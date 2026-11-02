import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.settings import Settings
from app.services.twitch_oauth import OAuthRole, TwitchOAuthError, TwitchOAuthService

HELIX_BASE = "https://api.twitch.tv/helix"


class TwitchHelixError(RuntimeError):
    def __init__(
        self, status_code: int, message: str, response_headers: httpx.Headers | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_headers = response_headers or httpx.Headers()


@dataclass(frozen=True)
class SendChatResult:
    status: str
    message_id: str | None = None
    drop_code: str | None = None
    drop_reason: str | None = None
    retry_after_seconds: float | None = None


class TwitchHelixClient:
    def __init__(
        self,
        settings: Settings,
        oauth: TwitchOAuthService,
        http: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.oauth = oauth
        self.http = http

    async def create_eventsub_subscription(
        self,
        *,
        role: OAuthRole,
        session_id: str,
        subscription_type: str,
        version: str,
        condition: dict[str, str],
    ) -> None:
        await self.request(
            "POST",
            "/eventsub/subscriptions",
            role=role,
            json={
                "type": subscription_type,
                "version": version,
                "condition": condition,
                "transport": {"method": "websocket", "session_id": session_id},
            },
        )

    async def send_chat_message(self, message: str) -> SendChatResult:
        broadcaster = await self.oauth.repository.get("broadcaster")
        bot = await self.oauth.repository.get("bot")
        if broadcaster is None or bot is None:
            raise TwitchHelixError(409, "Both broadcaster and bot accounts must be connected.")
        if broadcaster.channel_id != bot.channel_id:
            raise TwitchHelixError(409, "Bot authorization is not linked to the connected channel.")
        if not self.oauth.settings.twitch_client_id:
            raise TwitchHelixError(503, "Twitch client credentials are not configured.")
        try:
            response = await self.request(
                "POST",
                "/chat/messages",
                role="bot",
                json={
                    "broadcaster_id": broadcaster.twitch_user_id,
                    "sender_id": bot.twitch_user_id,
                    "message": message,
                },
                return_rate_limit=True,
            )
        except TwitchHelixError as exc:
            if exc.status_code == 429:
                retry_after = self._retry_delay(exc.response_headers)
                return SendChatResult(status="rate_limited", retry_after_seconds=retry_after)
            raise
        data = response.json().get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return SendChatResult(status="unknown")
        item = data[0]
        if item.get("is_sent") is True:
            return SendChatResult(status="sent", message_id=item.get("message_id"))
        drop = item.get("drop_reason") or {}
        return SendChatResult(
            status="dropped",
            drop_code=drop.get("code"),
            drop_reason=drop.get("message"),
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        role: OAuthRole,
        json: dict[str, Any] | None = None,
        return_rate_limit: bool = False,
    ) -> httpx.Response:
        if not self.settings.twitch_client_id:
            raise TwitchHelixError(503, "Twitch client credentials are not configured.")
        token, _ = await self.oauth.access_token(role)
        response = await self._request_with_token(method, path, token, json)
        if response.status_code == 401:
            try:
                token = await self.oauth.refresh_after_401(role, token)
            except TwitchOAuthError as exc:
                raise TwitchHelixError(401, exc.public_message) from exc
            response = await self._request_with_token(method, path, token, json)
        if response.status_code == 429 and return_rate_limit:
            raise TwitchHelixError(429, "Twitch rate limit reached.", response.headers)
        if response.status_code >= 400:
            raise TwitchHelixError(
                response.status_code, f"Twitch API request failed ({response.status_code})."
            )
        return response

    async def _request_with_token(
        self, method: str, path: str, token: str, body: dict[str, Any] | None
    ) -> httpx.Response:
        return await self.http.request(
            method,
            f"{HELIX_BASE}{path}",
            headers={
                "Client-Id": self.settings.twitch_client_id or "",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    @staticmethod
    def _retry_delay(headers: httpx.Headers) -> float:
        retry_after = headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass
        reset = headers.get("Ratelimit-Reset")
        if reset:
            try:
                return max(1.0, float(reset) - datetime.now(UTC).timestamp() + 1.0)
            except ValueError:
                pass
        return 30.0


class ChatRateLimiter:
    def __init__(
        self,
        *,
        max_per_window: int = 20,
        window_seconds: float = 30,
        per_channel_interval: float = 1,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ) -> None:
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self.per_channel_interval = per_channel_interval
        self._clock = clock
        self._sleep = sleep
        self._sent: list[float] = []
        self._channel_last: dict[str, float] = {}
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, self._clock() + max(0.0, seconds))

    async def wait_turn(self, channel_id: str) -> None:
        while True:
            now = self._clock()
            self._sent = [sent_at for sent_at in self._sent if sent_at > now - self.window_seconds]
            wait = max(0.0, self._blocked_until - now)
            previous = self._channel_last.get(channel_id)
            if previous is not None:
                wait = max(wait, previous + self.per_channel_interval - now)
            if len(self._sent) >= self.max_per_window:
                wait = max(wait, self._sent[0] + self.window_seconds - now)
            if wait <= 0:
                self._sent.append(now)
                self._channel_last[channel_id] = now
                return
            await self._sleep(wait)
