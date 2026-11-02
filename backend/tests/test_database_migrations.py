import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.ai.repository import AIRepository
from app.contracts.events import ActorIdentity
from app.contracts.events import GameEvent as ContractGameEvent
from app.db.session import create_session_factory
from app.engine.repository import EngineRepository
from app.engine.rules import RulesEngine
from app.engine.service import GameEngineService
from app.models.entities import (
    Chronicle,
    DashboardAudit,
    GameSession,
    Hero,
    Memory,
    Viewer,
    World,
    WorldEventPending,
)
from app.models.entities import (
    GameEvent as GameEventRow,
)
from app.repositories.dashboard import DashboardRepository


def test_database_connectivity_and_fresh_migration() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL migration integration test")

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    async def verify_database() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                extension = await connection.scalar(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
                tables = await connection.run_sync(
                    lambda sync_connection: set(
                        __import__("sqlalchemy").inspect(sync_connection).get_table_names()
                    )
                )
                columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in __import__("sqlalchemy")
                        .inspect(sync_connection)
                        .get_columns("memories")
                    }
                )
            assert revision == "0006_streamer_control_room"
            assert extension == "vector"
            assert {
                "channels",
                "oauth_tokens",
                "worlds",
                "viewers",
                "heroes",
                "sessions",
                "scenes",
                "votes",
                "game_events",
                "world_events_pending",
                "memories",
                "llm_calls",
                "chronicles",
                "overlay_access_keys",
            }.issubset(tables)
            assert {"dashboard_configs", "dashboard_audit"}.issubset(tables)
            assert {
                "kind",
                "content",
                "importance",
                "last_used_at",
                "use_count",
                "archived_at",
            } <= columns

            # The same normalized input id must commit effects only once.
            world_id = uuid4()
            async with engine.begin() as connection:
                channel_id = uuid4()
                await connection.execute(
                    text(
                        "INSERT INTO channels (id, twitch_broadcaster_id, display_name) "
                        "VALUES (:id, :twitch_id, :name)"
                    ),
                    {
                        "id": channel_id,
                        "twitch_id": f"test-{uuid4().hex[:27]}",
                        "name": "Engine Test",
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO worlds (id, channel_id, slug, name) "
                        "VALUES (:id, :channel_id, :slug, :name)"
                    ),
                    {"id": world_id, "channel_id": channel_id, "slug": "test", "name": "Test"},
                )
            sessions = create_session_factory(engine)
            repository = EngineRepository(sessions)
            viewer_key = f"simulator:test-{uuid4().hex}"
            incoming = ContractGameEvent(
                event_id=uuid4(),
                event_type="chat.command.join",
                source="simulator",
                world_id=world_id,
                occurred_at=datetime.now(UTC),
                actor=ActorIdentity(
                    kind="simulator", identity_key=viewer_key, display_name="[SIM] Test"
                ),
                payload={"command": "join", "arguments": None, "simulated": True},
            )
            state, _outputs, first_applied = await repository.process_event(incoming, RulesEngine())
            _state, _outputs, second_applied = await repository.process_event(
                incoming, RulesEngine()
            )
            assert first_applied is True and second_applied is False
            async with sessions() as db_session:
                stored = await db_session.scalar(
                    select(func.count())
                    .select_from(GameEventRow)
                    .where(GameEventRow.event_id == incoming.event_id)
                )
                assert stored == 1

            rules = RulesEngine()
            consent_event = ContractGameEvent(
                event_id=uuid4(),
                event_type="chat.command.memory",
                source="simulator",
                world_id=world_id,
                occurred_at=datetime.now(UTC),
                actor=ActorIdentity(
                    kind="simulator", identity_key=viewer_key, display_name="[SIM] Test"
                ),
                payload={"command": "memory", "arguments": "on", "simulated": True},
            )
            await repository.process_event(consent_event, rules)
            async with sessions() as db_session:
                viewer_id = await db_session.scalar(
                    select(Viewer.id).where(Viewer.world_id == world_id)
                )
                viewer = await db_session.get(Viewer, viewer_id)
                assert viewer is not None and viewer.memory_consent

            memories = AIRepository(sessions)
            await memories.write_memory(
                world_id=world_id,
                viewer_id=viewer_id,
                kind="viewer_moment",
                content="Crossed the glass orchard in Session A.",
                importance=0.7,
            )
            before_optout = await memories.memories(
                world_id,
                viewer_ids=[viewer_id],
                query_embedding=None,
                include_world=False,
            )
            assert before_optout and before_optout[0]["content"] == (
                "Crossed the glass orchard in Session A."
            )

            async with sessions.begin() as db_session:
                db_session.add(
                    Chronicle(
                        world_id=world_id,
                        session_id=state.session_id,
                        title="Session A",
                        recap={
                            "title": "Session A",
                            "cliffhanger": "The lantern road bends north.",
                        },
                    )
                )
                session_a = await db_session.get(GameSession, state.session_id)
                assert session_a is not None
                session_a.state = "ENDED"
                session_a.ended_at = datetime.now(UTC)
            assert (await memories.prior_recap(world_id))["title"] == "Session A"
            state_b, _ = await repository.start_session(world_id, rules, seed=2)
            assert state_b.session_id != state.session_id
            assert (await memories.prior_recap(world_id))["cliffhanger"] == (
                "The lantern road bends north."
            )

            # Dashboard controls and proposal writes stay scoped to their authenticated world.
            other_world_id = uuid4()
            async with sessions.begin() as db_session:
                db_session.add(
                    World(
                        id=other_world_id,
                        channel_id=channel_id,
                        slug=f"other-{uuid4().hex[:8]}",
                        name="Other world",
                    )
                )
                proposal_id = uuid4()
                veto_id = uuid4()
                db_session.add_all(
                    [
                        WorldEventPending(
                            id=proposal_id,
                            world_id=world_id,
                            payload={
                                "title": "Open the Lantern Festival",
                                "description": "The town prepares a celebration.",
                                "effect": {"flag_id": "lantern_festival"},
                            },
                        ),
                        WorldEventPending(
                            id=veto_id,
                            world_id=world_id,
                            payload={
                                "title": "Unsafe proposal",
                                "effect": {"flag_id": "market_open"},
                            },
                        ),
                    ]
                )
            dashboard = DashboardRepository(sessions)
            assert not await dashboard.edit_proposal(
                other_world_id,
                proposal_id,
                "test-broadcaster",
                description="Cross-world edit",
                flag_id="market_open",
            )
            assert await dashboard.edit_proposal(
                world_id,
                proposal_id,
                "test-broadcaster",
                description="A keeper-approved celebration.",
                flag_id="lantern_festival",
            )
            assert (
                await dashboard.decide_proposal(
                    other_world_id, proposal_id, "other-broadcaster", approve=True
                )
                is None
            )
            assert (
                await dashboard.decide_proposal(
                    world_id, proposal_id, "test-broadcaster", approve=True
                )
                == "applied"
            )
            assert (
                await dashboard.decide_proposal(
                    world_id, veto_id, "test-broadcaster", approve=False
                )
                == "rejected"
            )
            async with sessions() as db_session:
                canonical = await db_session.get(World, world_id)
                assert "lantern_festival" in canonical.state["flags"]
                actions = set(
                    await db_session.scalars(
                        select(DashboardAudit.action).where(DashboardAudit.world_id == world_id)
                    )
                )
                assert {"proposal.edited", "proposal.approved", "proposal.vetoed"} <= actions

            controls = GameEngineService(repository)
            controlled_state = await controls.start_session(
                other_world_id, source="dashboard", session_config={"difficulty": "normal"}
            )
            await controls.dashboard_control(other_world_id, "pause", "test-broadcaster")
            assert (await controls.get_state(other_world_id)).state.value == "PAUSED"
            await controls.dashboard_control(other_world_id, "resume", "test-broadcaster")
            assert (await controls.get_state(other_world_id)).state.value != "PAUSED"
            async with sessions() as db_session:
                dashboard_events = await db_session.scalars(
                    select(GameEventRow).where(
                        GameEventRow.world_id == other_world_id,
                        GameEventRow.session_id == controlled_state.session_id,
                        GameEventRow.source == "dashboard",
                    )
                )
                assert len(list(dashboard_events.all())) >= 2

            optout_event = ContractGameEvent(
                event_id=uuid4(),
                event_type="chat.command.optout",
                source="simulator",
                world_id=world_id,
                occurred_at=datetime.now(UTC),
                actor=ActorIdentity(
                    kind="simulator", identity_key=viewer_key, display_name="[SIM] Test"
                ),
                payload={"command": "optout", "simulated": True},
            )
            await repository.process_event(optout_event, rules)
            after_optout = await memories.memories(
                world_id,
                viewer_ids=[viewer_id],
                query_embedding=None,
                include_world=True,
            )
            assert after_optout == []
            async with sessions() as db_session:
                viewer = await db_session.get(Viewer, viewer_id)
                assert viewer is not None and viewer.opted_out and not viewer.memory_consent
                assert (
                    await db_session.scalar(
                        select(func.count())
                        .select_from(Memory)
                        .where(Memory.viewer_id == viewer_id)
                    )
                    == 0
                )
                assert (
                    await db_session.scalar(
                        select(func.count()).select_from(Hero).where(Hero.viewer_id == viewer_id)
                    )
                    == 0
                )
            async with sessions.begin() as db_session:
                await db_session.execute(
                    delete(World).where(World.id.in_([world_id, other_world_id]))
                )
        finally:
            await engine.dispose()

    asyncio.run(verify_database())
