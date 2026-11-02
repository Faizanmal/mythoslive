"""Run a complete, seeded Emberfall session without Twitch or LLM services."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.engine.repository import EngineRepository
from app.engine.service import GameEngineService
from app.services.ingress import EventRecorder, IngressPipeline
from app.services.simulator import SimulatorService


async def run(personas: int = 15, seed: int = 2026) -> None:
    if personas < 15:
        raise ValueError("A full seeded simulator session requires at least 15 personas")
    settings = get_settings()
    world_id = UUID(settings.sim_world_id)
    database = create_database_engine(settings.database_url)
    sessions = create_session_factory(database)
    engine = GameEngineService(EngineRepository(sessions))
    recorder = EventRecorder(max_items=5_000)
    ingress = IngressPipeline(settings, recorder)
    simulator = SimulatorService(settings, ingress, recorder)
    try:
        await engine.ensure_simulator_world(world_id)
        await engine.restore()
        start_time = datetime.now(UTC)
        state = await engine.start_session(world_id, seed=seed, now=start_time)

        async def say(name: str, message: str) -> None:
            cursor = recorder.sequence
            simulator.submit(name, message)
            for _, event in recorder.since(cursor):
                await engine.process_event(event)

        names = [f"Emberfall Viewer {index:02d}" for index in range(1, personas + 1)]
        classes = ("warrior", "mage", "rogue", "cleric", "bard")
        for name in names:
            await say(name, "!join")
        await asyncio.sleep(0.55)
        for index, name in enumerate(names):
            await say(name, f"!class {classes[index % len(classes)]}")
        await asyncio.sleep(0.55)

        clock = start_time

        async def advance(seconds: int) -> None:
            nonlocal clock
            clock += timedelta(seconds=seconds)
            await engine.tick_once(clock)

        await advance(6)  # LOBBY -> INTRO
        await advance(5)  # INTRO -> VOTE
        for name in names:
            await say(name, "!1")
        await advance(11)  # VOTE -> COMBAT
        await asyncio.sleep(0.55)
        for name in names:
            await say(name, "!attack")
        await advance(13)  # COMBAT -> PUZZLE
        await asyncio.sleep(0.55)
        await say(names[0], "!answer clock")
        await advance(11)  # PUZZLE -> EVENT
        await advance(6)  # EVENT -> BOSS

        for _round in range(6):
            if state.state.value in {"RECAP", "ENDED"}:
                break
            await asyncio.sleep(1.05)
            for name in names:
                await say(name, "!attack")
            state = await engine.get_state(world_id) or state
        if state.state.value == "BOSS":
            await advance(181)  # Deterministic timeout guarantees a completed run.
        if state.state.value == "RECAP":
            await advance(6)
        state = await engine.get_state(world_id) or state
        print(
            f"Emberfall simulator complete: session={state.session_id} "
            f"personas={personas} state={state.state.value} "
            f"engine_events={engine.sequence} seed={seed}"
        )
        if state.state.value != "ENDED":
            raise RuntimeError(f"Seeded simulator stopped in {state.state.value}, expected ENDED")
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personas", type=int, default=15)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    asyncio.run(run(args.personas, args.seed))


if __name__ == "__main__":
    main()
