"""Persistence boundary for broadcaster dashboard configuration and audit actions."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.repository import APPROVABLE_WORLD_FLAGS
from app.models.entities import (
    DashboardAudit,
    DashboardConfig,
    Hero,
    Memory,
    Viewer,
    Vote,
    World,
    WorldEventPending,
)

DEFAULT_DASHBOARD_SETTINGS: dict[str, Any] = {
    "tone": "heroic",
    "family_friendly": True,
    "banned_topics": [],
    "approval_mode": "required",
    "difficulty": "normal",
    "duration_minutes": 30,
    "vote_window_seconds": 20,
    "command_cooldown_seconds": 0.5,
    "bot_messages_per_30_seconds": 20,
}
PROPOSAL_TTL = timedelta(minutes=5)


class DashboardRepository:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def config(self, world_id: UUID) -> dict[str, Any]:
        async with self.sessions() as db:
            row = await db.get(DashboardConfig, world_id)
            return {
                "director_notes": row.director_notes if row else "",
                "settings": {**DEFAULT_DASHBOARD_SETTINGS, **(row.settings if row else {})},
            }

    async def all_configs(self) -> list[tuple[UUID, dict[str, Any], str]]:
        async with self.sessions() as db:
            rows = await db.execute(
                select(
                    DashboardConfig.world_id,
                    DashboardConfig.settings,
                    DashboardConfig.director_notes,
                )
            )
            return [
                (
                    row.world_id,
                    {**DEFAULT_DASHBOARD_SETTINGS, **(row.settings or {})},
                    row.director_notes,
                )
                for row in rows.all()
            ]

    async def muted_twitch_ids(self, world_id: UUID | None = None) -> set[str]:
        async with self.sessions() as db:
            statement = select(Viewer.twitch_user_id).where(
                Viewer.identity_kind == "twitch",
                Viewer.muted.is_(True),
                Viewer.twitch_user_id.is_not(None),
            )
            if world_id:
                statement = statement.where(Viewer.world_id == world_id)
            rows = await db.scalars(statement)
            return {value for value in rows.all() if value}

    async def save_config(
        self,
        world_id: UUID,
        broadcaster_id: str,
        *,
        director_notes: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self.sessions.begin() as db:
            row = await db.get(DashboardConfig, world_id, with_for_update=True)
            if row is None:
                row = DashboardConfig(world_id=world_id)
                db.add(row)
            if director_notes is not None:
                row.director_notes = director_notes[:1_000]
            if settings is not None:
                row.settings = {**(row.settings or {}), **settings}
            db.add(
                DashboardAudit(
                    world_id=world_id,
                    actor_broadcaster_id=broadcaster_id,
                    action="config.updated",
                    details={
                        "keys": sorted((settings or {}).keys())
                        + (["director_notes"] if director_notes is not None else [])
                    },
                )
            )
            await db.flush()
            return {
                "director_notes": row.director_notes,
                "settings": {**DEFAULT_DASHBOARD_SETTINGS, **row.settings},
            }

    async def audit(
        self, world_id: UUID, broadcaster_id: str, action: str, details: dict[str, Any]
    ) -> None:
        async with self.sessions.begin() as db:
            db.add(
                DashboardAudit(
                    world_id=world_id,
                    actor_broadcaster_id=broadcaster_id,
                    action=action[:64],
                    details=details,
                )
            )

    async def list_proposals(self, world_id: UUID, limit: int = 50) -> list[WorldEventPending]:
        now = datetime.now(UTC)
        async with self.sessions.begin() as db:
            await db.execute(
                update(WorldEventPending)
                .where(
                    WorldEventPending.world_id == world_id,
                    WorldEventPending.status == "pending",
                    WorldEventPending.expires_at.is_not(None),
                    WorldEventPending.expires_at <= now,
                )
                .values(status="expired", processed_at=now)
            )
            rows = await db.scalars(
                select(WorldEventPending)
                .where(WorldEventPending.world_id == world_id)
                .order_by(WorldEventPending.created_at.desc())
                .limit(limit)
            )
            return list(rows.all())

    async def edit_proposal(
        self,
        world_id: UUID,
        pending_id: UUID,
        broadcaster_id: str,
        *,
        description: str,
        flag_id: str,
    ) -> bool:
        if flag_id not in APPROVABLE_WORLD_FLAGS or not 1 <= len(description.strip()) <= 200:
            return False
        async with self.sessions.begin() as db:
            row = await db.scalar(
                select(WorldEventPending)
                .where(
                    WorldEventPending.id == pending_id,
                    WorldEventPending.world_id == world_id,
                    WorldEventPending.status == "pending",
                )
                .with_for_update()
            )
            if row is None or (row.expires_at and row.expires_at <= datetime.now(UTC)):
                return False
            row.payload = {
                **row.payload,
                "description": description.strip(),
                "effect": {"flag_id": flag_id},
            }
            db.add(
                DashboardAudit(
                    world_id=world_id,
                    actor_broadcaster_id=broadcaster_id,
                    action="proposal.edited",
                    details={"pending_id": str(pending_id), "flag_id": flag_id},
                )
            )
            return True

    async def decide_proposal(
        self,
        world_id: UUID,
        pending_id: UUID,
        broadcaster_id: str,
        *,
        approve: bool,
    ) -> tuple[str, str] | None:
        now = datetime.now(UTC)
        async with self.sessions.begin() as db:
            row = await db.scalar(
                select(WorldEventPending)
                .where(
                    WorldEventPending.id == pending_id,
                    WorldEventPending.world_id == world_id,
                )
                .with_for_update()
            )
            if row is None or row.status != "pending":
                return None
            if row.expires_at and row.expires_at <= now:
                row.status = "expired"
                row.processed_at = now
                return "expired"
            flag_id = row.payload.get("effect", {}).get("flag_id")
            if approve:
                if flag_id not in APPROVABLE_WORLD_FLAGS:
                    return None
                world = await db.scalar(select(World).where(World.id == world_id).with_for_update())
                if world is None:
                    return None
                state = dict(world.state or {})
                flags = set(state.get("flags", []))
                flags.add(flag_id)
                state["flags"] = sorted(flags)
                world.state = state
                row.status = "applied"
            else:
                row.status = "rejected"
            row.processed_at = now
            db.add(
                DashboardAudit(
                    world_id=world_id,
                    actor_broadcaster_id=broadcaster_id,
                    action="proposal.approved" if approve else "proposal.vetoed",
                    details={"pending_id": str(pending_id), "flag_id": flag_id},
                )
            )
            return row.status

    async def audit_log(self, world_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        async with self.sessions() as db:
            rows = await db.scalars(
                select(DashboardAudit)
                .where(DashboardAudit.world_id == world_id)
                .order_by(DashboardAudit.created_at.desc())
                .limit(limit)
            )
            return [
                {
                    "id": str(row.id),
                    "action": row.action,
                    "details": row.details,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows.all()
            ]

    async def world_codex(self, world_id: UUID) -> dict[str, Any]:
        async with self.sessions() as db:
            world = await db.get(World, world_id)
            heroes = await db.execute(
                select(Hero, Viewer)
                .join(Viewer, Viewer.id == Hero.viewer_id)
                .where(Hero.world_id == world_id, Viewer.opted_out.is_(False))
                .order_by(Hero.updated_at.desc())
                .limit(100)
            )
            memories = await db.scalars(
                select(Memory)
                .where(
                    Memory.world_id == world_id,
                    Memory.archived_at.is_(None),
                    Memory.consented.is_(True),
                )
                .order_by(Memory.importance.desc(), Memory.created_at.desc())
                .limit(100)
            )
            flags = (world.state or {}).get("flags", []) if world else []
            return {
                "canon": (
                    "Emberfall is a valley of lantern towns, glass orchards, warm caverns, "
                    "and old starlit roads."
                ),
                "locations": ["Lantern Town", "Glass Orchard", "Warm Caverns", "Silver River"],
                "npcs": ["Mira the mapmaker", "Tovin the orchard keeper", "Quill the Chronicler"],
                "world_flags": flags,
                "heroes": [
                    {
                        "viewer_id": str(viewer.id),
                        "identity_kind": viewer.identity_kind,
                        "display_name": viewer.display_name or "Wayfarer",
                        "class_name": hero.class_name,
                        "level": (hero.stats or {}).get("level", 1),
                        "memory_consent": viewer.memory_consent,
                        "muted": viewer.muted,
                    }
                    for hero, viewer in heroes.all()
                ],
                "memories": [
                    {
                        "id": str(row.id),
                        "kind": row.kind,
                        "content": row.content,
                        "importance": row.importance,
                        "personal": row.viewer_id is not None,
                    }
                    for row in memories.all()
                ],
            }

    async def delete_memory(self, world_id: UUID, memory_id: UUID, broadcaster_id: str) -> bool:
        async with self.sessions.begin() as db:
            row = await db.scalar(
                select(Memory).where(Memory.id == memory_id, Memory.world_id == world_id)
            )
            if row is None:
                return False
            await db.delete(row)
            db.add(
                DashboardAudit(
                    world_id=world_id,
                    actor_broadcaster_id=broadcaster_id,
                    action="memory.deleted",
                    details={"memory_id": str(memory_id)},
                )
            )
            return True

    async def set_viewer_mute(
        self,
        world_id: UUID,
        viewer_id: UUID,
        broadcaster_id: str,
        *,
        muted: bool,
        kick: bool = False,
    ) -> tuple[str, str] | None:
        async with self.sessions.begin() as db:
            viewer = await db.scalar(
                select(Viewer)
                .where(
                    Viewer.id == viewer_id,
                    Viewer.world_id == world_id,
                    Viewer.identity_kind == "twitch",
                    Viewer.opted_out.is_(False),
                )
                .with_for_update()
            )
            if viewer is None or not viewer.twitch_user_id:
                return None
            viewer.muted = muted
            if kick:
                await db.execute(
                    delete(Hero).where(Hero.world_id == world_id, Hero.viewer_id == viewer_id)
                )
                await db.execute(delete(Vote).where(Vote.viewer_id == viewer_id))
            db.add(
                DashboardAudit(
                    world_id=world_id,
                    actor_broadcaster_id=broadcaster_id,
                    action="viewer.kicked"
                    if kick
                    else ("viewer.muted" if muted else "viewer.unmuted"),
                    details={"viewer_id": str(viewer_id)},
                )
            )
            return viewer.twitch_user_id, viewer.identity_key
