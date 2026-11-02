import asyncio
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ValidationError

from app.core.encryption import TokenCipher, TokenEncryptionError
from app.core.settings import Settings
from app.repositories.oauth_tokens import OAuthTokenRepository, StoredOAuthToken

OAuthRole = Literal["broadcaster", "bot"]
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
REVOKE_URL = "https://id.twitch.tv/oauth2/revoke"
AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"

REQUIRED_SCOPES: dict[OAuthRole, frozenset[str]] = {
    "broadcaster": frozenset({"channel:bot", "moderator:read:followers"}),
    "bot": frozenset({"user:read:chat", "user:write:chat", "user:bot"}),
}


class TwitchOAuthError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message


class OAuthStateStore:
    """Single-process, one-use OAuth CSRF state with a bounded lifetime."""

    def __init__(self, ttl_seconds: int = 600, max_pending: int = 512) -> None:
        self._ttl = ttl_seconds
        self._max_pending = max_pending
        self._states: dict[str, tuple[OAuthRole, float]] = {}
        self._lock = asyncio.Lock()

    async def issue(self, role: OAuthRole) -> str:
        now = time.monotonic()
        async with self._lock:
            self._prune(now)
            if len(self._states) >= self._max_pending:
                oldest = min(self._states, key=lambda key: self._states[key][1])
                self._states.pop(oldest, None)
            state = secrets.token_urlsafe(32)
            self._states[state] = (role, now + self._ttl)
            return state

    async def consume(self, role: OAuthRole, received: str | None) -> bool:
        if not received:
            return False
        now = time.monotonic()
        async with self._lock:
            stored = self._states.pop(received, None)
            if stored is None:
                return False
            expected_role, expires_at = stored
            return expires_at > now and expected_role == role

    def _prune(self, now: float) -> None:
        for state, (_, expires_at) in list(self._states.items()):
            if expires_at <= now:
                self._states.pop(state, None)


class TokenGrant(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int
    scope: list[str] | str = []
    token_type: str


class ValidatedToken(BaseModel):
    client_id: str
    login: str
    scopes: list[str]
    user_id: str
    expires_in: int


@dataclass(frozen=True)
class OAuthStatus:
    status: str
    error: str | None = None
    last_validated_at: datetime | None = None


def token_scopes(value: list[str] | str) -> list[str]:
    return value.split() if isinstance(value, str) else value


class TwitchOAuthService:
    def __init__(
        self,
        settings: Settings,
        repository: OAuthTokenRepository,
        http: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.http = http
        self.cipher = TokenCipher(settings.encryption_key)
        self.states = OAuthStateStore()
        self._refresh_locks: dict[str, asyncio.Lock] = {
            "broadcaster": asyncio.Lock(),
            "bot": asyncio.Lock(),
        }
        self._status: dict[str, OAuthStatus] = {
            "broadcaster": OAuthStatus("disconnected"),
            "bot": OAuthStatus("disconnected"),
        }

    @property
    def configured(self) -> bool:
        return bool(self.settings.twitch_client_id and self.settings.twitch_client_secret)

    def redirect_uri(self, role: OAuthRole) -> str:
        return (
            self.settings.twitch_broadcaster_redirect_uri
            if role == "broadcaster"
            else self.settings.twitch_bot_redirect_uri
        )

    def status(self, role: OAuthRole) -> OAuthStatus:
        return self._status[role]

    async def begin(self, role: OAuthRole) -> str:
        self._require_configured()
        if role == "bot" and await self.repository.get("broadcaster") is None:
            raise TwitchOAuthError("broadcaster_required", "Connect the broadcaster account first.")
        state = await self.states.issue(role)
        params = {
            "response_type": "code",
            "client_id": self.settings.twitch_client_id,
            "redirect_uri": self.redirect_uri(role),
            "scope": " ".join(sorted(REQUIRED_SCOPES[role])),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def complete(self, role: OAuthRole, code: str, state: str | None) -> StoredOAuthToken:
        self._require_configured()
        if not await self.states.consume(role, state):
            raise TwitchOAuthError("invalid_state", "OAuth state was missing, expired, or invalid.")
        grant = await self._exchange_code(code, role)
        validated = await self._validate(grant.access_token, role)
        if validated.user_id == "":
            raise TwitchOAuthError("invalid_identity", "Twitch did not return a user identity.")
        scopes = sorted(set(validated.scopes))
        missing = REQUIRED_SCOPES[role].difference(scopes)
        if missing:
            raise TwitchOAuthError(
                "missing_scope",
                f"Twitch authorization is missing required scopes: {', '.join(sorted(missing))}.",
            )
        if role == "bot":
            broadcaster = await self.repository.get("broadcaster")
            if broadcaster is None:
                raise TwitchOAuthError(
                    "broadcaster_required", "Connect the broadcaster account first."
                )
        expires_at = datetime.now(UTC) + timedelta(
            seconds=min(grant.expires_in, validated.expires_in)
        )
        try:
            record = await self.repository.save(
                role=role,
                twitch_user_id=validated.user_id,
                display_name=validated.login,
                scopes=scopes,
                expires_at=expires_at,
                access_token_encrypted=self.cipher.encrypt(grant.access_token),
                refresh_token_encrypted=(
                    self.cipher.encrypt(grant.refresh_token) if grant.refresh_token else None
                ),
            )
        except TokenEncryptionError as exc:
            raise TwitchOAuthError("encryption_unavailable", str(exc)) from exc
        self._status[role] = OAuthStatus("connected", last_validated_at=datetime.now(UTC))
        return record

    async def access_token(self, role: OAuthRole) -> tuple[str, StoredOAuthToken]:
        record = await self.repository.get(role)
        if record is None:
            raise TwitchOAuthError("not_connected", f"The {role} account is not connected.")
        try:
            return self.cipher.decrypt(record.access_token_encrypted), record
        except TokenEncryptionError as exc:
            raise TwitchOAuthError(
                "encryption_error", "Stored Twitch credentials could not be decrypted."
            ) from exc

    async def refresh_after_401(self, role: OAuthRole, rejected_access_token: str) -> str:
        async with self._refresh_locks[role]:
            record = await self.repository.get(role)
            if record is None or record.refresh_token_encrypted is None:
                raise TwitchOAuthError("reauthorization_required", f"Reconnect the {role} account.")
            current = self.cipher.decrypt(record.access_token_encrypted)
            if current != rejected_access_token:
                return current
            refresh = self.cipher.decrypt(record.refresh_token_encrypted)
            try:
                response = await self.http.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                        "client_id": self.settings.twitch_client_id,
                        "client_secret": self.settings.twitch_client_secret,
                    },
                )
                response.raise_for_status()
                grant = TokenGrant.model_validate(response.json())
                validated = await self._validate(grant.access_token, role)
            except (httpx.HTTPError, ValidationError, ValueError) as exc:
                self._status[role] = OAuthStatus(
                    "reauthorization_required", "Token refresh failed."
                )
                raise TwitchOAuthError(
                    "reauthorization_required", f"Reconnect the {role} account."
                ) from exc
            if validated.user_id != record.twitch_user_id:
                raise TwitchOAuthError(
                    "identity_changed", "Refreshed Twitch identity did not match the saved role."
                )
            scopes = sorted(set(validated.scopes))
            missing = REQUIRED_SCOPES[role].difference(scopes)
            if missing:
                raise TwitchOAuthError(
                    "missing_scope",
                    f"Required scopes are no longer authorized: {', '.join(sorted(missing))}.",
                )
            updated = await self.repository.save(
                role=role,
                twitch_user_id=validated.user_id,
                display_name=validated.login,
                scopes=scopes,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=min(grant.expires_in, validated.expires_in)),
                access_token_encrypted=self.cipher.encrypt(grant.access_token),
                refresh_token_encrypted=(
                    self.cipher.encrypt(grant.refresh_token)
                    if grant.refresh_token
                    else record.refresh_token_encrypted
                ),
            )
            self._status[role] = OAuthStatus("connected", last_validated_at=datetime.now(UTC))
            return self.cipher.decrypt(updated.access_token_encrypted)

    async def validate_saved(self, role: OAuthRole) -> bool:
        record = await self.repository.get(role)
        if record is None:
            self._status[role] = OAuthStatus("disconnected")
            return False
        try:
            token = self.cipher.decrypt(record.access_token_encrypted)
            identity = await self._validate(token, role)
            if identity.user_id != record.twitch_user_id:
                raise TwitchOAuthError(
                    "identity_changed", "Saved token identity no longer matches this role."
                )
            missing = REQUIRED_SCOPES[role].difference(identity.scopes)
            if missing:
                raise TwitchOAuthError(
                    "missing_scope", "Reconnect and approve the required Twitch permissions."
                )
        except (TwitchOAuthError, TokenEncryptionError) as exc:
            self._status[role] = OAuthStatus("reauthorization_required", str(exc))
            return False
        except httpx.HTTPError:
            self._status[role] = OAuthStatus(
                "degraded", "Twitch token validation could not be reached."
            )
            return False
        self._status[role] = OAuthStatus("connected", last_validated_at=datetime.now(UTC))
        return True

    async def disconnect(self, role: OAuthRole) -> None:
        record = await self.repository.get(role)
        if record and self.configured:
            access = self.cipher.decrypt(record.access_token_encrypted)
            response = await self.http.post(
                REVOKE_URL,
                data={"client_id": self.settings.twitch_client_id, "token": access},
            )
            if response.status_code not in (200, 400):
                response.raise_for_status()
        await self.repository.delete(role)
        self._status[role] = OAuthStatus("disconnected")

    async def validation_loop(self, interval_seconds: int = 3600) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            for role in ("broadcaster", "bot"):
                await self.validate_saved(role)

    async def _exchange_code(self, code: str, role: OAuthRole) -> TokenGrant:
        try:
            response = await self.http.post(
                TOKEN_URL,
                data={
                    "client_id": self.settings.twitch_client_id,
                    "client_secret": self.settings.twitch_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri(role),
                },
            )
            response.raise_for_status()
            grant = TokenGrant.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise TwitchOAuthError(
                "token_exchange_failed", "Twitch authorization could not be completed."
            ) from exc
        if not grant.refresh_token or grant.token_type.lower() != "bearer" or grant.expires_in <= 0:
            raise TwitchOAuthError(
                "invalid_token_response", "Twitch returned an incomplete user token."
            )
        missing = REQUIRED_SCOPES[role].difference(token_scopes(grant.scope))
        if missing:
            raise TwitchOAuthError(
                "missing_scope",
                f"Twitch authorization is missing required scopes: {', '.join(sorted(missing))}.",
            )
        return grant

    async def _validate(self, access_token: str, role: OAuthRole) -> ValidatedToken:
        try:
            response = await self.http.get(
                VALIDATE_URL, headers={"Authorization": f"OAuth {access_token}"}
            )
            response.raise_for_status()
            token = ValidatedToken.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise TwitchOAuthError(
                "token_validation_failed", "Twitch did not validate the user token."
            ) from exc
        if token.client_id != self.settings.twitch_client_id or not token.user_id:
            raise TwitchOAuthError(
                "token_identity_mismatch", "Twitch token client or user identity did not match."
            )
        missing = REQUIRED_SCOPES[role].difference(token.scopes)
        if missing:
            raise TwitchOAuthError(
                "missing_scope",
                f"Twitch token is missing required scopes: {', '.join(sorted(missing))}.",
            )
        return token

    def _require_configured(self) -> None:
        if not self.configured:
            raise TwitchOAuthError(
                "not_configured", "Configure Twitch client credentials before connecting."
            )
