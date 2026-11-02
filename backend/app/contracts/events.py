from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActorIdentity(StrictContract):
    kind: Literal["twitch", "simulator", "dashboard"] = "twitch"
    identity_key: str | None = Field(default=None, max_length=96)
    twitch_user_id: str | None = None
    display_name: str | None = Field(default=None, max_length=128)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class GameEvent(StrictContract):
    event_id: UUID
    event_type: str = Field(min_length=1, max_length=96)
    schema_version: Literal[1] = 1
    occurred_at: datetime
    source: Literal["twitch", "simulator", "dashboard"]
    world_id: UUID
    session_id: UUID | None = None
    actor: ActorIdentity | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorldSnapshot(StrictContract):
    schema_version: Literal[1] = 1
    world_id: UUID
    session_id: UUID | None = None
    session_state: str = Field(min_length=1, max_length=16)
    revision: int = Field(ge=0)
    occurred_at: datetime
    state: dict[str, Any] = Field(default_factory=dict)


class RealtimeGameEvent(StrictContract):
    schema_version: Literal[1] = 1
    message_type: Literal["game.event"] = "game.event"
    event: GameEvent


class RealtimeWorldSnapshot(StrictContract):
    schema_version: Literal[1] = 1
    message_type: Literal["world.snapshot"] = "world.snapshot"
    snapshot: WorldSnapshot


class RealtimeConnectionStatus(StrictContract):
    schema_version: Literal[1] = 1
    message_type: Literal["connection.status"] = "connection.status"
    status: Literal["connected", "disconnected", "degraded"]
    detail: str | None = Field(default=None, max_length=256)


EngineEventType = Literal[
    "session_transition",
    "hero_joined",
    "hero_updated",
    "scene_started",
    "vote_tally",
    "vote_result",
    "combat_tick",
    "damage",
    "boss_phase",
    "combo",
    "puzzle_update",
    "narration",
    "toast",
    "recap",
    "paused",
]


class EngineRealtimeEvent(StrictContract):
    schema_version: Literal[1] = 1
    message_type: Literal["engine.event"] = "engine.event"
    event_type: EngineEventType
    event_id: UUID
    session_id: UUID
    world_id: UUID
    occurred_at: datetime
    sequence: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class EngineRealtimeSnapshot(StrictContract):
    schema_version: Literal[1] = 1
    message_type: Literal["engine.snapshot"] = "engine.snapshot"
    session_id: UUID
    world_id: UUID
    revision: int = Field(ge=0)
    sequence: int = Field(ge=0)
    state: dict[str, Any]


type RealtimeMessage = Annotated[
    RealtimeGameEvent
    | RealtimeWorldSnapshot
    | RealtimeConnectionStatus
    | EngineRealtimeEvent
    | EngineRealtimeSnapshot,
    Field(discriminator="message_type"),
]


class TwitchConnectionStatus(StrictContract):
    broadcaster_connected: bool
    bot_connected: bool
    broadcaster_user_id: str | None = None
    bot_user_id: str | None = None
    broadcaster_scopes: list[str] = Field(default_factory=list)
    bot_scopes: list[str] = Field(default_factory=list)
    eventsub_status: Literal["disconnected", "connecting", "connected", "degraded"]
    eventsub_session_id: str | None = None
    subscriptions: dict[str, str] = Field(default_factory=dict)
    last_keepalive_at: datetime | None = None
    last_message_at: datetime | None = None
    last_error: str | None = None
    chat_send_enabled: bool = False
    outbox_pending: int = 0
    outbox_sent: int = 0
    outbox_dropped: int = 0


class SimChatRequest(StrictContract):
    persona_name: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class SimSocialRequest(StrictContract):
    event_type: Literal["channel.follow", "channel.raid"]
    name: str = Field(min_length=1, max_length=64)
    viewers: int = Field(default=0, ge=0, le=10_000)


class SimStatus(StrictContract):
    running: bool
    simulated: Literal[True] = True
    generated_events: int = 0
    last_event_at: datetime | None = None
    events: list[GameEvent] = Field(default_factory=list)


class ChatSendRequest(StrictContract):
    message: str = Field(min_length=1, max_length=500)


class ChatEnableRequest(StrictContract):
    enabled: bool
