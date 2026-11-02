from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionState(StrEnum):
    LOBBY = "LOBBY"
    INTRO = "INTRO"
    VOTE = "VOTE"
    COMBAT = "COMBAT"
    PUZZLE = "PUZZLE"
    EVENT = "EVENT"
    BOSS = "BOSS"
    RECAP = "RECAP"
    ENDED = "ENDED"
    PAUSED = "PAUSED"


class HeroState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity_key: str
    display_name: str
    chat_color: str | None = None
    viewer_id: str | None = None
    hero_id: str | None = None
    class_name: str | None = None
    level: int = 1
    xp: int = 0
    gold: int = 0
    title: str = "Wayfarer"
    stats: dict[str, int] = Field(default_factory=dict)
    hp: int = 0
    max_hp: int = 0
    downed: bool = False
    ghost: bool = False
    shield_until: float = 0
    joined: bool = False
    cosmetics: list[str] = Field(default_factory=list)
    damage_dealt: int = 0
    support_done: int = 0
    votes_cast: int = 0


class GameState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    session_id: UUID
    world_id: UUID
    state: SessionState = SessionState.LOBBY
    resume_state: SessionState | None = None
    revision: int = 0
    seed: int = 1
    session_config: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    phase_started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_tick_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_snapshot_at: datetime | None = None
    scene_index: int = -1
    scene_id: str | None = None
    scene: dict[str, Any] = Field(default_factory=dict)
    preferred_scene_id: str | None = None
    preferred_scene_flavor: str | None = None
    preferred_enemy_id: str | None = None
    preferred_boss_id: str | None = None
    preferred_boss_mechanic: str | None = None
    preferred_riddle_id: str | None = None
    votes: dict[str, int] = Field(default_factory=dict)
    heroes: dict[str, HeroState] = Field(default_factory=dict)
    enemy: dict[str, Any] = Field(default_factory=dict)
    boss_index: int = 0
    boss_phase: int = 0
    boss_mechanic_index: int = 0
    cooldowns: dict[str, float] = Field(default_factory=dict)
    combo_hits: list[dict[str, Any]] = Field(default_factory=list)
    global_action_times: list[float] = Field(default_factory=list)
    action_count: int = 0
    key_moments: list[str] = Field(default_factory=list)
    world_flags: list[str] = Field(default_factory=list)
    morale_bonus: int = Field(default=0, ge=0, le=3)
    torches_lit: int = Field(default=0, ge=0, le=12)
    reinforcements: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    opted_out: list[str] = Field(default_factory=list)
    processed_event_ids: list[str] = Field(default_factory=list)
    recap: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def restore(cls, value: dict[str, Any]) -> "GameState":
        return cls.model_validate(value)


def xp_required_for_level(level: int) -> int:
    if level < 1:
        raise ValueError("Level must be positive")
    return round(100 * level**1.5)


def level_for_xp(xp: int) -> int:
    if xp < 0:
        raise ValueError("XP cannot be negative")
    level = 1
    while xp >= xp_required_for_level(level):
        xp -= xp_required_for_level(level)
        level += 1
        if level > 100:
            break
    return level
