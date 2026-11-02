from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.events import EngineRealtimeEvent, RealtimeGameEvent


def test_representative_realtime_event_matches_contract() -> None:
    message = RealtimeGameEvent.model_validate(
        {
            "schema_version": 1,
            "message_type": "game.event",
            "event": {
                "event_id": str(uuid4()),
                "event_type": "viewer.join",
                "schema_version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "source": "simulator",
                "world_id": str(uuid4()),
                "actor": {"twitch_user_id": "1234", "display_name": "TestHero"},
                "payload": {"source": "browser"},
            },
        }
    )
    assert message.message_type == "game.event"
    assert message.schema_version == 1


def test_realtime_event_rejects_unsupported_version() -> None:
    with pytest.raises(ValidationError):
        RealtimeGameEvent.model_validate({"schema_version": 2, "message_type": "game.event"})


def test_representative_engine_realtime_event_matches_contract() -> None:
    event = EngineRealtimeEvent.model_validate(
        {
            "schema_version": 1,
            "message_type": "engine.event",
            "event_type": "hero_joined",
            "event_id": str(uuid4()),
            "session_id": str(uuid4()),
            "world_id": str(uuid4()),
            "occurred_at": datetime.now(UTC).isoformat(),
            "sequence": 1,
            "payload": {"display_name": "[SIM] Test", "simulated": True},
        }
    )
    assert event.event_type == "hero_joined"
    assert event.schema_version == 1
