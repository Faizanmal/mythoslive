import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import get_settings
from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Channel(TimestampMixin, Base):
    __tablename__ = "channels"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    twitch_broadcaster_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", server_default="active", nullable=False
    )


class OAuthToken(TimestampMixin, Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("channel_id", "role", name="uq_oauth_channel_role"),
        CheckConstraint("role IN ('broadcaster','bot')", name="role"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    twitch_user_id: Mapped[str | None] = mapped_column(String(32))
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String(128)), default=list, server_default="{}", nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class World(TimestampMixin, Base):
    __tablename__ = "worlds"
    __table_args__ = (UniqueConstraint("channel_id", "slug", name="uq_world_channel_slug"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )


class Viewer(TimestampMixin, Base):
    __tablename__ = "viewers"
    __table_args__ = (
        UniqueConstraint("world_id", "identity_key", name="uq_viewer_world_identity"),
        CheckConstraint("identity_kind IN ('twitch','simulator')", name="identity_kind"),
        UniqueConstraint("world_id", "optout_key", name="uq_viewer_world_optout_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    identity_key: Mapped[str] = mapped_column(String(96), nullable=False)
    identity_kind: Mapped[str] = mapped_column(
        String(16), default="twitch", server_default="twitch", nullable=False
    )
    twitch_user_id: Mapped[str | None] = mapped_column(String(32))
    optout_key: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(128))
    opted_out: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    muted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memory_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )


class Hero(TimestampMixin, Base):
    __tablename__ = "heroes"
    __table_args__ = (
        UniqueConstraint("world_id", "viewer_id", name="uq_hero_world_viewer"),
        CheckConstraint(
            "class_name IS NULL OR class_name IN ('warrior','mage','rogue','cleric','bard')",
            name="class_name",
        ),
        CheckConstraint("xp >= 0 AND cosmetic_gold >= 0", name="nonnegative_rewards"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    viewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("viewers.id", ondelete="CASCADE"), nullable=False
    )
    class_name: Mapped[str | None] = mapped_column(String(16))
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    xp: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    cosmetic_gold: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    cosmetics: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, server_default="{}", nullable=False
    )


class GameSession(TimestampMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('LOBBY','INTRO','VOTE','COMBAT','PUZZLE','EVENT','BOSS','RECAP','ENDED',"
            "'PAUSED')",
            name="state",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(16), default="LOBBY", server_default="LOBBY", nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )


class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_scene_session_sequence"),
        CheckConstraint("sequence >= 0", name="sequence_nonnegative"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )


class Vote(TimestampMixin, Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("scene_id", "viewer_id", name="uq_vote_scene_viewer"),
        CheckConstraint("choice BETWEEN 1 AND 4", name="choice_range"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    viewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("viewers.id", ondelete="CASCADE"), nullable=False
    )
    choice: Mapped[int] = mapped_column(Integer, nullable=False)
    cast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GameEvent(Base):
    __tablename__ = "game_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_game_event_id"),
        Index("ix_game_events_session_occurred", "session_id", "occurred_at"),
        Index("ix_game_events_world_occurred", "world_id", "occurred_at"),
        CheckConstraint("source IN ('twitch','simulator','dashboard')", name="source"),
        CheckConstraint("schema_version >= 1", name="schema_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    actor_viewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("viewers.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorldEventPending(Base):
    __tablename__ = "world_events_pending"
    __table_args__ = (
        Index("ix_world_events_pending_world_status", "world_id", "status"),
        CheckConstraint("status IN ('pending','applied','rejected','expired')", name="status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("game_events.event_id", ondelete="SET NULL"), unique=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DashboardConfig(Base):
    __tablename__ = "dashboard_configs"
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), primary_key=True
    )
    director_notes: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DashboardAudit(Base):
    __tablename__ = "dashboard_audit"
    __table_args__ = (
        Index("ix_dashboard_audit_world_created", "world_id", "created_at"),
        CheckConstraint("length(action) BETWEEN 1 AND 64", name="action_length"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    actor_broadcaster_id: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_world_viewer_kind", "world_id", "viewer_id", "kind"),
        Index("ix_memories_world_importance", "world_id", "importance"),
        CheckConstraint(
            "kind IN ('world_fact','session_summary','viewer_moment','inside_joke',"
            "'npc','location','quest')",
            name="kind",
        ),
        CheckConstraint("importance >= 0 AND importance <= 1", name="importance_range"),
        CheckConstraint("use_count >= 0", name="use_count_nonnegative"),
        CheckConstraint("length(content) BETWEEN 1 AND 280", name="content_length"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    viewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("viewers.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(24), default="world_fact", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5", nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(get_settings().embedding_dimension)
    )
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    consented: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_world_created", "world_id", "created_at"),
        CheckConstraint("status IN ('success','error','rejected','fallback')", name="status"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_nonnegative"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_nonnegative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_nonnegative"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("worlds.id", ondelete="SET NULL"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Chronicle(TimestampMixin, Base):
    __tablename__ = "chronicles"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_chronicle_session"),
        Index("ix_chronicles_world_created", "world_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    recap: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class OverlayAccessKey(TimestampMixin, Base):
    __tablename__ = "overlay_access_keys"
    __table_args__ = (Index("ix_overlay_access_world_active", "world_id", "revoked_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
