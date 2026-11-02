import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Float, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.entities import (
    Channel,
    Chronicle,
    DashboardConfig,
    GameEvent,
    Hero,
    LLMCall,
    Memory,
    Viewer,
    World,
    WorldEventPending,
)

APPROVABLE_WORLD_FLAGS = frozenset(
    {"lantern_festival", "market_open", "village_trusts_party", "ashfall_cleared", "river_crossed"}
)
MEMORY_KINDS = frozenset(
    {"world_fact", "session_summary", "viewer_moment", "inside_joke", "npc", "location", "quest"}
)
MEMORY_MAX_LENGTH = 280


class AIRepository:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def record_call(
        self,
        *,
        world_id: UUID | None,
        session_id: UUID | None,
        model_name: str,
        status: str,
        latency_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        detail: str | None = None,
    ) -> None:
        async with self.sessions.begin() as db:
            db.add(
                LLMCall(
                    world_id=world_id,
                    session_id=session_id,
                    model_name=model_name[:128] or "unconfigured",
                    status=status,
                    latency_ms=max(0, latency_ms),
                    input_tokens=max(0, input_tokens),
                    output_tokens=max(0, output_tokens),
                    metadata_json={
                        **({"detail": detail[:96]} if detail else {}),
                        "cost_usd": round(max(0.0, cost_usd), 8),
                    },
                )
            )

    async def session_tokens(self, session_id: UUID) -> int:
        async with self.sessions() as db:
            value = await db.scalar(
                select(
                    func.coalesce(func.sum(LLMCall.input_tokens + LLMCall.output_tokens), 0)
                ).where(LLMCall.session_id == session_id)
            )
            return int(value or 0)

    async def session_cost(self, session_id: UUID) -> float:
        async with self.sessions() as db:
            value = await db.scalar(
                select(
                    func.coalesce(
                        func.sum(cast(LLMCall.metadata_json["cost_usd"].as_string(), Float)), 0.0
                    )
                ).where(LLMCall.session_id == session_id)
            )
            return float(value or 0.0)

    async def prior_recap(self, world_id: UUID) -> dict[str, Any] | None:
        async with self.sessions() as db:
            row = await db.scalar(
                select(Chronicle)
                .where(Chronicle.world_id == world_id)
                .order_by(Chronicle.created_at.desc())
                .limit(1)
            )
            return dict(row.recap) if row else None

    async def viewer_id_for_identity(
        self, world_id: UUID, identity_key: str
    ) -> tuple[UUID, bool, bool] | None:
        async with self.sessions() as db:
            row = await db.execute(
                select(Viewer.id, Viewer.memory_consent, Hero.id.is_not(None))
                .outerjoin(Hero, Hero.viewer_id == Viewer.id)
                .where(
                    Viewer.world_id == world_id,
                    Viewer.identity_key == identity_key,
                    Viewer.opted_out.is_(False),
                )
            )
            found = row.first()
            return (found[0], found[1], found[2]) if found else None

    async def hero_sheet(self, world_id: UUID, viewer_id: UUID) -> dict[str, Any] | None:
        async with self.sessions() as db:
            row = await db.scalar(
                select(Hero).where(Hero.world_id == world_id, Hero.viewer_id == viewer_id)
            )
            if row is None:
                return None
            return {
                "class_name": row.class_name,
                "level": int(row.stats.get("level", 1)),
                "hp": int(row.stats.get("hp", row.stats.get("max_hp", 0))),
                "max_hp": int(row.stats.get("max_hp", 0)),
                "xp": int(row.xp),
            }

    async def broadcaster_id_for_world(self, world_id: UUID) -> str | None:
        async with self.sessions() as db:
            return await db.scalar(
                select(Channel.twitch_broadcaster_id)
                .join(World, World.channel_id == Channel.id)
                .where(World.id == world_id, Channel.status == "active")
            )

    async def memories(
        self,
        world_id: UUID,
        *,
        viewer_ids: list[UUID],
        query_embedding: list[float] | None,
        limit: int = 6,
        include_world: bool = True,
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        async with self.sessions.begin() as db:
            permitted_viewers = (
                and_(
                    Memory.viewer_id.in_(viewer_ids),
                    Viewer.id == Memory.viewer_id,
                    Viewer.world_id == world_id,
                    Viewer.memory_consent.is_(True),
                    Viewer.opted_out.is_(False),
                )
                if viewer_ids
                else False
            )
            await db.execute(
                update(Memory)
                .where(
                    Memory.world_id == world_id,
                    Memory.archived_at.is_(None),
                    or_(
                        and_(
                            Memory.importance < 0.2,
                            Memory.created_at < now - timedelta(days=30),
                        ),
                        Memory.expires_at <= now,
                    ),
                )
                .values(archived_at=now)
            )
            owner_condition = (
                or_(Memory.viewer_id.is_(None), permitted_viewers)
                if include_world
                else permitted_viewers
            )
            conditions = [
                Memory.world_id == world_id,
                Memory.consented.is_(True),
                Memory.archived_at.is_(None),
                (Memory.expires_at.is_(None) | (Memory.expires_at > now)),
                owner_condition,
            ]
            if query_embedding is not None:
                distance = Memory.embedding.cosine_distance(query_embedding).label("distance")
                rows = await db.execute(
                    select(Memory, distance)
                    .outerjoin(Viewer, Viewer.id == Memory.viewer_id)
                    .where(*conditions)
                    .order_by(distance.asc().nullslast(), Memory.importance.desc())
                    .limit(100)
                )
                candidates = [
                    {
                        **_memory_candidate(memory),
                        "similarity": 1.0 - float(distance) if distance is not None else 0.0,
                    }
                    for memory, distance in rows.all()
                ]
            else:
                rows = await db.scalars(
                    select(Memory)
                    .outerjoin(Viewer, Viewer.id == Memory.viewer_id)
                    .where(*conditions)
                    .order_by(Memory.importance.desc(), Memory.created_at.desc())
                    .limit(100)
                )
                candidates = [_memory_candidate(memory) for memory in rows.all()]
            ranked = rank_memory_candidates(
                candidates, query_embedding=query_embedding, limit=limit
            )
            selected_ids = [candidate["id"] for candidate in ranked]
            if selected_ids:
                await db.execute(
                    update(Memory)
                    .where(Memory.id.in_(selected_ids))
                    .values(last_used_at=now, use_count=Memory.use_count + 1)
                )
            return [{"kind": item["kind"], "content": item["content"]} for item in ranked]

    async def propose_world_event(
        self,
        *,
        world_id: UUID,
        session_id: UUID,
        event_id: str,
        description: str,
        effect: dict[str, str],
        approval_mode: str,
    ) -> tuple[str, UUID | None]:
        async with self.sessions.begin() as db:
            world = await db.scalar(select(World).where(World.id == world_id).with_for_update())
            if world is None:
                return "missing_world", None
            if approval_mode == "auto_safe":
                self._apply_flag(world, effect["flag_id"])
                return "applied", None
            pending = WorldEventPending(
                world_id=world_id,
                payload={
                    "session_id": str(session_id),
                    "event_id": event_id,
                    "description": description[:200],
                    "effect": effect,
                },
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            db.add(pending)
            await db.flush()
            return "pending", pending.id

    async def write_memory(
        self,
        *,
        world_id: UUID,
        content: str,
        kind: str,
        importance: float,
        viewer_id: UUID | None = None,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
        expires_at: datetime | None = None,
    ) -> UUID:
        content = " ".join(content.split())
        if kind not in MEMORY_KINDS or not 1 <= len(content) <= MEMORY_MAX_LENGTH:
            raise ValueError("Memory kind or content length is invalid")
        if not math.isfinite(importance) or not 0 <= importance <= 1:
            raise ValueError("Memory importance must be between 0 and 1")
        if viewer_id is not None and kind != "viewer_moment":
            raise ValueError("Personal memories must use the viewer_moment kind")
        async with self.sessions.begin() as db:
            if viewer_id is not None:
                viewer = await db.scalar(
                    select(Viewer)
                    .where(Viewer.id == viewer_id, Viewer.world_id == world_id)
                    .with_for_update()
                )
                if viewer is None or viewer.opted_out or not viewer.memory_consent:
                    raise PermissionError("Viewer has not consented to personalized memories")
            existing = await db.scalar(
                select(Memory.id)
                .where(
                    Memory.world_id == world_id,
                    Memory.viewer_id == viewer_id,
                    Memory.kind == kind,
                    func.lower(Memory.content) == content.casefold(),
                    Memory.archived_at.is_(None),
                )
                .limit(1)
            )
            if existing:
                return existing
            memory = Memory(
                world_id=world_id,
                viewer_id=viewer_id,
                kind=kind,
                content=content,
                importance=importance,
                embedding=embedding,
                embedding_model=embedding_model,
                consented=True,
                expires_at=expires_at,
            )
            db.add(memory)
            await db.flush()
            cutoff = datetime.now(UTC)
            await db.execute(
                update(Memory)
                .where(
                    Memory.world_id == world_id,
                    Memory.archived_at.is_(None),
                    or_(
                        and_(
                            Memory.importance < 0.2,
                            Memory.created_at < cutoff - timedelta(days=30),
                        ),
                        Memory.expires_at <= cutoff,
                    ),
                )
                .values(archived_at=cutoff)
            )
            return memory.id

    async def write_memories(self, world_id: UUID, memories: list[dict[str, Any]]) -> int:
        prepared = []
        for item in memories[:120]:
            content = " ".join(str(item.get("content", "")).split())
            kind = str(item.get("kind", ""))
            importance = float(item.get("importance", 0.0))
            if kind not in MEMORY_KINDS or not 1 <= len(content) <= MEMORY_MAX_LENGTH:
                continue
            if not math.isfinite(importance) or not 0 <= importance <= 1:
                continue
            viewer_id = item.get("viewer_id")
            if viewer_id is not None and kind != "viewer_moment":
                continue
            prepared.append({**item, "content": content, "kind": kind, "importance": importance})
        if not prepared:
            return 0
        now = datetime.now(UTC)
        async with self.sessions.begin() as db:
            viewer_ids = {item["viewer_id"] for item in prepared if item.get("viewer_id")}
            permitted: set[UUID] = set()
            if viewer_ids:
                rows = await db.scalars(
                    select(Viewer)
                    .where(Viewer.id.in_(viewer_ids), Viewer.world_id == world_id)
                    .with_for_update()
                )
                permitted = {
                    row.id for row in rows.all() if row.memory_consent and not row.opted_out
                }
            keys = {
                (item.get("viewer_id"), item["kind"], item["content"].casefold())
                for item in prepared
                if item.get("viewer_id") is None or item.get("viewer_id") in permitted
            }
            existing_rows = await db.scalars(
                select(Memory)
                .where(
                    Memory.world_id == world_id,
                    Memory.archived_at.is_(None),
                )
                .order_by(Memory.created_at.desc())
                .limit(1_000)
            )
            existing = {
                (row.viewer_id, row.kind, row.content.casefold()) for row in existing_rows.all()
            }
            additions = []
            for item in prepared:
                viewer_id = item.get("viewer_id")
                if viewer_id is not None and viewer_id not in permitted:
                    continue
                key = (viewer_id, item["kind"], item["content"].casefold())
                if key in existing or key not in keys:
                    continue
                existing.add(key)
                additions.append(
                    Memory(
                        world_id=world_id,
                        viewer_id=viewer_id,
                        kind=item["kind"],
                        content=item["content"],
                        importance=item["importance"],
                        embedding=item.get("embedding"),
                        embedding_model=item.get("embedding_model"),
                        consented=True,
                        expires_at=item.get("expires_at"),
                    )
                )
            db.add_all(additions)
            await db.execute(
                update(Memory)
                .where(
                    Memory.world_id == world_id,
                    Memory.archived_at.is_(None),
                    or_(
                        and_(
                            Memory.importance < 0.2,
                            Memory.created_at < now - timedelta(days=30),
                        ),
                        Memory.expires_at <= now,
                    ),
                )
                .values(archived_at=now)
            )
            return len(additions)

    async def session_memory_sources(
        self, world_id: UUID, session_id: UUID
    ) -> tuple[dict[str, Any] | None, list[tuple[UUID, int]]]:
        async with self.sessions() as db:
            chronicle = await db.scalar(
                select(Chronicle).where(
                    Chronicle.world_id == world_id, Chronicle.session_id == session_id
                )
            )
            participants = await db.execute(
                select(Viewer.id, Hero.stats)
                .join(Hero, Hero.viewer_id == Viewer.id)
                .join(GameEvent, GameEvent.actor_viewer_id == Viewer.id)
                .where(
                    Viewer.world_id == world_id,
                    Viewer.memory_consent.is_(True),
                    Viewer.opted_out.is_(False),
                    GameEvent.session_id == session_id,
                    GameEvent.event_type == "chat.command.join",
                )
                .distinct()
            )
            viewers = [(row[0], int((row[1] or {}).get("level", 1))) for row in participants.all()]
            return (dict(chronicle.recap) if chronicle else None), viewers

    async def world_flags(self, world_id: UUID) -> list[str]:
        async with self.sessions() as db:
            world = await db.get(World, world_id)
            flags = (world.state or {}).get("flags", []) if world else []
            return [str(flag)[:64] for flag in flags[:40] if isinstance(flag, str)]

    async def director_notes(self, world_id: UUID) -> str:
        async with self.sessions() as db:
            row = await db.get(DashboardConfig, world_id)
            return row.director_notes[:1_000] if row else ""

    async def pending_events(self, world_id: UUID, limit: int = 50) -> list[WorldEventPending]:
        async with self.sessions() as db:
            rows = await db.scalars(
                select(WorldEventPending)
                .where(
                    WorldEventPending.world_id == world_id, WorldEventPending.status == "pending"
                )
                .order_by(WorldEventPending.created_at.desc())
                .limit(limit)
            )
            return list(rows.all())

    async def review_world_event(self, pending_id: UUID, *, approve: bool) -> bool:
        async with self.sessions.begin() as db:
            pending = await db.scalar(
                select(WorldEventPending)
                .where(WorldEventPending.id == pending_id)
                .with_for_update()
            )
            if pending is None or pending.status != "pending":
                return False
            if approve:
                world = await db.scalar(
                    select(World).where(World.id == pending.world_id).with_for_update()
                )
                flag_id = pending.payload.get("effect", {}).get("flag_id")
                if world is None or flag_id not in APPROVABLE_WORLD_FLAGS:
                    return False
                self._apply_flag(world, flag_id)
                pending.status = "applied"
            else:
                pending.status = "rejected"
            pending.processed_at = datetime.now(UTC)
            return True

    @staticmethod
    def _apply_flag(world: World, flag_id: str) -> None:
        state = dict(world.state or {})
        raw_flags = state.get("flags", [])
        flags = set(raw_flags) if isinstance(raw_flags, list) else set()
        flags.add(flag_id)
        state["flags"] = sorted(flags)
        world.state = state


def _memory_candidate(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "kind": memory.kind,
        "content": memory.content,
        "importance": float(memory.importance),
        "created_at": memory.created_at,
        "embedding": list(memory.embedding) if memory.embedding is not None else None,
        "similarity": 0.0,
    }


def _cosine_similarity(first: list[float] | None, second: list[float] | None) -> float:
    if not first or not second or len(first) != len(second):
        return 0.0
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0 or second_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(first, second, strict=True)) / (first_norm * second_norm)


def _text_similarity(first: str, second: str) -> float:
    first_words = set(re.findall(r"[a-z0-9]{2,}", first.casefold()))
    second_words = set(re.findall(r"[a-z0-9]{2,}", second.casefold()))
    if not first_words or not second_words:
        return 0.0
    return len(first_words & second_words) / len(first_words | second_words)


def rank_memory_candidates(
    candidates: list[dict[str, Any]], *, query_embedding: list[float] | None, limit: int
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    scored = []
    for candidate in candidates:
        created = candidate.get("created_at")
        if created is None:
            recency = 0.5
        else:
            age_days = max(0.0, (now - created).total_seconds() / 86_400)
            recency = math.exp(-age_days / 45.0)
        similarity = float(candidate.get("similarity", 0.0)) if query_embedding is not None else 0.0
        score = 0.5 * similarity + 0.3 * float(candidate.get("importance", 0.5)) + 0.2 * recency
        scored.append((score, candidate))
    scored.sort(key=lambda item: (item[0], item[1].get("created_at") or now), reverse=True)

    selected: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = {}
    for _score, candidate in scored:
        kind = str(candidate.get("kind", "world_fact"))
        if kind_counts.get(kind, 0) >= 2:
            continue
        vector = candidate.get("embedding")
        duplicate = any(
            _cosine_similarity(vector, prior.get("embedding")) >= 0.92
            if vector is not None and prior.get("embedding") is not None
            else _text_similarity(str(candidate.get("content", "")), str(prior.get("content", "")))
            >= 0.8
            for prior in selected
        )
        if duplicate:
            continue
        selected.append(candidate)
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if len(selected) >= max(0, limit):
            break
    return selected
