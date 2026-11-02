from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.contracts.events import ActorIdentity, GameEvent
from app.engine.catalog import ALLOWED_BOSS_MECHANICS, ContentCatalog
from app.engine.puzzles import answer_matches, normalize_answer
from app.engine.rules import (
    CLASS_STATS,
    MAX_GOLD,
    MAX_XP,
    RulesEngine,
)
from app.engine.state import GameState, SessionState, level_for_xp, xp_required_for_level

WORLD = uuid4()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def event(identity: str, command: str, args=None, *, seconds=0, moderator=False) -> GameEvent:
    return GameEvent(
        event_id=uuid4(),
        event_type=f"chat.command.{command}",
        occurred_at=NOW + timedelta(seconds=seconds),
        source="simulator",
        world_id=WORLD,
        actor=ActorIdentity(
            kind="simulator", identity_key=f"simulator:{identity}", display_name=f"[SIM] {identity}"
        ),
        payload={
            "command": command,
            "arguments": args,
            "is_moderator": moderator,
            "simulated": True,
        },
    )


def add_hero(engine: RulesEngine, state: GameState, name: str, class_name: str, *, at=0):
    engine.apply(state, event(name, "join", seconds=at))
    engine.apply(state, event(name, "class", class_name, seconds=at + 2))
    return state.heroes[f"simulator:{name}"]


def test_transition_legality_and_pause_resume() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, seed=7, now=NOW)
    with pytest.raises(ValueError, match="Illegal"):
        engine.transition(state, SessionState.BOSS, NOW)
    engine.transition(state, SessionState.INTRO, NOW)
    paused = engine.apply(state, event("host", "pause", seconds=1, moderator=True))
    assert state.state == SessionState.PAUSED
    assert paused[0].event_type == "paused"
    engine.apply(state, event("host", "resume", seconds=2, moderator=True))
    assert state.state == SessionState.INTRO


def test_hero_join_restore_and_class_validation() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, now=NOW)
    hero = add_hero(engine, state, "Ada", "mage")
    assert hero.stats == CLASS_STATS["mage"]
    assert hero.max_hp == 85 and hero.hp == 85
    invalid = engine.apply(state, event("Ada", "class", "ranger", seconds=4))
    assert invalid[0].event_type == "toast"
    change = engine.apply(state, event("Ada", "class", "warrior", seconds=5))
    assert "already chosen" in change[0].payload["text"]
    restored = GameState.restore(state.snapshot())
    assert restored.heroes["simulator:Ada"].class_name == "mage"
    assert restored.revision == state.revision


def test_duplicate_event_id_is_applied_once() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, now=NOW)
    incoming = event("Repeat", "join")
    assert engine.apply_once(state, incoming)
    assert engine.apply_once(state, incoming) == []
    assert len(state.heroes) == 1


def test_follow_effects_are_capped_deduplicated_and_visible() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, now=NOW)
    state.state = SessionState.COMBAT
    follow = GameEvent(
        event_id=uuid4(), event_type="channel.follow", occurred_at=NOW, source="simulator",
        world_id=WORLD, actor=ActorIdentity(kind="simulator", display_name="[SIM] Emberfriend"),
        payload={"simulated": True},
    )
    first = engine.apply_once(state, follow)
    assert first[0].payload["effect"] == "torch_lit"
    assert first[0].payload["morale_delta"] == 1
    assert state.torches_lit == 1 and state.morale_bonus == 1
    assert engine.apply_once(state, follow) == []
    for _index in range(20):
        repeated = follow.model_copy(update={"event_id": uuid4()})
        engine.apply_once(state, repeated)
    assert state.torches_lit == 12 and state.morale_bonus == 3


def test_raid_reinforcements_are_bounded_temporary_and_help_in_combat() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, now=NOW)
    state.state = SessionState.COMBAT
    state.enemy = {"name": "Ashling", "hp": 200, "max_hp": 200, "defense": 0}
    raid = GameEvent(
        event_id=uuid4(), event_type="channel.raid", occurred_at=NOW, source="simulator",
        world_id=WORLD, actor=ActorIdentity(kind="simulator", display_name="[SIM] Raid Party"),
        payload={"simulated": True, "from_broadcaster_user_name": "Raid Party", "viewers": 10_000},
    )
    output = engine.apply_once(state, raid)
    assert output[0].payload["reinforcements"] == 4
    assert state.reinforcements[0]["units"] == 4
    zero_raid = raid.model_copy(update={"event_id": uuid4(), "payload": {
        "simulated": True, "from_broadcaster_user_name": "Empty Raid", "viewers": 0,
    }})
    zero_output = engine.apply(state, zero_raid)
    assert zero_output[0].payload["reinforcements"] == 0
    add_hero(engine, state, "Raider", "warrior")
    damaged = engine.apply(state, event("Raider", "attack", seconds=4))
    assert any(item.payload.get("source") == "Visiting reinforcements" for item in damaged)
    for _index in range(5):
        engine.apply(state, raid.model_copy(update={"event_id": uuid4()}))
    assert len(state.reinforcements) <= 3
    assert sum(squad["units"] for squad in state.reinforcements) <= 12
    engine.tick(state, NOW + timedelta(seconds=91))
    assert state.reinforcements == []


def test_vote_overwrite_bard_weight_seeded_tie_and_stat_check() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, seed=123, now=NOW)
    bard = add_hero(engine, state, "Bard", "bard")
    warrior = add_hero(engine, state, "Tank", "warrior")
    state.scene = engine.catalog.scene(0)
    state.scene_id = state.scene["id"]
    state.state = SessionState.VOTE
    engine.apply(state, event("Bard", "vote", 1, seconds=6))
    engine.apply(state, event("Tank", "vote", 2, seconds=6))
    tally = engine.vote_tally(state)
    assert tally["tally"] == {"1": 2, "2": 1}
    engine.apply(state, event("Bard", "vote", 2, seconds=7))
    assert engine.vote_tally(state)["tally"] == {"2": 3}
    result = engine._resolve_vote(state, NOW + timedelta(seconds=10))[0]
    assert result.event_type == "vote_result"
    assert result.payload["choice"] == 2
    assert result.payload["outcome"] in {"success", "partial", "failure"}
    assert bard.votes_cast == 2 and warrior.votes_cast == 1

    tie = engine.new_session(WORLD, seed=321, now=NOW)
    add_hero(engine, tie, "One", "warrior")
    add_hero(engine, tie, "Two", "mage")
    tie.scene = engine.catalog.scene(2)
    tie.scene_id = tie.scene["id"]
    tie.state = SessionState.VOTE
    engine.apply(tie, event("One", "vote", 1, seconds=6))
    engine.apply(tie, event("Two", "vote", 2, seconds=6))
    first_choice = engine._resolve_vote(tie, NOW + timedelta(seconds=10))[0].payload["choice"]
    tie.votes = {"simulator:One": 1, "simulator:Two": 2}
    tie.boss_index = 0
    repeat = GameState.restore(tie.snapshot())
    second_choice = engine._resolve_vote(repeat, NOW + timedelta(seconds=10))[0].payload["choice"]
    assert first_choice == second_choice


def test_combat_cooldown_combo_damage_and_boss_phases() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, seed=44, now=NOW)
    for index in range(3):
        add_hero(engine, state, f"H{index}", "warrior", at=index * 3)
    state.state = SessionState.COMBAT
    state.enemy = {
        "name": "Practice Ember",
        "hp": 300,
        "max_hp": 300,
        "defense": 0,
        "attack": 1,
        "next_attack_at": 10_000,
    }
    outputs = []
    for index in range(3):
        outputs += engine.apply(state, event(f"H{index}", "attack", seconds=20))
    assert any(output.event_type == "combo" for output in outputs)
    assert state.enemy["hp"] < 300
    hp_after = state.enemy["hp"]
    engine.apply(state, event("H0", "attack", seconds=20.2))
    assert state.enemy["hp"] == hp_after

    state.state = SessionState.BOSS
    state.enemy = {
        "name": "Practice Boss",
        "hp": 60,
        "max_hp": 100,
        "defense": 0,
        "mechanic": "shield_wall",
        "mechanics": ["shield_wall", "weak_point", "enrage"],
    }
    assert engine._boss_phase_if_due(state, NOW)[0].payload["phase"] == 2
    state.enemy["hp"] = 20
    assert engine._boss_phase_if_due(state, NOW)[0].payload["phase"] == 3
    assert state.enemy["mechanic"] in ALLOWED_BOSS_MECHANICS


def test_cleric_special_revives_a_ghost() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, now=NOW)
    cleric = add_hero(engine, state, "Healer", "cleric")
    ally = add_hero(engine, state, "Fallen", "rogue", at=3)
    ally.hp = 0
    ally.downed = True
    ally.ghost = True
    state.state = SessionState.COMBAT
    state.enemy = {"name": "Cinderling", "hp": 100, "max_hp": 100, "defense": 0}
    result = engine.apply(state, event("Healer", "special", seconds=10))
    assert result[0].event_type == "hero_updated"
    assert not ally.downed and not ally.ghost
    assert ally.hp > 0 and cleric.support_done > 0


def test_puzzle_normalization_aliases_and_conservative_fuzzy_match() -> None:
    assert normalize_answer("  Thé Clock! ") == "the clock"
    assert answer_matches("lantern keepr", ["lantern keeper"])
    assert not answer_matches("candle", ["clock"])


def test_xp_curve_caps_cosmetics_and_chronicle_recap() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, seed=9, now=NOW)
    hero = add_hero(engine, state, "Leveler", "cleric")
    state.state = SessionState.EVENT
    hero.xp = MAX_XP - 50
    hero.gold = MAX_GOLD - 1
    engine._reward_party(state, xp=1000, gold=100, now=NOW)
    assert hero.xp == MAX_XP and hero.gold == MAX_GOLD
    assert level_for_xp(0) == 1
    assert level_for_xp(xp_required_for_level(1)) == 2
    assert hero.level >= 20 and "lantern-aegis" in hero.cosmetics
    state.state = SessionState.RECAP
    engine._make_recap(state, NOW)
    assert state.recap["party_size"] == 1
    assert set(state.recap) >= {
        "title",
        "key_moments",
        "mvp_categories",
        "world_flags",
        "cliffhanger",
    }


def test_content_catalog_counts_and_allowlists() -> None:
    catalog = ContentCatalog()
    assert len(catalog.data["scenes"]) >= 20
    assert len(catalog.data["bosses"]) >= 6
    assert len(catalog.data["riddles"]) >= 15
    assert all(set(boss["mechanics"]) <= ALLOWED_BOSS_MECHANICS for boss in catalog.data["bosses"])


def test_seeded_fifteen_person_session_reaches_ended_without_llm() -> None:
    engine = RulesEngine()
    state = engine.new_session(WORLD, seed=555, now=NOW)
    classes = ("warrior", "mage", "rogue", "cleric", "bard")
    names = [f"Viewer{i}" for i in range(15)]
    for index, name in enumerate(names):
        add_hero(engine, state, name, classes[index % len(classes)], at=index * 3)
    out = engine.tick(state, NOW + timedelta(seconds=6))
    assert state.state == SessionState.INTRO
    out += engine.tick(state, NOW + timedelta(seconds=11))
    assert state.state == SessionState.VOTE
    for name in names:
        out.extend(engine.apply(state, event(name, "vote", 1, seconds=12)))
    out.extend(engine.tick(state, NOW + timedelta(seconds=22)))
    assert state.state == SessionState.COMBAT
    for index, name in enumerate(names):
        out.extend(engine.apply(state, event(name, "attack", seconds=23 + index)))
    out.extend(engine.tick(state, NOW + timedelta(seconds=35)))
    assert state.state == SessionState.PUZZLE
    out.extend(engine.apply(state, event(names[0], "answer", "clock", seconds=36)))
    out.extend(engine.tick(state, NOW + timedelta(seconds=46)))
    out.extend(engine.tick(state, NOW + timedelta(seconds=52)))
    assert state.state == SessionState.BOSS
    for round_index in range(5):
        for index, name in enumerate(names):
            out.extend(
                engine.apply(state, event(name, "attack", seconds=60 + round_index * 20 + index))
            )
        if state.state == SessionState.RECAP:
            break
    if state.state == SessionState.BOSS:
        out.extend(engine.tick(state, NOW + timedelta(seconds=240)))
    assert state.state == SessionState.RECAP
    out.extend(engine.tick(state, NOW + timedelta(seconds=246)))
    assert state.state == SessionState.ENDED
    assert {"scene_started", "vote_result", "boss_phase", "recap"} <= {
        item.event_type for item in out
    }
