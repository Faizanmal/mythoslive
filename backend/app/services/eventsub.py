import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import websockets
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.contracts.events import ActorIdentity, GameEvent
from app.core.settings import Settings
from app.repositories.oauth_tokens import OAuthTokenRepository
from app.services.ingress import EventSubDeduper, IngressPipeline
from app.services.twitch_helix import TwitchHelixClient

logger = logging.getLogger(__name__)


class EventSubMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str = Field(min_length=1, max_length=128)
    message_type: str = Field(min_length=1, max_length=64)
    message_timestamp: datetime
    subscription_type: str | None = None
    subscription_version: str | None = None


class EventSubEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: EventSubMetadata
    payload: dict[str, Any]


class ChatBadge(BaseModel):
    model_config = ConfigDict(extra="allow")

    set_id: str


class ChatText(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str = Field(max_length=500)


class ChatNotification(BaseModel):
    model_config = ConfigDict(extra="allow")

    broadcaster_user_id: str
    chatter_user_id: str
    chatter_user_name: str
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    message: ChatText
    badges: list[ChatBadge] = Field(default_factory=list)
    chatter_is_moderator: bool = False
    chatter_is_broadcaster: bool = False


class FollowNotification(BaseModel):
    model_config = ConfigDict(extra="allow")

    broadcaster_user_id: str
    user_id: str
    user_name: str
    followed_at: datetime


class RaidNotification(BaseModel):
    model_config = ConfigDict(extra="allow")

    from_broadcaster_user_id: str
    from_broadcaster_user_name: str
    to_broadcaster_user_id: str
    to_broadcaster_user_name: str
    viewers: int = Field(ge=0)


class EventSubManager:
    def __init__(
        self,
        settings: Settings,
        tokens: OAuthTokenRepository,
        helix: TwitchHelixClient,
        ingress: IngressPipeline,
        websocket_connect=websockets.connect,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self.helix = helix
        self.ingress = ingress
        self._websocket_connect = websocket_connect
        self.deduper = EventSubDeduper()
        self._task: asyncio.Task[None] | None = None
        self._socket: Any | None = None
        self._stopping = False
        self._status = "disconnected"
        self._session_id: str | None = None
        self._subscriptions: dict[str, str] = {
            "channel.chat.message": "not_started",
            "channel.follow": "not_started",
            "channel.raid": "not_started",
        }
        self._last_keepalive_at: datetime | None = None
        self._last_message_at: datetime | None = None
        self._last_error: str | None = None
        self._retry_attempt = 0

    @property
    def status(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "session_id": self._session_id,
            "subscriptions": dict(self._subscriptions),
            "last_keepalive_at": self._last_keepalive_at,
            "last_message_at": self._last_message_at,
            "last_error": self._last_error,
            "retry_attempt": self._retry_attempt,
        }

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._status = "connecting"
        self._last_error = None
        self._retry_attempt = 0
        self._task = asyncio.create_task(self._run(), name="twitch-eventsub")

    async def stop(self) -> None:
        self._stopping = True
        socket = self._socket
        if socket is not None:
            await socket.close()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._socket = None
        self._session_id = None
        self._status = "disconnected"

    async def _run(self) -> None:
        failures = 0
        while not self._stopping:
            self._status = "connecting"
            try:
                await self._connection_cycle()
                if self._stopping:
                    break
                failures += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                self._last_error = self._safe_error(exc)
                self._status = "degraded"
                logger.warning("EventSub connection ended: %s", self._last_error)
                socket, self._socket = self._socket, None
                if socket is not None:
                    try:
                        await socket.close()
                    except Exception:
                        pass
            if failures > self.settings.eventsub_max_retries:
                self._status = "degraded"
                self._retry_attempt = failures
                return
            self._retry_attempt = failures
            delay = min(60.0, float(2 ** min(failures - 1, 6))) * random.uniform(0.8, 1.2)
            await asyncio.sleep(delay)
        self._status = "disconnected"

    async def _connection_cycle(self) -> None:
        websocket = await self._websocket_connect(
            self.settings.twitch_eventsub_url,
            open_timeout=10,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=10,
            max_size=1_048_576,
        )
        self._socket = websocket
        welcome = await self._receive_envelope(websocket, timeout=10)
        session_id, keepalive = self._read_welcome(welcome)
        self._accept_welcome(session_id, keepalive)
        await self._create_required_subscriptions(session_id)

        while not self._stopping:
            try:
                envelope = await self._receive_envelope(websocket, timeout=float(keepalive) + 2.0)
            except TimeoutError as exc:
                raise RuntimeError("EventSub keepalive deadline was exceeded") from exc
            self._last_message_at = datetime.now(UTC)
            message_type = envelope.metadata.message_type
            if message_type == "session_keepalive":
                self._last_keepalive_at = datetime.now(UTC)
            elif message_type == "notification":
                await self._handle_notification(envelope)
            elif message_type == "session_reconnect":
                reconnect_url = envelope.payload.get("session", {}).get("reconnect_url")
                if not isinstance(reconnect_url, str) or not reconnect_url.startswith("wss://"):
                    raise RuntimeError("EventSub supplied an invalid reconnect URL")
                replacement = await self._websocket_connect(
                    reconnect_url,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=1_048_576,
                )
                new_welcome = await self._receive_envelope(replacement, timeout=10)
                new_session_id, new_keepalive = self._read_welcome(new_welcome)
                self._accept_welcome(new_session_id, new_keepalive)
                old_socket = websocket
                websocket = replacement
                self._socket = replacement
                # Twitch transfers the subscriptions; keep the old socket until the new welcome.
                await old_socket.close()
                keepalive = new_keepalive
            elif message_type == "revocation":
                self._handle_revocation(envelope)
            elif message_type == "session_welcome":
                raise RuntimeError("Unexpected EventSub welcome on an established connection")
            else:
                logger.info("Ignoring unknown EventSub message type %s", message_type)
        await websocket.close()

    async def _receive_envelope(self, websocket: Any, *, timeout: float) -> EventSubEnvelope:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
        if not isinstance(raw, str):
            raise ValueError("EventSub payload was not a text frame")
        data = json.loads(raw)
        return EventSubEnvelope.model_validate(data)

    @staticmethod
    def _read_welcome(envelope: EventSubEnvelope) -> tuple[str, int]:
        if envelope.metadata.message_type != "session_welcome":
            raise ValueError("EventSub connection did not start with session_welcome")
        session = envelope.payload.get("session")
        if not isinstance(session, dict):
            raise ValueError("EventSub welcome did not include a session object")
        session_id = session.get("id")
        keepalive = session.get("keepalive_timeout_seconds")
        if not isinstance(session_id, str) or not isinstance(keepalive, int):
            raise ValueError("EventSub welcome included invalid session values")
        if not 10 <= keepalive <= 600:
            raise ValueError("EventSub welcome keepalive timeout was outside documented bounds")
        return session_id, keepalive

    def _accept_welcome(self, session_id: str, _keepalive: int) -> None:
        self._session_id = session_id
        self._last_message_at = datetime.now(UTC)
        self._status = "connected"
        self._last_error = None

    async def _create_required_subscriptions(self, session_id: str) -> None:
        broadcaster = await self.tokens.get("broadcaster")
        bot = await self.tokens.get("bot")
        if broadcaster is None or bot is None or broadcaster.channel_id != bot.channel_id:
            raise RuntimeError(
                "Both broadcaster and linked bot authorization are required for EventSub"
            )
        if not broadcaster.twitch_user_id or not bot.twitch_user_id:
            raise RuntimeError("Saved Twitch roles are missing verified user identities")
        self.ingress.bot_user_id = bot.twitch_user_id
        world_id = await self.tokens.world_id()
        if world_id is None:
            raise RuntimeError("No MythosLive world exists for the connected broadcaster")
        jobs = {
            "channel.chat.message": self.helix.create_eventsub_subscription(
                role="bot",
                session_id=session_id,
                subscription_type="channel.chat.message",
                version="1",
                condition={
                    "broadcaster_user_id": broadcaster.twitch_user_id,
                    "user_id": bot.twitch_user_id,
                },
            ),
            "channel.follow": self.helix.create_eventsub_subscription(
                role="broadcaster",
                session_id=session_id,
                subscription_type="channel.follow",
                version="2",
                condition={
                    "broadcaster_user_id": broadcaster.twitch_user_id,
                    "moderator_user_id": broadcaster.twitch_user_id,
                },
            ),
            "channel.raid": self.helix.create_eventsub_subscription(
                role="broadcaster",
                session_id=session_id,
                subscription_type="channel.raid",
                version="1",
                condition={"to_broadcaster_user_id": broadcaster.twitch_user_id},
            ),
        }
        for name in jobs:
            self._subscriptions[name] = "pending"
        results = await asyncio.wait_for(
            asyncio.gather(*jobs.values(), return_exceptions=True), timeout=8
        )
        for name, result in zip(jobs, results, strict=True):
            if isinstance(result, BaseException):
                self._subscriptions[name] = "failed"
                self._last_error = (
                    f"{name} subscription failed; check Twitch scopes and channel authorization."
                )
                logger.warning("EventSub subscription failed for %s", name)
            else:
                self._subscriptions[name] = "enabled"
        if any(value != "enabled" for value in self._subscriptions.values()):
            self._status = "degraded"

    async def _handle_notification(self, envelope: EventSubEnvelope) -> None:
        if not self.deduper.accept(envelope.metadata.message_id):
            self.ingress.recorder.metrics.duplicates += 1
            return
        payload = envelope.payload.get("event")
        if not isinstance(payload, dict):
            logger.warning("Ignoring malformed EventSub notification")
            return
        source_type = envelope.metadata.subscription_type
        world_id = await self.tokens.world_id()
        if world_id is None:
            self._last_error = "Connected broadcaster has no MythosLive world."
            return
        event_uuid = self._event_id(envelope.metadata.message_id)
        try:
            if source_type == "channel.chat.message":
                chat = ChatNotification.model_validate(payload)
                is_mod = (
                    chat.chatter_is_moderator
                    or chat.chatter_is_broadcaster
                    or any(badge.set_id in {"moderator", "broadcaster"} for badge in chat.badges)
                )
                self.ingress.handle_chat(
                    message=chat.message.text,
                    source="twitch",
                    world_id=world_id,
                    user_id=chat.chatter_user_id,
                    display_name=chat.chatter_user_name,
                    color=chat.color,
                    is_moderator=is_mod,
                    event_id=event_uuid,
                    occurred_at=envelope.metadata.message_timestamp,
                )
            elif source_type == "channel.follow":
                follow = FollowNotification.model_validate(payload)
                event = GameEvent(
                    event_id=event_uuid,
                    event_type="channel.follow",
                    occurred_at=envelope.metadata.message_timestamp,
                    source="twitch",
                    world_id=world_id,
                    actor=ActorIdentity(
                        kind="twitch",
                        twitch_user_id=follow.user_id,
                        display_name=follow.user_name,
                    ),
                    payload={
                        "broadcaster_user_id": follow.broadcaster_user_id,
                        "followed_at": follow.followed_at.isoformat(),
                        "simulated": False,
                    },
                )
                self.ingress.record_social_event(event)
            elif source_type == "channel.raid":
                raid = RaidNotification.model_validate(payload)
                event = GameEvent(
                    event_id=event_uuid,
                    event_type="channel.raid",
                    occurred_at=envelope.metadata.message_timestamp,
                    source="twitch",
                    world_id=world_id,
                    payload={
                        "from_broadcaster_user_id": raid.from_broadcaster_user_id,
                        "from_broadcaster_user_name": raid.from_broadcaster_user_name,
                        "to_broadcaster_user_id": raid.to_broadcaster_user_id,
                        "to_broadcaster_user_name": raid.to_broadcaster_user_name,
                        "viewers": raid.viewers,
                        "simulated": False,
                    },
                )
                self.ingress.record_social_event(event)
        except ValidationError:
            logger.warning("Ignoring malformed EventSub notification for %s", source_type)

    def _handle_revocation(self, envelope: EventSubEnvelope) -> None:
        subscription = envelope.payload.get("subscription", {})
        if not isinstance(subscription, dict):
            self._last_error = "EventSub sent a malformed subscription revocation."
            self._status = "degraded"
            return
        subscription_type = subscription.get("type")
        subscription_status = subscription.get("status")
        if isinstance(subscription_type, str):
            self._subscriptions[subscription_type] = f"revoked:{subscription_status or 'unknown'}"
        self._last_error = f"EventSub subscription revoked: {subscription_status or 'unknown'}"
        self._status = "degraded"

    @staticmethod
    def _event_id(message_id: str) -> UUID:
        try:
            return UUID(message_id)
        except ValueError:
            return uuid5(NAMESPACE_URL, f"twitch-eventsub:{message_id}")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return "EventSub sent a malformed payload."
        if isinstance(exc, TimeoutError):
            return "EventSub keepalive deadline was exceeded."
        if isinstance(exc, RuntimeError) and str(exc) in {
            "EventSub connection did not start with session_welcome",
            "EventSub keepalive deadline was exceeded",
            "EventSub supplied an invalid reconnect URL",
            "Unexpected EventSub welcome on an established connection",
        }:
            return str(exc)
        return f"EventSub connection failed ({type(exc).__name__})."
