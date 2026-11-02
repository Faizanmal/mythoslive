import asyncio
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.contracts.events import ActorIdentity, GameEvent
from app.core.settings import Settings
from app.engine.service import GameEngineService
from app.services.ingress import EventRecorder, IngressPipeline


class SimulatorService:
    """Produces only simulator-sourced events; it has no Helix/outbox dependency."""

    PERSONAS = tuple((f"Emberfall Viewer {index:02d}", "!join") for index in range(1, 16))

    def __init__(
        self,
        settings: Settings,
        ingress: IngressPipeline,
        recorder: EventRecorder,
        engine: GameEngineService | None = None,
    ) -> None:
        self.settings = settings
        self.ingress = ingress
        self.recorder = recorder
        self.engine = engine
        self._task: asyncio.Task[None] | None = None
        self.generated_events = 0
        self.last_event_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, object]:
        events = [event for _, event in self.recorder.since() if event.source == "simulator"]
        return {
            "running": self.running,
            "generated_events": self.generated_events,
            "last_event_at": self.last_event_at,
            "events": events[-30:],
        }

    async def start(self) -> None:
        if self.engine is not None:
            await self.engine.start_session(UUID(self.settings.sim_world_id), seed=1)
        if not self.running:
            self._task = asyncio.create_task(self._run(), name="mythos-simulator")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def submit(self, persona_name: str, message: str) -> None:
        event = self.ingress.handle_chat(
            message=message,
            source="simulator",
            world_id=UUID(self.settings.sim_world_id),
            user_id=(
                f"persona-{re.sub(r'[^a-z0-9]+', '-', persona_name.casefold()).strip('-')[:40]}"
            ),
            display_name=persona_name,
        )
        if event is not None:
            self.generated_events += 1
            self.last_event_at = event.occurred_at

    def submit_social(self, event_type: str, name: str, viewers: int = 0) -> None:
        now = datetime.now(UTC)
        event = GameEvent(
            event_id=uuid4(), event_type=event_type, occurred_at=now, source="simulator",
            world_id=UUID(self.settings.sim_world_id),
            actor=ActorIdentity(kind="simulator", identity_key=f"simulator:social:{uuid4()}",
                                display_name=f"[SIM] {name[:64]}"),
            payload={"simulated": True, **({"from_broadcaster_user_name": name[:64],
                       "viewers": viewers} if event_type == "channel.raid" else {})},
        )
        self.ingress.record_social_event(event)
        self.generated_events += 1
        self.last_event_at = now

    async def _run(self) -> None:
        index = 0
        try:
            while True:
                name, message = self.PERSONAS[index % len(self.PERSONAS)]
                self.submit(name, message)
                index += 1
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            raise
