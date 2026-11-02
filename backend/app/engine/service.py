import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.contracts.events import ActorIdentity, EngineRealtimeEvent, GameEvent
from app.engine.repository import EngineRepository
from app.engine.rules import RulesEngine
from app.engine.state import GameState

logger = logging.getLogger(__name__)


class GameEngineService:
    """Bounded event ingress, one serial consumer, and one controlled world tick loop."""

    def __init__(
        self,
        repository: EngineRepository,
        rules: RulesEngine | None = None,
        *,
        queue_size: int = 10_000,
        event_history_size: int = 5_000,
        tick_interval_seconds: float = 0.5,
    ) -> None:
        self.repository = repository
        self.rules = rules or RulesEngine()
        self.queue: asyncio.Queue[GameEvent] = asyncio.Queue(maxsize=queue_size)
        self.tick_interval_seconds = tick_interval_seconds
        self.states: dict[UUID, GameState] = {}
        self._history: deque[tuple[int, EngineRealtimeEvent]] = deque(maxlen=event_history_size)
        self._sequence = 0
        self._worker: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._listeners: list[Any] = []
        self.dropped_events = 0
        self.processing_failures = 0
        self.tick_failures = 0
        self.connected_clients = 0
        self._last_tick = datetime.now(UTC)

    @property
    def running(self) -> bool:
        return self._worker is not None and not self._worker.done()

    def enqueue(self, event: GameEvent) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.dropped_events += 1
            return False

    def subscribe(self, listener: Any) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    async def set_ai_preferences(self, world_id: UUID, preferences: dict[str, Any]) -> bool:
        async with self._state_lock:
            applied = await self.repository.set_ai_preferences(world_id, preferences, self.rules)
            if applied:
                state = await self.repository.get_state(world_id)
                if state:
                    self.states[world_id] = state
            return applied

    async def grant_ai_reward(self, world_id: UUID, tier: str) -> bool:
        async with self._state_lock:
            state, outputs = await self.repository.grant_ai_reward(
                world_id, tier, self.rules, datetime.now(UTC)
            )
            if not outputs:
                return False
            if state:
                self.states[world_id] = state
            self._publish(outputs)
            return True

    async def publish_ai_presentation(
        self, world_id: UUID, event_type: str, payload: dict[str, Any]
    ) -> bool:
        if event_type not in {"narration", "toast"}:
            return False
        async with self._state_lock:
            state = self.states.get(world_id)
            if state is None:
                return False
            self._sequence += 1
            event = EngineRealtimeEvent(
                event_type=event_type,
                event_id=uuid4(),
                session_id=state.session_id,
                world_id=world_id,
                occurred_at=datetime.now(UTC),
                sequence=self._sequence,
                payload=payload,
            )
            self._history.append((self._sequence, event))
            self._notify(event)
            return True

    def start(self) -> None:
        if not self.running:
            self._worker = asyncio.create_task(self._run(), name="mythos-game-engine")

    async def stop(self) -> None:
        worker, self._worker = self._worker, None
        if worker is None:
            return
        try:
            await asyncio.wait_for(self.queue.join(), timeout=5)
        except TimeoutError:
            pass
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    async def restore(self) -> None:
        for state, outputs in await self.repository.restore_active(self.rules):
            self.states[state.world_id] = state
            self._publish(outputs)

    async def ensure_simulator_world(self, world_id: UUID) -> None:
        await self.repository.ensure_simulator_world(world_id)

    async def start_session(
        self,
        world_id: UUID,
        *,
        seed: int = 1,
        now: datetime | None = None,
        session_config: dict[str, Any] | None = None,
        source: str = "simulator",
    ) -> GameState:
        async with self._state_lock:
            state, outputs = await self.repository.start_session(
                world_id,
                self.rules,
                seed=seed,
                now=now,
                session_config=session_config,
                source=source,
            )
            self.states[world_id] = state
            self._publish(outputs)
            return state

    async def dashboard_control(
        self,
        world_id: UUID,
        action: str,
        broadcaster_id: str,
        *,
        session_config: dict[str, Any] | None = None,
    ) -> GameState:
        if action == "start":
            return await self.start_session(
                world_id, session_config=session_config, source="dashboard"
            )
        if action not in {"pause", "resume", "end"}:
            raise ValueError("Unsupported dashboard session action")
        for _ in range(10 if action == "end" else 1):
            state = await self.get_state(world_id)
            if state is None:
                raise LookupError("No session exists for this world")
            if action == "end" and state.state.value == "ENDED":
                break
            command = (
                "resume"
                if action == "end" and state.state.value == "PAUSED"
                else ("skip" if action == "end" else action)
            )
            event = GameEvent(
                event_id=uuid4(),
                event_type=f"chat.command.{command}",
                occurred_at=datetime.now(UTC),
                source="dashboard",
                world_id=world_id,
                actor=ActorIdentity(
                    kind="dashboard",
                    identity_key=f"dashboard:{broadcaster_id}",
                    display_name="Streamer control room",
                ),
                payload={"command": command, "is_moderator": True},
            )
            await self.process_event(event)
            if action != "end":
                return await self.get_state(world_id) or state
        return await self.get_state(world_id) or state

    async def remove_viewer(self, world_id: UUID, identity_key: str, display_name: str) -> None:
        async with self._state_lock:
            state = await self.get_state(world_id)
            if state is None:
                return
            hero = state.heroes.pop(identity_key, None)
            state.votes.pop(identity_key, None)
            if hero is None:
                return
            state.revision += 1
            await self.repository.persist_snapshot(state)
            self._publish(
                [
                    GameEvent(
                        event_id=uuid4(),
                        event_type="hero_updated",
                        occurred_at=datetime.now(UTC),
                        source="dashboard",
                        world_id=world_id,
                        session_id=state.session_id,
                        payload={"hero_removed": True, "display_name": display_name},
                    )
                ]
            )

    async def process_event(self, event: GameEvent) -> list[GameEvent]:
        async with self._state_lock:
            state, outputs, _applied = await self.repository.process_event(event, self.rules)
            if state is not None:
                self.states[state.world_id] = state
            self._publish(outputs)
            return outputs

    async def tick_once(self, now: datetime | None = None) -> list[GameEvent]:
        async with self._state_lock:
            timestamp = now or datetime.now(UTC)
            outputs: list[GameEvent] = []
            for world_id in await self.repository.active_worlds():
                state, events = await self.repository.tick_world(world_id, self.rules, timestamp)
                if state is not None:
                    self.states[world_id] = state
                outputs.extend(events)
                self._publish(events)
            self._last_tick = timestamp
            return outputs

    async def get_state(self, world_id: UUID) -> GameState | None:
        state = self.states.get(world_id)
        if state is None:
            state = await self.repository.get_state(world_id)
            if state:
                self.states[world_id] = state
        return state

    async def public_snapshot(self, world_id: UUID) -> dict[str, Any] | None:
        snapshot, _sequence = await self.public_snapshot_bundle(world_id)
        return snapshot

    async def public_snapshot_bundle(self, world_id: UUID) -> tuple[dict[str, Any] | None, int]:
        async with self._state_lock:
            return await self._public_snapshot_locked(world_id), self._sequence

    async def _public_snapshot_locked(self, world_id: UUID) -> dict[str, Any] | None:
        state = await self.get_state(world_id)
        if state is None:
            return None
        snapshot = state.snapshot()
        snapshot["heroes"] = [
            {
                "display_name": hero.display_name,
                "chat_color": hero.chat_color,
                "class_name": hero.class_name,
                "level": hero.level,
                "title": hero.title,
                "hp": hero.hp,
                "max_hp": hero.max_hp,
                "downed": hero.downed,
                "ghost": hero.ghost,
                "gold": hero.gold,
                "stats": hero.stats,
                "cosmetics": hero.cosmetics,
            }
            for hero in state.heroes.values()
            if hero.joined
        ]
        snapshot["votes"] = self.rules.vote_tally(state)
        scene = dict(snapshot.get("scene", {}))
        scene.pop("database_scene_id", None)
        if isinstance(scene.get("riddle"), dict):
            riddle = dict(scene["riddle"])
            riddle.pop("answer", None)
            riddle.pop("aliases", None)
            scene["riddle"] = riddle
        snapshot["scene"] = scene
        snapshot["cooldowns"] = {}
        snapshot["combo_hits"] = [
            {"active_participants": len({hit["identity"] for hit in state.combo_hits})}
        ]
        snapshot.pop("processed_event_ids", None)
        snapshot.pop("opted_out", None)
        return snapshot

    def events_since(
        self, sequence: int = 0, world_id: UUID | None = None
    ) -> list[tuple[int, EngineRealtimeEvent]]:
        return [
            (seq, event)
            for seq, event in self._history
            if seq > sequence and (world_id is None or event.world_id == world_id)
        ]

    @property
    def sequence(self) -> int:
        return self._sequence

    async def _run(self) -> None:
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=self.tick_interval_seconds)
            except TimeoutError:
                event = None
            if event is not None:
                try:
                    await self.process_event(event)
                except Exception:
                    self.processing_failures += 1
                    logger.exception("Engine event failed: %s", event.event_id)
                finally:
                    self.queue.task_done()
            now = datetime.now(UTC)
            if (now - self._last_tick).total_seconds() >= self.tick_interval_seconds:
                try:
                    await self.tick_once(now)
                except Exception:
                    self.tick_failures += 1
                    logger.exception("Engine tick failed")
                    self._last_tick = now

    def _publish(self, events: list[GameEvent]) -> None:
        for event in events:
            self._sequence += 1
            self._history.append(
                (
                    self._sequence,
                    EngineRealtimeEvent(
                        event_type=event.event_type,
                        event_id=event.event_id,
                        session_id=event.session_id,
                        world_id=event.world_id,
                        occurred_at=event.occurred_at,
                        sequence=self._sequence,
                        payload=event.payload,
                    ),
                )
            )
            self._notify(self._history[-1][1])

    def _notify(self, event: EngineRealtimeEvent) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                logger.exception("Engine event listener failed: %s", event.event_type)
