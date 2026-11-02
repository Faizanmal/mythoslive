"""Small deterministic engine load profile; does not contact Twitch or an LLM."""

import json
import resource
import time
from datetime import UTC, datetime
from uuid import uuid4

from app.contracts.events import ActorIdentity, GameEvent
from app.engine.rules import RulesEngine
from app.engine.state import SessionState


def profile(viewers: int, repetitions: int = 8) -> dict[str, float | int]:
    engine = RulesEngine()
    state = engine.new_session(uuid4(), seed=8128)
    state.state = SessionState.COMBAT
    start_cpu = time.process_time()
    start_wall = time.perf_counter()
    count = 0
    for _pass_index in range(repetitions):
        for viewer_index in range(viewers):
            identity = f"viewer-{viewer_index}"
            event = GameEvent(
                event_id=uuid4(), event_type="channel.follow", occurred_at=datetime.now(UTC),
                source="simulator", world_id=state.world_id,
                actor=ActorIdentity(kind="simulator", identity_key=f"simulator:{identity}",
                                    display_name=f"[SIM] {identity}"),
                payload={"simulated": True},
            )
            engine.apply_once(state, event)
            count += 1
    wall = time.perf_counter() - start_wall
    cpu = time.process_time() - start_cpu
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; the Stage 8 harness runs in the backend container.
    return {
        "participants": viewers,
        "events": count,
        "wall_seconds": round(wall, 4),
        "cpu_seconds": round(cpu, 4),
        "cpu_percent_one_core": round(cpu / max(wall, 1e-9) * 100, 1),
        "events_per_second": round(count / max(wall, 1e-9), 1),
        "peak_rss_mb": round(peak_rss / 1024, 1),
    }


if __name__ == "__main__":
    print(json.dumps([profile(size) for size in (15, 50, 100, 250)], indent=2))
