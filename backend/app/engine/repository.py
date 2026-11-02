from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.contracts.events import GameEvent as InputEvent
from app.engine.rules import RulesEngine
from app.engine.state import GameState, SessionState
from app.models.entities import (
    Channel,
    Chronicle,
    GameSession,
    Hero,
    Memory,
    Scene,
    Viewer,
    Vote,
    World,
)
from app.models.entities import (
    GameEvent as GameEventRow,
)

ApplyFunction = Callable[[GameState, InputEvent], list[InputEvent]]


class EngineRepository:
    """PostgreSQL transaction boundary for engine events and durable state."""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def ensure_simulator_world(self, world_id: UUID) -> None:
        async with self.sessions.begin() as db:
            world = await db.get(World, world_id)
            if world:
                return
            channel = await db.scalar(
                select(Channel).where(Channel.twitch_broadcaster_id == "local-simulator")
            )
            if channel is None:
                channel = Channel(
                    twitch_broadcaster_id="local-simulator", display_name="Emberfall Simulator"
                )
                db.add(channel)
                await db.flush()
            db.add(
                World(
                    id=world_id,
                    channel_id=channel.id,
                    slug="emberfall-simulator",
                    name="Emberfall Simulator",
                )
            )

    async def start_session(
        self,
        world_id: UUID,
        engine: RulesEngine,
        *,
        seed: int = 1,
        now: datetime | None = None,
        session_config: dict[str, Any] | None = None,
        source: str = "simulator",
    ) -> tuple[GameState, list[InputEvent]]:
        timestamp = now or datetime.now(UTC)
        async with self.sessions.begin() as db:
            await self._lock_world(db, world_id)
            row = await self._active_session(db, world_id)
            if row is not None:
                state = self._restore_row(row, engine, timestamp)
                outputs = engine.resume_for_simulator(state, timestamp)
                if outputs:
                    await self._store_outputs(db, row, state, outputs)
                    self._save_state(row, state)
                return state, outputs
            row = GameSession(world_id=world_id, state="LOBBY", started_at=timestamp, snapshot={})
            db.add(row)
            await db.flush()
            state = engine.new_session(world_id, row.id, seed=seed, now=timestamp)
            state.session_config = dict(session_config or {})
            world = await db.get(World, world_id)
            state.world_flags = list((world.state if world else {}).get("flags", []))
            outputs = engine.start_events(state, source=source)
            await self._store_outputs(db, row, state, outputs)
            self._save_state(row, state)
            return state, outputs

    async def restore_active(self, engine: RulesEngine) -> list[tuple[GameState, list[InputEvent]]]:
        timestamp = datetime.now(UTC)
        restored: list[tuple[GameState, list[InputEvent]]] = []
        async with self.sessions.begin() as db:
            rows = list(
                (
                    await db.scalars(
                        select(GameSession)
                        .where(GameSession.state != SessionState.ENDED.value)
                        .order_by(GameSession.created_at)
                        .with_for_update()
                    )
                ).all()
            )
            for row in rows:
                state = self._restore_row(row, engine, timestamp)
                outputs = engine.recover(state, timestamp)
                if outputs:
                    await self._store_outputs(db, row, state, outputs)
                    self._save_state(row, state)
                restored.append((state, outputs))
        return restored

    async def process_event(
        self,
        event: InputEvent,
        engine: RulesEngine,
        *,
        now: datetime | None = None,
    ) -> tuple[GameState | None, list[InputEvent], bool]:
        timestamp = now or datetime.now(UTC)
        async with self.sessions.begin() as db:
            await self._lock_world(db, event.world_id)
            duplicate = await db.scalar(
                select(GameEventRow.id).where(GameEventRow.event_id == event.event_id)
            )
            if duplicate:
                row = await self._active_session(db, event.world_id)
                if row is None:
                    row = await db.scalar(
                        select(GameSession)
                        .where(GameSession.world_id == event.world_id)
                        .order_by(GameSession.created_at.desc())
                        .limit(1)
                    )
                return (self._restore_row(row, engine, timestamp) if row else None), [], False
            row = await self._active_session(db, event.world_id)
            if row is None:
                row = GameSession(
                    world_id=event.world_id, state="LOBBY", started_at=timestamp, snapshot={}
                )
                db.add(row)
                await db.flush()
                state = engine.new_session(event.world_id, row.id, seed=1, now=timestamp)
                world = await db.get(World, event.world_id)
                state.world_flags = list((world.state if world else {}).get("flags", []))
                start_outputs = engine.start_events(state)
                await self._store_outputs(db, row, state, start_outputs)
            else:
                state = self._restore_row(row, engine, timestamp)
            viewer = await self._prepare_viewer(db, state, event, engine)
            payload = dict(event.payload)
            if payload.get("command") == "memory" and viewer and not viewer.opted_out:
                enabled = payload.get("arguments") == "on"
                viewer.memory_consent = enabled
                payload["memory_consent_enabled"] = enabled
            elif payload.get("command") == "memory":
                payload["memory_consent_enabled"] = None
            if viewer is not None:
                payload["engine_viewer_id"] = str(viewer.id)
                if viewer.opted_out:
                    digest = sha256(
                        (event.actor.identity_key if event.actor else "").encode()
                    ).hexdigest()
                    state.opted_out = sorted(set(state.opted_out) | {digest})
            enriched = event.model_copy(update={"session_id": row.id, "payload": payload})
            output = engine.apply_once(state, enriched)
            await self._store_input(db, enriched, row.id, viewer.id if viewer else None)
            await self._sync_heroes(db, state)
            await self._sync_vote(db, row, state, enriched, viewer)
            await self._store_outputs(db, row, state, output, viewer.id if viewer else None)
            if event.payload.get("command") == "optout" and viewer:
                await self._apply_optout(
                    db, viewer, event.actor.identity_key if event.actor else ""
                )
            self._save_state(row, state)
            row.state = state.state.value
            if state.state == SessionState.ENDED:
                row.ended_at = timestamp
            await self._save_world_flags(db, state)
            return state, output, True

    async def tick_world(
        self,
        world_id: UUID,
        engine: RulesEngine,
        now: datetime,
        *,
        snapshot_interval_seconds: int = 30,
    ) -> tuple[GameState | None, list[InputEvent]]:
        async with self.sessions.begin() as db:
            await self._lock_world(db, world_id)
            row = await self._active_session(db, world_id)
            if row is None:
                return None, []
            state = self._restore_row(row, engine, now)
            output = engine.tick(state, now)
            last_snapshot = (
                float(state.last_snapshot_at.timestamp()) if state.last_snapshot_at else 0
            )
            snapshot_due = now.timestamp() - last_snapshot >= snapshot_interval_seconds
            if output or snapshot_due:
                state.last_snapshot_at = now
                await self._sync_heroes(db, state)
                await self._store_outputs(db, row, state, output)
                self._save_state(row, state)
                row.state = state.state.value
                if state.state == SessionState.ENDED:
                    row.ended_at = now
                await self._save_world_flags(db, state)
            return state, output

    async def set_ai_preferences(
        self, world_id: UUID, preferences: dict[str, Any], engine: RulesEngine
    ) -> bool:
        async with self.sessions.begin() as db:
            await self._lock_world(db, world_id)
            row = await self._active_session(db, world_id)
            if row is None:
                return False
            state = self._restore_row(row, engine, datetime.now(UTC))
            if not engine.set_ai_preferences(state, preferences):
                return False
            self._save_state(row, state)
            return True

    async def grant_ai_reward(
        self, world_id: UUID, tier: str, engine: RulesEngine, now: datetime
    ) -> tuple[GameState | None, list[InputEvent]]:
        async with self.sessions.begin() as db:
            await self._lock_world(db, world_id)
            row = await self._active_session(db, world_id)
            if row is None:
                return None, []
            state = self._restore_row(row, engine, now)
            outputs = engine.grant_ai_reward(state, tier, now)
            if outputs:
                await self._sync_heroes(db, state)
                await self._store_outputs(db, row, state, outputs)
                self._save_state(row, state)
            return state, outputs

    async def get_state(self, world_id: UUID) -> GameState | None:
        async with self.sessions() as db:
            row = await self._active_session(db, world_id)
            if row is None:
                row = await db.scalar(
                    select(GameSession)
                    .where(GameSession.world_id == world_id)
                    .order_by(GameSession.created_at.desc())
                    .limit(1)
                )
            if row is None:
                return None
            return (
                GameState.restore(row.snapshot)
                if row.snapshot
                else GameState(
                    session_id=row.id,
                    world_id=row.world_id,
                    started_at=row.started_at or datetime.now(UTC),
                    phase_started_at=row.started_at or datetime.now(UTC),
                )
            )

    async def persist_snapshot(self, state: GameState) -> None:
        """Persist an authorized control-plane state edit to the active session."""
        async with self.sessions.begin() as db:
            await self._lock_world(db, state.world_id)
            row = await self._active_session(db, state.world_id)
            if row is None or row.id != state.session_id:
                return
            self._save_state(row, state)

    async def chronicles(self, world_id: UUID, limit: int = 50) -> list[Chronicle]:
        async with self.sessions() as db:
            return list(
                (
                    await db.scalars(
                        select(Chronicle)
                        .where(Chronicle.world_id == world_id)
                        .order_by(Chronicle.created_at.desc())
                        .limit(limit)
                    )
                ).all()
            )

    async def get_chronicle(self, chronicle_id: UUID) -> Chronicle | None:
        async with self.sessions() as db:
            return await db.get(Chronicle, chronicle_id)

    async def active_worlds(self) -> list[UUID]:
        async with self.sessions() as db:
            rows = await db.scalars(
                select(GameSession.world_id).where(GameSession.state != "ENDED").distinct()
            )
            return list(rows.all())

    @staticmethod
    async def _lock_world(db, world_id: UUID) -> None:
        world = await db.scalar(select(World).where(World.id == world_id).with_for_update())
        if world is None:
            raise ValueError(f"Unknown game world {world_id}")

    @staticmethod
    async def _active_session(db, world_id: UUID) -> GameSession | None:
        return await db.scalar(
            select(GameSession)
            .where(
                GameSession.world_id == world_id,
                GameSession.state != SessionState.ENDED.value,
            )
            .order_by(GameSession.created_at.desc())
            .limit(1)
            .with_for_update()
        )

    @staticmethod
    def _restore_row(row: GameSession, engine: RulesEngine, now: datetime) -> GameState:
        if row.snapshot:
            return GameState.restore(row.snapshot)
        return engine.new_session(row.world_id, row.id, now=row.started_at or now)

    @staticmethod
    def _save_state(row: GameSession, state: GameState) -> None:
        row.snapshot = state.snapshot()
        row.state = state.state.value

    async def _prepare_viewer(
        self, db, state: GameState, event: InputEvent, engine: RulesEngine
    ) -> Viewer | None:
        if event.source == "dashboard":
            return None
        actor = event.actor
        if actor is None or actor.identity_key is None:
            return None
        identity = actor.identity_key
        command = event.payload.get("command")
        viewer = await db.scalar(
            select(Viewer)
            .where(Viewer.world_id == state.world_id, Viewer.identity_key == identity)
            .with_for_update()
        )
        if viewer is None:
            digest = sha256(identity.encode()).hexdigest()
            viewer = await db.scalar(
                select(Viewer)
                .where(Viewer.world_id == state.world_id, Viewer.optout_key == digest)
                .with_for_update()
            )
        if viewer is None and command != "join" and identity not in state.heroes:
            return None
        if viewer is None:
            viewer = Viewer(
                world_id=state.world_id,
                identity_key=identity,
                identity_kind=actor.kind,
                twitch_user_id=actor.twitch_user_id,
                display_name=actor.display_name[:128] if actor.display_name else None,
            )
            db.add(viewer)
            await db.flush()
        if viewer.opted_out:
            state.opted_out = sorted(set(state.opted_out) | {sha256(identity.encode()).hexdigest()})
            return viewer
        if identity not in state.heroes:
            hero_row = await db.scalar(
                select(Hero).where(Hero.world_id == state.world_id, Hero.viewer_id == viewer.id)
            )
            if hero_row is not None:
                engine.hydrate_hero(
                    state,
                    identity_key=identity,
                    display_name=viewer.display_name or actor.display_name or "Wayfarer",
                    viewer_id=viewer.id,
                    hero_id=hero_row.id,
                    class_name=hero_row.class_name,
                    xp=int(hero_row.xp),
                    gold=int(hero_row.cosmetic_gold),
                    cosmetics=list(hero_row.cosmetics),
                    stats=dict(hero_row.stats),
                )
        return viewer

    async def _store_input(
        self, db, event: InputEvent, session_id: UUID, viewer_id: UUID | None
    ) -> None:
        payload = dict(event.payload)
        command = payload.get("command")
        payload.pop("message", None)
        payload.pop("engine_viewer_id", None)
        if command in {"answer", "lore", "quill"}:
            payload.pop("arguments", None)
        await self._store_game_event(db, event, session_id, viewer_id, payload)

    async def _store_outputs(
        self,
        db,
        row: GameSession,
        state: GameState,
        outputs: list[InputEvent],
        actor_viewer_id: UUID | None = None,
    ) -> None:
        for event in outputs:
            await self._store_game_event(db, event, row.id, actor_viewer_id, event.payload)
            if event.event_type == "scene_started":
                scene = await db.scalar(
                    select(Scene).where(
                        Scene.session_id == row.id, Scene.sequence == state.scene_index
                    )
                )
                if scene is None:
                    scene = Scene(
                        session_id=row.id,
                        sequence=state.scene_index,
                        kind="VOTE",
                        content=state.scene.get("text", ""),
                        state=event.payload,
                    )
                    db.add(scene)
                    await db.flush()
                state.scene["database_scene_id"] = str(scene.id)
            elif event.event_type == "recap" and state.recap:
                chronicle = await db.scalar(select(Chronicle).where(Chronicle.session_id == row.id))
                if chronicle is None:
                    db.add(
                        Chronicle(
                            world_id=state.world_id,
                            session_id=row.id,
                            title=state.recap["title"],
                            recap=state.recap,
                        )
                    )

    async def _store_game_event(
        self,
        db,
        event: InputEvent,
        session_id: UUID,
        viewer_id: UUID | None,
        payload: dict[str, Any],
    ) -> None:
        db.add(
            GameEventRow(
                event_id=event.event_id,
                world_id=event.world_id,
                session_id=session_id,
                actor_viewer_id=viewer_id,
                event_type=event.event_type,
                source=event.source,
                schema_version=event.schema_version,
                payload=payload,
                occurred_at=event.occurred_at,
            )
        )

    async def _sync_heroes(self, db, state: GameState) -> None:
        for hero_state in state.heroes.values():
            if not hero_state.viewer_id:
                continue
            viewer = await db.get(Viewer, UUID(hero_state.viewer_id))
            if viewer is None or viewer.opted_out:
                continue
            hero_row = await db.scalar(
                select(Hero)
                .where(Hero.world_id == state.world_id, Hero.viewer_id == viewer.id)
                .with_for_update()
            )
            stats = dict(hero_state.stats)
            stats.update(
                {
                    "hp": hero_state.hp,
                    "max_hp": hero_state.max_hp,
                    "downed": hero_state.downed,
                    "ghost": hero_state.ghost,
                    "level": hero_state.level,
                    "shield_until": hero_state.shield_until,
                    "damage_dealt": hero_state.damage_dealt,
                    "support_done": hero_state.support_done,
                    "votes_cast": hero_state.votes_cast,
                }
            )
            if hero_row is None:
                hero_row = Hero(world_id=state.world_id, viewer_id=viewer.id)
                db.add(hero_row)
            hero_row.class_name = hero_state.class_name
            hero_row.stats = stats
            hero_row.xp = hero_state.xp
            hero_row.cosmetic_gold = hero_state.gold
            hero_row.cosmetics = list(hero_state.cosmetics)
            await db.flush()
            hero_state.hero_id = str(hero_row.id)

    async def _sync_vote(
        self, db, row: GameSession, state: GameState, event: InputEvent, viewer: Viewer | None
    ) -> None:
        if (
            event.payload.get("command") != "vote"
            or viewer is None
            or state.state != SessionState.VOTE
        ):
            return
        scene_id = state.scene.get("database_scene_id")
        if not scene_id:
            return
        vote = await db.scalar(
            select(Vote)
            .where(Vote.scene_id == UUID(scene_id), Vote.viewer_id == viewer.id)
            .with_for_update()
        )
        choice = state.votes.get(event.actor.identity_key if event.actor else "")
        if choice is None:
            return
        if vote is None:
            db.add(Vote(scene_id=UUID(scene_id), viewer_id=viewer.id, choice=choice))
        else:
            vote.choice = choice
            vote.cast_at = event.occurred_at

    async def _apply_optout(self, db, viewer: Viewer, identity: str) -> None:
        digest = sha256(identity.encode()).hexdigest()
        display_name = viewer.display_name
        await db.execute(delete(Hero).where(Hero.viewer_id == viewer.id))
        await db.execute(delete(Memory).where(Memory.viewer_id == viewer.id))
        await db.execute(delete(Vote).where(Vote.viewer_id == viewer.id))
        await db.execute(
            update(GameEventRow)
            .where(GameEventRow.actor_viewer_id == viewer.id)
            .values(actor_viewer_id=None)
        )
        if display_name:
            sessions = await db.scalars(
                select(GameSession).where(GameSession.world_id == viewer.world_id).with_for_update()
            )
            for session in sessions.all():
                snapshot = dict(session.snapshot or {})
                heroes = dict(snapshot.get("heroes", {}))
                heroes.pop(identity, None)
                snapshot["heroes"] = heroes
                votes = dict(snapshot.get("votes", {}))
                votes.pop(identity, None)
                snapshot["votes"] = votes
                cooldowns = dict(snapshot.get("cooldowns", {}))
                for key in [key for key in cooldowns if key.startswith(f"{identity}:")]:
                    cooldowns.pop(key, None)
                snapshot["cooldowns"] = cooldowns
                snapshot["combo_hits"] = [
                    hit for hit in snapshot.get("combo_hits", []) if hit.get("identity") != identity
                ]
                snapshot = _redact_json_value(snapshot, display_name)
                session.snapshot = snapshot
            chronicles = await db.scalars(
                select(Chronicle).where(Chronicle.world_id == viewer.world_id).with_for_update()
            )
            for chronicle in chronicles.all():
                chronicle.title = _redact_string(chronicle.title, display_name)
                chronicle.recap = _redact_json_value(chronicle.recap, display_name)
            events = await db.scalars(
                select(GameEventRow)
                .where(GameEventRow.world_id == viewer.world_id)
                .with_for_update()
            )
            for event_row in events.all():
                event_row.payload = _redact_json_value(event_row.payload, display_name)
            scenes = await db.scalars(
                select(Scene)
                .join(GameSession, Scene.session_id == GameSession.id)
                .where(GameSession.world_id == viewer.world_id)
                .with_for_update()
            )
            for scene in scenes.all():
                scene.content = _redact_string(scene.content, display_name)
                scene.state = _redact_json_value(scene.state, display_name)
            memories = await db.scalars(
                select(Memory).where(
                    Memory.world_id == viewer.world_id,
                    Memory.viewer_id.is_(None),
                )
            )
            for memory in memories.all():
                if display_name.casefold() in memory.content.casefold():
                    await db.delete(memory)
        viewer.opted_out = True
        viewer.memory_consent = False
        viewer.opted_out_at = datetime.now(UTC)
        viewer.display_name = None
        viewer.twitch_user_id = None
        viewer.identity_key = f"opted-out:{digest}"
        viewer.optout_key = digest

    async def _save_world_flags(self, db, state: GameState) -> None:
        world = await db.get(World, state.world_id)
        if world is not None and state.world_flags:
            world.state = {**world.state, "flags": state.world_flags}


def _redact_string(value: str, display_name: str) -> str:
    import re

    return re.sub(re.escape(display_name), "A wayfarer", value, flags=re.IGNORECASE)


def _redact_json_value(value: Any, display_name: str) -> Any:
    if isinstance(value, str):
        return _redact_string(value, display_name)
    if isinstance(value, list):
        return [_redact_json_value(item, display_name) for item in value]
    if isinstance(value, dict):
        return {key: _redact_json_value(item, display_name) for key, item in value.items()}
    return value
