import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.encryption import TokenCipher
from app.core.settings import Settings
from app.repositories.oauth_tokens import StoredOAuthToken
from app.services.twitch_oauth import (
    REQUIRED_SCOPES,
    TwitchOAuthError,
    TwitchOAuthService,
)


class _Repository:
    def __init__(self, record):
        self.record = record

    async def get(self, _role):
        return self.record

    async def save(self, **values):
        values.pop("display_name")
        self.record = StoredOAuthToken(**values, channel_id=UUID(int=1))
        return self.record


@pytest.mark.asyncio
async def test_refresh_lock_prevents_double_rotation_and_replaces_secret() -> None:
    encryption_key = Fernet.generate_key().decode()
    cipher = TokenCipher(encryption_key)
    scopes = sorted(REQUIRED_SCOPES["bot"])
    record = StoredOAuthToken(
        channel_id=UUID(int=1),
        role="bot",
        twitch_user_id="bot-id",
        scopes=scopes,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        access_token_encrypted=cipher.encrypt("old-access"),
        refresh_token_encrypted=cipher.encrypt("old-refresh"),
    )
    repository = _Repository(record)
    token_posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_posts
        if request.url.path.endswith("/token"):
            token_posts += 1
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                    "scope": scopes,
                    "token_type": "bearer",
                },
            )
        return httpx.Response(
            200,
            json={
                "client_id": "client-id",
                "login": "bot",
                "scopes": scopes,
                "user_id": "bot-id",
                "expires_in": 3600,
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = TwitchOAuthService(
        Settings(
            _env_file=None,
            twitch_client_id="client-id",
            twitch_client_secret="secret",
            encryption_key=encryption_key,
        ),
        repository,
        http,
    )
    try:
        first, second = await asyncio.gather(
            service.refresh_after_401("bot", "old-access"),
            service.refresh_after_401("bot", "old-access"),
        )
    finally:
        await http.aclose()
    assert token_posts == 1
    assert first == second == "new-access"
    assert cipher.decrypt(repository.record.refresh_token_encrypted) == "new-refresh"


@pytest.mark.asyncio
async def test_scope_validation_rejects_missing_permissions() -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "client_id": "client-id",
                    "login": "bot",
                    "scopes": ["user:read:chat"],
                    "user_id": "bot-id",
                    "expires_in": 3600,
                },
            )
        )
    )
    settings = Settings(
        _env_file=None,
        twitch_client_id="client-id",
        twitch_client_secret="secret",
        encryption_key=Fernet.generate_key().decode(),
    )
    service = TwitchOAuthService(settings, _Repository(None), http)
    try:
        with pytest.raises(TwitchOAuthError, match="missing required scopes"):
            await service._validate("token-value", "bot")
    finally:
        await http.aclose()
