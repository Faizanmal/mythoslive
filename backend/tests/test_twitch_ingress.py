from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.contracts.events import GameEvent
from app.core.encryption import TokenCipher
from app.core.settings import Settings
from app.services.command_parser import CommandRejected, parse_command
from app.services.ingress import EventRecorder, EventSubDeduper, IngressPipeline
from app.services.simulator import SimulatorService
from app.services.twitch_oauth import OAuthStateStore


@pytest.mark.asyncio
async def test_oauth_state_is_one_use_role_bound_and_random() -> None:
    store = OAuthStateStore()
    first = await store.issue("bot")
    second = await store.issue("bot")
    assert first != second
    assert not await store.consume("broadcaster", first)
    assert not await store.consume("bot", first)  # wrong-role attempt consumes state
    assert not await store.consume("bot", first)
    assert await store.consume("bot", second)


def test_token_cipher_round_trip_and_scope_set() -> None:
    from cryptography.fernet import Fernet

    cipher = TokenCipher(Fernet.generate_key().decode())
    ciphertext = cipher.encrypt("not-a-real-token")
    assert b"not-a-real-token" not in ciphertext
    assert cipher.decrypt(ciphertext) == "not-a-real-token"


def test_parser_valid_invalid_and_moderator_only_commands() -> None:
    assert parse_command("!JOIN") and parse_command("!class warrior")
    assert parse_command("!1").name == "vote"
    for command in (
        "!join",
        "!class mage",
        "!2",
        "!vote 3",
        "!attack",
        "!heal",
        "!shield",
        "!special",
        "!answer 42",
        "!hero",
        "!me",
        "!lore",
        "!quill",
        "!optout",
    ):
        assert parse_command(command) is not None
    with pytest.raises(CommandRejected):
        parse_command("!class wizard")
    with pytest.raises(CommandRejected):
        parse_command("!pause")
    assert parse_command("!pause", is_moderator=True).name == "pause"


def test_deduper_and_bot_self_filter() -> None:
    deduper = EventSubDeduper(max_items=2, ttl_seconds=10)
    assert deduper.accept("one", now=1)
    assert not deduper.accept("one", now=2)
    settings = Settings(_env_file=None)
    recorder = EventRecorder()
    ingress = IngressPipeline(settings, recorder)
    ingress.bot_user_id = "bot-1"
    world = UUID("6c9f5a98-8f43-5bd5-a263-239ea8b494fc")
    assert (
        ingress.handle_chat(
            message="!join", source="twitch", world_id=world, user_id="bot-1", display_name="Bot"
        )
        is None
    )
    assert (
        ingress.handle_chat(
            message="!join",
            source="twitch",
            world_id=world,
            user_id="viewer-1",
            display_name="Viewer",
        )
        is not None
    )
    assert recorder.metrics.bot_messages == 1


def test_user_cooldown_rejects_rapid_repeat() -> None:
    settings = Settings(_env_file=None, command_user_cooldown_seconds=1.0)
    clock = [10.0]
    ingress = IngressPipeline(settings, EventRecorder(), clock=lambda: clock[0])
    kwargs = dict(
        message="!join",
        source="twitch",
        world_id=UUID("6c9f5a98-8f43-5bd5-a263-239ea8b494fc"),
        user_id="viewer-1",
        display_name="Viewer",
    )
    assert ingress.handle_chat(**kwargs) is not None
    assert ingress.handle_chat(**kwargs) is None
    clock[0] += 1.0
    assert ingress.handle_chat(**kwargs) is not None


def test_simulator_and_twitch_commands_share_event_shape() -> None:
    settings = Settings(_env_file=None)
    recorder = EventRecorder()
    ingress = IngressPipeline(settings, recorder)
    world = UUID("6c9f5a98-8f43-5bd5-a263-239ea8b494fc")
    twitch = ingress.handle_chat(
        message="!join", source="twitch", world_id=world, user_id="viewer", display_name="Hero"
    )
    simulated = ingress.handle_chat(
        message="!join", source="simulator", world_id=world, user_id=None, display_name="Hero"
    )
    assert twitch is not None and simulated is not None
    assert twitch.event_type == simulated.event_type
    assert twitch.payload["command"] == simulated.payload["command"]
    assert twitch.source == "twitch" and simulated.source == "simulator"
    assert simulated.payload["simulated"] is True
    assert simulated.actor and simulated.actor.display_name.startswith("[SIM]")


def test_simulated_raid_uses_the_same_normalized_event_type_and_effect_fields() -> None:
    settings = Settings(_env_file=None)
    recorder = EventRecorder()
    ingress = IngressPipeline(settings, recorder)
    simulator = SimulatorService(settings, ingress, recorder)
    simulator.submit_social("channel.raid", "Raiders", 55)
    simulated = recorder.since()[-1][1]
    twitch = GameEvent(
        event_id=uuid4(), event_type="channel.raid", occurred_at=datetime.now(UTC),
        source="twitch", world_id=UUID(settings.sim_world_id),
        payload={"from_broadcaster_user_name": "Raiders", "viewers": 55, "simulated": False},
    )
    assert simulated.event_type == twitch.event_type == "channel.raid"
    assert simulated.source == "simulator" and twitch.source == "twitch"
    assert simulated.payload["from_broadcaster_user_name"] == twitch.payload[
        "from_broadcaster_user_name"
    ]
    assert simulated.payload["viewers"] == twitch.payload["viewers"]
    assert simulated.payload["simulated"] is True
    assert simulated.actor is not None and simulated.actor.display_name.startswith("[SIM]")
