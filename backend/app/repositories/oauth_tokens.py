from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.entities import Channel, OAuthToken, World


@dataclass(frozen=True)
class StoredOAuthToken:
    channel_id: UUID
    role: str
    twitch_user_id: str | None
    scopes: list[str]
    expires_at: datetime | None
    access_token_encrypted: bytes
    refresh_token_encrypted: bytes | None


class OAuthTokenRepository:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def get(self, role: str) -> StoredOAuthToken | None:
        async with self._sessions() as session:
            stmt = (
                select(OAuthToken)
                .join(Channel, Channel.id == OAuthToken.channel_id)
                .where(OAuthToken.role == role)
                .order_by(OAuthToken.created_at.desc())
                .limit(1)
            )
            token = await session.scalar(stmt)
            if token is None:
                return None
            return StoredOAuthToken(
                channel_id=token.channel_id,
                role=token.role,
                twitch_user_id=token.twitch_user_id,
                scopes=list(token.scopes),
                expires_at=token.expires_at,
                access_token_encrypted=token.access_token_encrypted,
                refresh_token_encrypted=token.refresh_token_encrypted,
            )

    async def save(
        self,
        *,
        role: str,
        twitch_user_id: str,
        display_name: str,
        scopes: list[str],
        expires_at: datetime,
        access_token_encrypted: bytes,
        refresh_token_encrypted: bytes | None,
    ) -> StoredOAuthToken:
        async with self._sessions.begin() as session:
            if role == "broadcaster":
                channel = await session.scalar(
                    select(Channel).where(Channel.twitch_broadcaster_id == twitch_user_id)
                )
                if channel is None:
                    channel = Channel(
                        twitch_broadcaster_id=twitch_user_id, display_name=display_name
                    )
                    session.add(channel)
                    await session.flush()
                else:
                    channel.display_name = display_name
                world = await session.scalar(
                    select(World).where(World.channel_id == channel.id, World.slug == "mythoslive")
                )
                if world is None:
                    session.add(World(channel_id=channel.id, slug="mythoslive", name="MythosLive"))
            else:
                broadcaster_token = await session.scalar(
                    select(OAuthToken)
                    .where(OAuthToken.role == "broadcaster")
                    .order_by(OAuthToken.created_at.desc())
                    .limit(1)
                )
                if broadcaster_token is None:
                    raise RuntimeError("Connect the broadcaster account before the bot account")
                channel = await session.get(Channel, broadcaster_token.channel_id)

            # A role represents one active Twitch identity for this local installation.
            await session.execute(
                delete(OAuthToken).where(
                    OAuthToken.role == role,
                    OAuthToken.channel_id != channel.id,
                )
            )

            token = await session.scalar(
                select(OAuthToken).where(
                    OAuthToken.channel_id == channel.id, OAuthToken.role == role
                )
            )
            if token is None:
                token = OAuthToken(channel_id=channel.id, role=role)
                session.add(token)
            token.twitch_user_id = twitch_user_id
            token.scopes = scopes
            token.expires_at = expires_at
            token.access_token_encrypted = access_token_encrypted
            token.refresh_token_encrypted = refresh_token_encrypted
            await session.flush()
            return StoredOAuthToken(
                channel_id=channel.id,
                role=role,
                twitch_user_id=twitch_user_id,
                scopes=scopes,
                expires_at=expires_at,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
            )

    async def delete(self, role: str) -> StoredOAuthToken | None:
        async with self._sessions.begin() as session:
            token = await session.scalar(
                select(OAuthToken)
                .where(OAuthToken.role == role)
                .order_by(OAuthToken.created_at.desc())
                .limit(1)
            )
            if token is None:
                return None
            record = StoredOAuthToken(
                channel_id=token.channel_id,
                role=token.role,
                twitch_user_id=token.twitch_user_id,
                scopes=list(token.scopes),
                expires_at=token.expires_at,
                access_token_encrypted=token.access_token_encrypted,
                refresh_token_encrypted=token.refresh_token_encrypted,
            )
            await session.execute(delete(OAuthToken).where(OAuthToken.role == role))
            return record

    async def world_id(self, role: str = "broadcaster") -> UUID | None:
        record = await self.get(role)
        if record is None:
            return None
        async with self._sessions() as session:
            return await session.scalar(
                select(World.id).where(
                    World.channel_id == record.channel_id, World.slug == "mythoslive"
                )
            )
