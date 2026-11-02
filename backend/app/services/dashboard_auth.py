"""Signed broadcaster session cookies and same-origin CSRF protection."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response
from sqlalchemy import select

from app.core.settings import Settings
from app.models.entities import Channel, OAuthToken, World

SESSION_COOKIE = "mythos_dashboard_session"
CSRF_COOKIE = "mythos_dashboard_csrf"
SESSION_SECONDS = 12 * 60 * 60
SIMULATOR_ID = "local-simulator"


@dataclass(frozen=True)
class DashboardPrincipal:
    broadcaster_id: str
    channel_id: str
    world_id: str
    simulator: bool = False


class DashboardAuth:
    def __init__(self, settings: Settings) -> None:
        if not settings.encryption_key:
            raise RuntimeError("Dashboard sessions require ENCRYPTION_KEY to be configured.")
        self.settings = settings
        self._key = hashlib.sha256(
            b"mythoslive/dashboard-session/v1/" + settings.encryption_key.encode()
        ).digest()

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def issue(self, broadcaster_id: str) -> str:
        now = int(time.time())
        payload = self._b64(
            json.dumps(
                {"sub": broadcaster_id, "iat": now, "exp": now + SESSION_SECONDS},
                separators=(",", ":"),
            ).encode()
        )
        signature = self._b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def read(self, token: str) -> str | None:
        if not token or len(token) > 2_048 or token.count(".") != 1:
            return None
        payload, signature = token.split(".", 1)
        expected = self._b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            claims = json.loads(self._unb64(payload))
            sub, expires, issued = claims["sub"], int(claims["exp"]), int(claims["iat"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
        if (
            not isinstance(sub, str)
            or not sub
            or expires <= time.time()
            or issued > time.time() + 60
        ):
            return None
        return sub

    def set_cookies(self, response: Response, broadcaster_id: str) -> None:
        csrf = secrets.token_urlsafe(32)
        response.set_cookie(
            SESSION_COOKIE,
            self.issue(broadcaster_id),
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            max_age=SESSION_SECONDS,
            httponly=False,
            secure=True,
            samesite="strict",
            path="/",
        )

    @staticmethod
    def clear_cookies(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")

    def verify_csrf(self, request: Request) -> None:
        origin = request.headers.get("origin")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get("x-mythos-csrf", "")
        if (
            origin not in self.settings.cors_origins
            or not cookie
            or not header
            or not hmac.compare_digest(cookie, header)
        ):
            raise HTTPException(status_code=403, detail="CSRF validation failed.")

    async def authenticate(self, request: Request) -> DashboardPrincipal:
        broadcaster_id = self.read(request.cookies.get(SESSION_COOKIE, ""))
        if broadcaster_id is None:
            raise HTTPException(status_code=401, detail="Broadcaster sign-in is required.")
        if broadcaster_id == SIMULATOR_ID:
            host = request.url.hostname
            origin = request.headers.get("origin")
            if (
                self.settings.environment != "development"
                or host not in {"localhost", "127.0.0.1"}
                or origin not in self.settings.cors_origins
            ):
                raise HTTPException(status_code=403, detail="Simulator sign-in is local-only.")
            async with request.app.state.db_sessions() as db:
                row = await db.execute(
                    select(Channel.id, World.id)
                    .join(World, World.channel_id == Channel.id)
                    .where(Channel.twitch_broadcaster_id == SIMULATOR_ID)
                )
                found = row.first()
            if not found:
                raise HTTPException(status_code=403, detail="Simulator world is unavailable.")
            return DashboardPrincipal(SIMULATOR_ID, str(found[0]), str(found[1]), simulator=True)

        async with request.app.state.db_sessions() as db:
            row = await db.execute(
                select(Channel.id, World.id)
                .join(World, World.channel_id == Channel.id)
                .join(OAuthToken, OAuthToken.channel_id == Channel.id)
                .where(
                    Channel.twitch_broadcaster_id == broadcaster_id,
                    Channel.status == "active",
                    OAuthToken.role == "broadcaster",
                    OAuthToken.twitch_user_id == broadcaster_id,
                    World.slug == "mythoslive",
                )
            )
            found = row.first()
        if not found:
            raise HTTPException(
                status_code=401, detail="Broadcaster connection is no longer active."
            )
        return DashboardPrincipal(broadcaster_id, str(found[0]), str(found[1]))


async def require_dashboard(request: Request) -> DashboardPrincipal:
    auth: DashboardAuth = request.app.state.dashboard_auth
    principal = await auth.authenticate(request)
    request.state.dashboard_principal = principal
    return principal


async def require_dashboard_mutation(request: Request) -> DashboardPrincipal:
    principal = await require_dashboard(request)
    request.app.state.dashboard_auth.verify_csrf(request)
    return principal
