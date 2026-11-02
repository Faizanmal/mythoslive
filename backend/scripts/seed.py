"""Idempotently seed the local Emberfall judge campaign."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.engine.repository import EngineRepository
from app.models.entities import Chronicle, GameSession, Hero, Memory, Viewer, World


async def seed() -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    world_id = UUID(settings.sim_world_id)
    chronicle_ids: list[str] = []
    async with factory.begin() as db:
        await EngineRepository(factory).ensure_simulator_world(world_id)
        world = await db.get(World, world_id)
        assert world is not None
        world.name = "Emberfall"
        world.slug = "emberfall-simulator"
        world.state = {**(world.state or {}), "flags": ["The Cinder Gate is sealed"]}

        sample_people = [
            ("sim-ember-01", "[SIM] Ashrunner", "warrior", True),
            ("sim-ember-02", "[SIM] Mosswhisper", "cleric", False),
            ("sim-ember-03", "[SIM] Starling", "mage", False),
        ]
        viewers: dict[str, Viewer] = {}
        for identity, name, class_name, consent in sample_people:
            viewer = await db.scalar(
                select(Viewer).where(Viewer.world_id == world_id, Viewer.identity_key == identity)
            )
            if viewer is None:
                viewer = Viewer(
                    world_id=world_id,
                    identity_key=identity,
                    identity_kind="simulator",
                    display_name=name,
                    memory_consent=consent,
                )
                db.add(viewer)
                await db.flush()
            viewers[identity] = viewer
            hero = await db.scalar(
                select(Hero).where(Hero.world_id == world_id, Hero.viewer_id == viewer.id)
            )
            if hero is None:
                db.add(
                    Hero(
                        world_id=world_id,
                        viewer_id=viewer.id,
                        class_name=class_name,
                        stats={"level": 3, "strength": 5, "wisdom": 4, "agility": 3},
                        xp=140,
                        cosmetic_gold=12,
                        cosmetics=["ember_pin"],
                    )
                )

        ash = viewers["sim-ember-01"]
        memory = await db.scalar(
            select(Memory).where(
                Memory.world_id == world_id,
                Memory.viewer_id == ash.id,
                Memory.kind == "viewer_moment",
                Memory.content == "[SIM] Ashrunner helped seal the Cinder Gate.",
            )
        )
        if memory is None:
            db.add(
                Memory(
                    world_id=world_id,
                    viewer_id=ash.id,
                    kind="viewer_moment",
                    content="[SIM] Ashrunner helped seal the Cinder Gate.",
                    importance=0.8,
                    consented=True,
                )
            )

        for index, (title, moments, cliffhanger) in enumerate(
            [
                (
                    "The Lantern Road",
                    ["The party lit the old road lanterns.", "A lost courier found the way home."],
                    "A black feather drifted from the sealed gate.",
                ),
                (
                    "The Cinder Gate",
                    ["Ashrunner held the bridge.", "Mosswhisper restored the warding flame."],
                    "Something beneath Emberfall answered the bell.",
                ),
            ],
            start=1,
        ):
            session = await db.scalar(
                select(GameSession).where(
                    GameSession.world_id == world_id,
                    GameSession.snapshot["judge_seed"].as_integer() == index,
                )
            )
            if session is None:
                now = datetime.now(UTC) - timedelta(days=3 - index)
                session = GameSession(
                    world_id=world_id,
                    state="ENDED",
                    started_at=now - timedelta(minutes=35),
                    ended_at=now,
                    snapshot={
                        "judge_seed": index,
                        "heroes": [],
                        "world_flags": ["The Cinder Gate is sealed"],
                    },
                )
                db.add(session)
                await db.flush()
            chronicle = await db.scalar(
                select(Chronicle).where(Chronicle.session_id == session.id)
            )
            if chronicle is None:
                db.add(
                    Chronicle(
                        id=UUID(int=index),
                        world_id=world_id,
                        session_id=session.id,
                        title=title,
                        recap={
                            "title": title,
                            "key_moments": moments,
                            "party_size": 3,
                            "mvp_categories": {"steadfast": "[SIM] Ashrunner"},
                            "level_ups": [],
                            "world_flags": ["The Cinder Gate is sealed"],
                            "cliffhanger": cliffhanger,
                        },
                    )
                )
                chronicle_ids.append(str(UUID(int=index)))
            else:
                chronicle_ids.append(str(chronicle.id))
    await engine.dispose()
    links = ", ".join(f"http://localhost:3000/chronicle/{item}" for item in chronicle_ids)
    print(
        "Emberfall judge campaign is ready: simulated heroes, consented sample memory, "
        f"and two Chronicles. Sample recap URLs: {links}"
    )


if __name__ == "__main__":
    asyncio.run(seed())
