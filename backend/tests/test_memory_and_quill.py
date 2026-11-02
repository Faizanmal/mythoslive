import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.master import AIGameMaster, EmbeddingDimensionError
from app.ai.quill import QuillRequest, QuillService
from app.ai.repository import AIRepository, rank_memory_candidates
from app.contracts.events import GameEvent
from app.core.settings import Settings


def test_embedding_dimension_mismatch_is_explicit() -> None:
    class FakeClient:
        configured = True

        async def embed(self, _texts, _model):
            return [[0.1, 0.2, 0.3]]

    master = object.__new__(AIGameMaster)
    master.settings = SimpleNamespace(ai_embedding_model="embed", embedding_dimension=4)
    master.client = FakeClient()
    with pytest.raises(EmbeddingDimensionError, match="configured 4, received 3"):
        asyncio.run(master._embedding_for("safe test query"))


def test_memory_retrieval_ranks_and_diversifies() -> None:
    now = datetime.now(UTC)
    candidates = [
        {
            "id": uuid4(),
            "kind": "world_fact",
            "content": "Lanterns light Emberfall.",
            "importance": 0.9,
            "created_at": now,
            "embedding": [1.0, 0.0],
            "similarity": 0.98,
        },
        {
            "id": uuid4(),
            "kind": "world_fact",
            "content": "Emberfall lanterns glow brightly.",
            "importance": 0.8,
            "created_at": now,
            "embedding": [0.999, 0.01],
            "similarity": 0.97,
        },
        {
            "id": uuid4(),
            "kind": "quest",
            "content": "The party crossed the river.",
            "importance": 0.7,
            "created_at": now - timedelta(days=1),
            "embedding": [0.0, 1.0],
            "similarity": 0.6,
        },
    ]
    result = rank_memory_candidates(candidates, query_embedding=[1.0, 0.0], limit=3)
    assert [item["kind"] for item in result] == ["world_fact", "quest"]
    assert result[0]["content"] == candidates[0]["content"]


def test_memory_write_validation_happens_before_database_access() -> None:
    repository = AIRepository(None)

    async def reject():
        with pytest.raises(ValueError, match="kind or content length"):
            await repository.write_memory(
                world_id=uuid4(), content="raw transcript", kind="chat_log", importance=0.5
            )

    asyncio.run(reject())


@pytest.mark.asyncio
async def test_quill_uses_only_stored_consenting_callback_and_respects_cooldown():
    world_id, viewer_id = uuid4(), uuid4()

    class Repository:
        async def viewer_id_for_identity(self, _world, _identity):
            return viewer_id, True, True

    class Master:
        async def _retrieve_memories(self, _world, ids, _query, *, include_world):
            assert ids == [viewer_id]
            assert include_world is False
            return [{"kind": "viewer_moment", "content": "Crossed the glass orchard in chapter A."}]

    service = object.__new__(QuillService)
    service.repository = Repository()
    service.game_master = Master()
    service.settings = Settings(quill_user_cooldown_seconds=30, quill_global_messages_per_minute=6)
    service._opted_out = set()
    service._memory_disabled = set()
    service._user_last = {}
    service._global_sent = {}
    service._allow = QuillService._allow.__get__(service)
    from app.contracts.events import ActorIdentity

    request = QuillRequest(
        "join",
        world_id,
        "viewer-key",
        GameEvent(
            event_id=uuid4(),
            occurred_at=datetime.now(UTC),
            source="twitch",
            world_id=world_id,
            event_type="chat.command.join",
            actor=ActorIdentity(identity_key="viewer-key", display_name="Tester"),
            payload={"command": "join"},
        ),
    )
    assert service._allow(request)
    assert not service._allow(request)
    text = await service._greeting(request)
    assert "Crossed the glass orchard in chapter A" in text


@pytest.mark.asyncio
async def test_quill_optout_blocks_queued_personalization():
    service = object.__new__(QuillService)
    service._opted_out = {(uuid4(), "viewer-key")}
    service._user_last = {}
    service._global_sent = {}
    service.settings = Settings()
    world_id, _ = next(iter(service._opted_out))
    assert not service._allow(QuillRequest("join", world_id, "viewer-key"))
