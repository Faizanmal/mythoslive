import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.core.settings import Settings
from app.services.chat_outbox import ChatOutbox
from app.services.eventsub import EventSubEnvelope, EventSubManager
from app.services.ingress import EventRecorder, IngressPipeline
from app.services.twitch_helix import (
    ChatRateLimiter,
    SendChatResult,
    TwitchHelixClient,
)


class _Tokens:
    async def get(self, role):
        return type(
            "Token",
            (),
            {
                "channel_id": UUID(int=1),
                "twitch_user_id": "broadcaster" if role == "broadcaster" else "bot",
            },
        )()

    async def world_id(self):
        return UUID("6c9f5a98-8f43-5bd5-a263-239ea8b494fc")


class _UnusedHelix:
    async def create_eventsub_subscription(self, **_kwargs):
        return None


def _envelope(message_type: str, payload: dict, *, sub_type: str | None = None):
    return EventSubEnvelope.model_validate(
        {
            "metadata": {
                "message_id": "e7f328a9-f123-4880-a865-33b76c523a11",
                "message_type": message_type,
                "message_timestamp": datetime.now(UTC).isoformat(),
                "subscription_type": sub_type,
            },
            "payload": payload,
        }
    )


def test_welcome_keepalive_and_reconnect_message_fixtures() -> None:
    welcome = _envelope(
        "session_welcome",
        {
            "session": {
                "id": "session-1",
                "keepalive_timeout_seconds": 30,
                "status": "connected",
                "connected_at": datetime.now(UTC).isoformat(),
            }
        },
    )
    assert EventSubManager._read_welcome(welcome) == ("session-1", 30)
    keepalive = _envelope("session_keepalive", {})
    assert keepalive.metadata.message_type == "session_keepalive"
    reconnect = _envelope(
        "session_reconnect", {"session": {"reconnect_url": "wss://example.test/ws"}}
    )
    assert reconnect.payload["session"]["reconnect_url"].startswith("wss://")


@pytest.mark.asyncio
async def test_notification_normalizes_once_and_revocation_degrades() -> None:
    settings = Settings(_env_file=None)
    recorder = EventRecorder()
    ingress = IngressPipeline(settings, recorder)
    manager = EventSubManager(settings, _Tokens(), _UnusedHelix(), ingress)
    envelope = _envelope(
        "notification",
        {
            "subscription": {"type": "channel.chat.message"},
            "event": {
                "broadcaster_user_id": "b1",
                "chatter_user_id": "v1",
                "chatter_user_name": "Viewer",
                "message": {"text": "!join", "fragments": []},
                "badges": [],
                "chatter_is_moderator": False,
                "chatter_is_broadcaster": False,
            },
        },
        sub_type="channel.chat.message",
    )
    await manager._handle_notification(envelope)
    await manager._handle_notification(envelope)
    assert len(recorder.since()) == 1
    assert recorder.since()[0][1].event_type == "chat.command.join"
    manager._handle_revocation(
        _envelope(
            "revocation",
            {"subscription": {"type": "channel.chat.message", "status": "authorization_revoked"}},
        )
    )
    assert manager.status["status"] == "degraded"
    assert manager.status["subscriptions"]["channel.chat.message"].startswith("revoked")


@pytest.mark.asyncio
async def test_reconnect_waits_for_new_welcome_before_closing_old_socket() -> None:
    welcome = {
        "metadata": {
            "message_id": "welcome-id",
            "message_type": "session_welcome",
            "message_timestamp": datetime.now(UTC).isoformat(),
        },
        "payload": {"session": {"id": "session", "keepalive_timeout_seconds": 30}},
    }
    handover = {
        "metadata": {
            "message_id": "reconnect-id",
            "message_type": "session_reconnect",
            "message_timestamp": datetime.now(UTC).isoformat(),
        },
        "payload": {"session": {"reconnect_url": "wss://handover.test/ws"}},
    }
    old_socket = _FakeSocket([welcome, handover])
    new_socket = _FakeSocket([welcome])
    urls = []

    async def connect(url, **_kwargs):
        urls.append(url)
        return old_socket if len(urls) == 1 else new_socket

    manager = EventSubManager(
        Settings(_env_file=None),
        _Tokens(),
        _UnusedHelix(),
        IngressPipeline(Settings(_env_file=None), EventRecorder()),
        websocket_connect=connect,
    )
    task = asyncio.create_task(manager._connection_cycle())
    try:
        await asyncio.wait_for(old_socket.closed.wait(), timeout=1)
        assert urls == ["wss://eventsub.wss.twitch.tv/ws", "wss://handover.test/ws"]
        assert not new_socket.closed.is_set()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_follow_notification_continues_after_eventsub_handover() -> None:
    def wire(message_id: str, message_type: str, payload: dict):
        return {
            "metadata": {
                "message_id": message_id,
                "message_type": message_type,
                "message_timestamp": datetime.now(UTC).isoformat(),
                **(
                    {"subscription_type": "channel.follow"}
                    if message_type == "notification"
                    else {}
                ),
            },
            "payload": payload,
        }

    welcome = wire("welcome-follow", "session_welcome", {
        "session": {"id": "session-active", "keepalive_timeout_seconds": 30},
    })
    handover = wire("handover-follow", "session_reconnect", {
        "session": {"reconnect_url": "wss://handover.test/ws"},
    })
    notification = wire("d4c9c57a-2e48-443d-a50d-828fe63cc704", "notification", {
        "subscription": {"type": "channel.follow"},
        "event": {
            "user_id": "viewer-1", "user_login": "emberfriend", "user_name": "Emberfriend",
            "broadcaster_user_id": "broadcaster", "broadcaster_user_login": "host",
            "broadcaster_user_name": "Host", "followed_at": datetime.now(UTC).isoformat(),
        },
    })
    old_socket = _FakeSocket([welcome, handover])
    new_socket = _FakeSocket([welcome, notification])
    recorder = EventRecorder()
    settings = Settings(_env_file=None)
    ingress = IngressPipeline(settings, recorder)
    urls = []

    async def connect(url, **_kwargs):
        urls.append(url)
        return old_socket if len(urls) == 1 else new_socket

    manager = EventSubManager(settings, _Tokens(), _UnusedHelix(), ingress,
                              websocket_connect=connect)
    task = asyncio.create_task(manager._connection_cycle())
    try:
        async with asyncio.timeout(1):
            while not recorder.since():
                await asyncio.sleep(0.01)
        assert urls[-1] == "wss://handover.test/ws"
        assert recorder.since()[0][1].event_type == "channel.follow"
        assert manager.status["status"] == "connected"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class _FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.closed = asyncio.Event()

    async def recv(self):
        if self.messages:
            return __import__("json").dumps(self.messages.pop(0))
        await asyncio.Future()

    async def close(self):
        self.closed.set()


@pytest.mark.asyncio
async def test_helix_dropped_message_is_reported() -> None:
    class Repo:
        async def get(self, role):
            return type("Token", (), {"channel_id": UUID(int=1), "twitch_user_id": role})()

    class OAuth:
        repository = Repo()
        settings = type("S", (), {"twitch_client_id": "client"})()

    class Client(TwitchHelixClient):
        async def request(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "is_sent": False,
                            "drop_reason": {"code": "msg_rejected", "message": "blocked"},
                        }
                    ]
                },
            )

    client = Client(Settings(_env_file=None), OAuth(), httpx.AsyncClient())
    try:
        result = await client.send_chat_message("hello")
    finally:
        await client.http.aclose()
    assert result.status == "dropped"
    assert result.drop_code == "msg_rejected"


@pytest.mark.asyncio
async def test_outbox_rejects_sim_messages_and_reports_drop() -> None:
    class Helix:
        async def send_chat_message(self, _message):
            return SendChatResult("dropped", drop_reason="Twitch rejected this message")

    settings = Settings(_env_file=None, chat_channel_interval_seconds=0)
    outbox = ChatOutbox(settings, Helix())
    outbox.start()
    outbox.set_enabled(True)
    try:
        with pytest.raises(RuntimeError, match="Simulator"):
            await outbox.enqueue(channel_id="channel", message="hello", source="simulator")
        result = await outbox.enqueue(channel_id="channel", message="hello", source="twitch")
        assert result.status == "dropped"
        batch = await outbox.enqueue_batch(
            channel_id="channel", messages=["first", "second"], source="twitch"
        )
        assert [item.status for item in batch] == ["dropped", "dropped"]
        assert outbox.dropped == 3
        with pytest.raises(ValueError, match="500"):
            await outbox.enqueue(channel_id="channel", message="x" * 501, source="twitch")
    finally:
        await outbox.stop()


@pytest.mark.asyncio
async def test_outbox_rate_limiter_honors_global_window_and_channel_gap() -> None:
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds

    limiter = ChatRateLimiter(
        max_per_window=1,
        window_seconds=30,
        per_channel_interval=1,
        clock=lambda: now[0],
        sleep=sleep,
    )
    await limiter.wait_turn("channel")
    assert now[0] == 0
    await limiter.wait_turn("channel")
    assert now[0] >= 30


def test_explicit_twitch_429_uses_rate_headers() -> None:
    headers = httpx.Headers({"Retry-After": "12", "Ratelimit-Reset": "9999999999"})
    assert TwitchHelixClient._retry_delay(headers) == 12
