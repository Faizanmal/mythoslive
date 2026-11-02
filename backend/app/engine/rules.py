from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from app.contracts.events import GameEvent
from app.engine.catalog import ContentCatalog
from app.engine.puzzles import answer_matches
from app.engine.state import GameState, HeroState, SessionState, level_for_xp

ALLOWED_CLASSES = frozenset({"warrior", "mage", "rogue", "cleric", "bard"})
ACTIVE_STATES = frozenset(
    {
        SessionState.LOBBY,
        SessionState.INTRO,
        SessionState.VOTE,
        SessionState.COMBAT,
        SessionState.PUZZLE,
        SessionState.EVENT,
        SessionState.BOSS,
    }
)
TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.LOBBY: frozenset({SessionState.INTRO, SessionState.PAUSED}),
    SessionState.INTRO: frozenset({SessionState.VOTE, SessionState.PAUSED}),
    SessionState.VOTE: frozenset({SessionState.COMBAT, SessionState.PAUSED}),
    SessionState.COMBAT: frozenset({SessionState.PUZZLE, SessionState.PAUSED}),
    SessionState.PUZZLE: frozenset({SessionState.EVENT, SessionState.PAUSED}),
    SessionState.EVENT: frozenset({SessionState.BOSS, SessionState.PAUSED}),
    SessionState.BOSS: frozenset({SessionState.RECAP, SessionState.PAUSED}),
    SessionState.RECAP: frozenset({SessionState.ENDED}),
    SessionState.PAUSED: frozenset(ACTIVE_STATES),
    SessionState.ENDED: frozenset(),
}

CLASS_STATS: dict[str, dict[str, int]] = {
    "warrior": {
        "max_hp": 130,
        "strength": 8,
        "intellect": 3,
        "agility": 4,
        "endurance": 8,
        "wisdom": 4,
        "craft": 4,
        "charisma": 3,
        "attack": 14,
        "defense": 8,
        "magic": 2,
        "speed": 4,
    },
    "mage": {
        "max_hp": 85,
        "strength": 3,
        "intellect": 9,
        "agility": 5,
        "endurance": 3,
        "wisdom": 7,
        "craft": 5,
        "charisma": 4,
        "attack": 7,
        "defense": 3,
        "magic": 15,
        "speed": 7,
    },
    "rogue": {
        "max_hp": 95,
        "strength": 5,
        "intellect": 4,
        "agility": 9,
        "endurance": 4,
        "wisdom": 4,
        "craft": 6,
        "charisma": 6,
        "attack": 12,
        "defense": 4,
        "magic": 4,
        "speed": 12,
    },
    "cleric": {
        "max_hp": 105,
        "strength": 4,
        "intellect": 6,
        "agility": 4,
        "endurance": 6,
        "wisdom": 9,
        "craft": 4,
        "charisma": 8,
        "attack": 7,
        "defense": 6,
        "magic": 11,
        "speed": 5,
    },
    "bard": {
        "max_hp": 95,
        "strength": 4,
        "intellect": 5,
        "agility": 6,
        "endurance": 4,
        "wisdom": 5,
        "craft": 5,
        "charisma": 10,
        "attack": 8,
        "defense": 4,
        "magic": 8,
        "speed": 7,
    },
}
PROGRESSION: dict[str, dict[str, int]] = {
    "warrior": {"max_hp": 12, "attack": 2, "defense": 1, "strength": 1},
    "mage": {"max_hp": 6, "magic": 3, "intellect": 1, "wisdom": 1},
    "rogue": {"max_hp": 8, "attack": 2, "speed": 2, "agility": 1},
    "cleric": {"max_hp": 9, "magic": 2, "wisdom": 2, "defense": 1},
    "bard": {"max_hp": 8, "magic": 2, "charisma": 2, "speed": 1},
}
TITLES = {5: "Ember Scout", 10: "Flamebound Champion", 20: "Guardian of Emberfall"}
BOSS_MECHANICS = frozenset({"shield_wall", "aoe_charge", "summon_adds", "weak_point", "enrage"})
MAX_XP = 1_000_000
MAX_GOLD = 100_000
MAX_ACTIONS_PER_SESSION = 1_000
MAX_GLOBAL_ACTIONS_PER_SECOND = 30
MAX_MORALE_BONUS = 3
MAX_TORCHES = 12
MAX_REINFORCEMENT_SQUADS = 3
MAX_REINFORCEMENT_UNITS = 12
REINFORCEMENT_LIFETIME_SECONDS = 90
ACTION_COOLDOWNS = {"attack": 1.0, "heal": 5.0, "shield": 8.0, "special": 15.0}
AI_ENEMY_TEMPLATES = {
    "cinderling": "Cinderling",
    "ash_wisp": "Ash Wisp",
    "ember_wolf": "Ember Wolf",
}
AI_REWARD_TIERS = {"participation": (10, 2), "milestone": (25, 5)}


class RulesEngine:
    """Pure seeded rules. Persistence and transports live outside this class."""

    def __init__(self, catalog: ContentCatalog | None = None) -> None:
        self.catalog = catalog or ContentCatalog()

    def new_session(
        self,
        world_id: UUID,
        session_id: UUID | None = None,
        *,
        seed: int = 1,
        now: datetime | None = None,
    ) -> GameState:
        timestamp = now or datetime.now(UTC)
        return GameState(
            session_id=session_id or uuid4(),
            world_id=world_id,
            seed=seed,
            started_at=timestamp,
            phase_started_at=timestamp,
            last_tick_at=timestamp,
        )

    def set_ai_preferences(self, state: GameState, preferences: dict[str, Any]) -> bool:
        """Store only local deck choices for future phases; never accept model arithmetic."""
        if state.state not in {SessionState.INTRO, SessionState.VOTE} or not preferences:
            return False
        allowed = {"scene_id", "scene_flavor", "enemy_id", "boss_id", "boss_mechanic", "riddle_id"}
        if set(preferences) - allowed:
            return False
        if "scene_id" in preferences and not self.catalog.scene_by_id(str(preferences["scene_id"])):
            return False
        if (
            state.state == SessionState.VOTE
            and preferences.get("scene_id", state.scene_id) != state.scene_id
        ):
            return False
        if "scene_flavor" in preferences and (
            not isinstance(preferences["scene_flavor"], str)
            or len(preferences["scene_flavor"]) > 320
        ):
            return False
        if "enemy_id" in preferences and preferences["enemy_id"] not in AI_ENEMY_TEMPLATES:
            return False
        if "boss_id" in preferences and not self.catalog.boss_by_id(str(preferences["boss_id"])):
            return False
        if "boss_mechanic" in preferences and preferences["boss_mechanic"] not in BOSS_MECHANICS:
            return False
        if "riddle_id" in preferences and not self.catalog.riddle_by_id(
            str(preferences["riddle_id"])
        ):
            return False
        if state.state == SessionState.VOTE:
            # During a live vote the model can only add moderated flavor to the
            # currently selected local scene. It cannot change choices/timer.
            if "scene_id" in preferences and preferences["scene_id"] != state.scene_id:
                return False
            if "scene_flavor" in preferences:
                state.scene["text"] = preferences["scene_flavor"]
        else:
            state.preferred_scene_id = preferences.get("scene_id", state.preferred_scene_id)
            state.preferred_scene_flavor = preferences.get(
                "scene_flavor", state.preferred_scene_flavor
            )
        state.preferred_enemy_id = preferences.get("enemy_id", state.preferred_enemy_id)
        state.preferred_boss_id = preferences.get("boss_id", state.preferred_boss_id)
        state.preferred_boss_mechanic = preferences.get(
            "boss_mechanic", state.preferred_boss_mechanic
        )
        state.preferred_riddle_id = preferences.get("riddle_id", state.preferred_riddle_id)
        state.revision += 1
        return True

    def grant_ai_reward(self, state: GameState, tier: str, now: datetime) -> list[GameEvent]:
        """Allow only fixed, engine-owned party rewards during the EVENT phase."""
        if state.state != SessionState.EVENT or tier not in AI_REWARD_TIERS:
            return []
        xp, gold = AI_REWARD_TIERS[tier]
        return self._reward_party(state, xp=xp, gold=gold, now=now)

    def transition(self, state: GameState, target: SessionState, now: datetime) -> None:
        if target not in TRANSITIONS[state.state]:
            raise ValueError(f"Illegal session transition: {state.state} -> {target}")
        state.state = target
        state.phase_started_at = now
        state.revision += 1

    def start_events(self, state: GameState, *, source: str = "simulator") -> list[GameEvent]:
        return [
            self._emit(state, "session_transition", {"state": state.state.value}, source=source),
            self._emit(
                state, "narration", {"text": "Welcome, wayfarers, to Emberfall."}, source=source
            ),
        ]

    def recover(self, state: GameState, now: datetime) -> list[GameEvent]:
        if state.state in {SessionState.ENDED, SessionState.PAUSED}:
            return []
        state.resume_state = state.state
        self.transition(state, SessionState.PAUSED, now)
        return [
            self._emit(
                state,
                "paused",
                {
                    "state": "PAUSED",
                    "reason": "backend_restart",
                    "resume_state": state.resume_state.value,
                },
                occurred_at=now,
            )
        ]

    def resume_for_simulator(self, state: GameState, now: datetime) -> list[GameEvent]:
        if state.state != SessionState.PAUSED or state.resume_state is None:
            return []
        target, state.resume_state = state.resume_state, None
        self.transition(state, target, now)
        return [
            self._emit(
                state,
                "session_transition",
                {"state": target.value, "resumed_by": "simulator"},
                source="simulator",
                occurred_at=now,
            )
        ]

    def apply(self, state: GameState, event: GameEvent) -> list[GameEvent]:
        if event.world_id != state.world_id:
            return []
        if event.event_type == "channel.follow":
            if state.state not in ACTIVE_STATES:
                return []
            state.world_flags = sorted(set(state.world_flags) | {"a_new_friend_arrived"})
            state.torches_lit = min(MAX_TORCHES, state.torches_lit + 1)
            morale_before = state.morale_bonus
            state.morale_bonus = min(MAX_MORALE_BONUS, morale_before + 1)
            follower = (event.actor.display_name if event.actor else None) or "A new friend"
            state.key_moments.append(f"{follower[:64]} lit an Emberfall torch")
            state.revision += 1
            return [
                self._emit(
                    state,
                    "toast",
                    {
                        "kind": "follow",
                        "effect": "torch_lit",
                        "torches_lit": state.torches_lit,
                        "morale_delta": state.morale_bonus - morale_before,
                        "morale_bonus": state.morale_bonus,
                        "text": f"{follower} followed the Emberfall tale!",
                    },
                    event,
                )
            ]
        if event.event_type == "channel.raid":
            if state.state not in ACTIVE_STATES:
                return []
            raider = str(event.payload.get("from_broadcaster_user_name") or "A visiting party")
            try:
                viewers = max(0, min(10_000, int(event.payload.get("viewers") or 0)))
            except (TypeError, ValueError):
                viewers = 0
            self._expire_reinforcements(state, event.occurred_at.timestamp())
            active_units = sum(int(squad.get("units", 0)) for squad in state.reinforcements)
            units = 0 if viewers == 0 else min(4, 1 + min(viewers, 150) // 50)
            added = min(units, MAX_REINFORCEMENT_UNITS - active_units)
            if len(state.reinforcements) >= MAX_REINFORCEMENT_SQUADS:
                added = 0
            if added:
                state.reinforcements.append({
                    "raider": raider[:64],
                    "units": added,
                    "expires_at": event.occurred_at.timestamp() + REINFORCEMENT_LIFETIME_SECONDS,
                })
                state.revision += 1
                state.key_moments.append(f"{raider[:64]} sent {added} reinforcements")
            return [
                self._emit(
                    state,
                    "toast",
                    {"kind": "raid", "reinforcements": added,
                     "text": f"{raider[:64]} arrives with {viewers} adventurers!"},
                    event,
                )
            ]
        command = event.payload.get("command")
        if not isinstance(command, str) and event.event_type.startswith("chat.command."):
            command = event.event_type.removeprefix("chat.command.")
        identity = self._identity(event)
        if not command or not identity:
            return []
        identity_digest = sha256(identity.encode()).hexdigest()
        if identity_digest in state.opted_out and command != "optout":
            return [
                self._emit(
                    state, "toast", {"text": "This viewer has opted out of game data."}, event
                )
            ]
        now = event.occurred_at
        if command == "pause":
            return self._pause(state, event, now)
        if command == "resume":
            return self._resume(state, event, now)
        if command == "skip":
            return self._skip(state, event, now)
        if command == "optout":
            return self._opt_out(state, identity, event)
        if command == "memory":
            enabled = event.payload.get("memory_consent_enabled")
            if not isinstance(enabled, bool):
                text = "Join the party first, then use !memory on or !memory off."
            else:
                text = (
                    "Quill may keep short campaign memories for you. Use !optout to delete them."
                    if enabled
                    else (
                        "Quill will not personalize memories for you; existing stored moments "
                        "remain until !optout."
                    )
                )
            return [self._emit(state, "toast", {"text": text}, event)]
        if state.state in {SessionState.PAUSED, SessionState.ENDED, SessionState.RECAP}:
            return []
        if command == "join":
            return self._join(state, identity, event)
        if command == "class":
            return self._select_class(state, identity, event)
        if command in {"hero", "me"}:
            hero = state.heroes.get(identity)
            text = "Join with !join to create a hero." if hero is None else self._hero_summary(hero)
            return [self._emit(state, "toast", {"text": text}, event)]
        if command == "lore":
            return [
                self._emit(
                    state,
                    "narration",
                    {
                        "text": (
                            "Emberfall is a valley of warm lanterns, clever neighbors, "
                            "and old starlit roads."
                        )
                    },
                    event,
                )
            ]
        if command == "quill":
            return [
                self._emit(
                    state,
                    "narration",
                    {"text": "Quill dips a copper nib: every brave choice leaves a kinder trail."},
                    event,
                )
            ]
        hero = state.heroes.get(identity)
        if hero is None or not hero.joined:
            return [self._emit(state, "toast", {"text": "Join the party with !join first."}, event)]
        if command in {"vote", "1", "2", "3", "4"}:
            return self._vote(state, identity, hero, event)
        if command == "answer":
            return self._answer(state, identity, event)
        if command in {"attack", "heal", "shield", "special"}:
            return self._action(state, identity, hero, command, event)
        return []

    def apply_once(self, state: GameState, event: GameEvent) -> list[GameEvent]:
        event_key = str(event.event_id)
        if event_key in state.processed_event_ids:
            return []
        outputs = self.apply(state, event)
        state.processed_event_ids.append(event_key)
        if len(state.processed_event_ids) > 20_000:
            del state.processed_event_ids[: len(state.processed_event_ids) - 20_000]
        return outputs

    def tick(self, state: GameState, now: datetime) -> list[GameEvent]:
        if state.state == SessionState.PAUSED or state.state == SessionState.ENDED:
            return []
        out: list[GameEvent] = []
        self._expire_reinforcements(state, now.timestamp())
        elapsed = (now - state.phase_started_at).total_seconds()
        if state.state == SessionState.LOBBY and elapsed >= 5:
            out.extend(self._change(state, SessionState.INTRO, now, "The Emberfall path opens."))
        elif state.state == SessionState.INTRO and elapsed >= 4:
            out.extend(self._begin_scene(state, now))
        elif state.state == SessionState.VOTE and elapsed >= float(
            state.session_config.get("vote_window_seconds", 10)
        ):
            out.extend(self._resolve_vote(state, now))
            out.extend(self._start_combat(state, now))
        elif state.state == SessionState.COMBAT:
            out.extend(self._enemy_turn_if_due(state, now))
            if elapsed >= 12:
                out.extend(
                    self._change(
                        state, SessionState.PUZZLE, now, "The party finds an Emberfall riddle."
                    )
                )
                riddle = (
                    self.catalog.riddle_by_id(state.preferred_riddle_id)
                    if state.preferred_riddle_id
                    else None
                ) or self.catalog.riddle(state.scene_index)
                state.preferred_riddle_id = None
                state.scene["riddle"] = riddle
                state.revision += 1
                out.append(
                    self._emit(
                        state,
                        "puzzle_update",
                        {"question": riddle["question"], "solved": False},
                        source="simulator",
                    )
                )
        elif state.state == SessionState.PUZZLE and elapsed >= 10:
            out.extend(
                self._change(
                    state, SessionState.EVENT, now, "A quiet moment lets the party regroup."
                )
            )
        elif state.state == SessionState.EVENT and elapsed >= 5:
            out.extend(self._start_boss(state, now))
        elif state.state == SessionState.BOSS:
            out.extend(self._enemy_turn_if_due(state, now))
            out.extend(self._boss_phase_if_due(state, now))
            if int(state.enemy.get("hp", 1)) <= 0 or elapsed >= 180:
                out.extend(
                    self._change(
                        state, SessionState.RECAP, now, "Emberfall's trial comes to a close."
                    )
                )
                out.extend(self._make_recap(state, now))
        elif state.state == SessionState.RECAP and elapsed >= 5:
            out.extend(self._change(state, SessionState.ENDED, now, "The chronicle is sealed."))
        state.last_tick_at = now
        return out

    def hydrate_hero(
        self,
        state: GameState,
        *,
        identity_key: str,
        display_name: str,
        viewer_id: UUID,
        hero_id: UUID | None,
        class_name: str | None,
        xp: int,
        gold: int,
        cosmetics: list[str],
        stats: dict[str, Any],
    ) -> HeroState:
        class_stats = CLASS_STATS.get(class_name or "", {})
        base_stats = {
            **class_stats,
            **{key: int(value) for key, value in stats.items() if isinstance(value, (int, float))},
        }
        level = level_for_xp(xp)
        hero = HeroState(
            identity_key=identity_key,
            display_name=display_name,
            viewer_id=str(viewer_id),
            hero_id=str(hero_id) if hero_id else None,
            class_name=class_name,
            level=level,
            xp=xp,
            gold=gold,
            title=self._title(level),
            stats=base_stats,
            max_hp=int(base_stats.get("max_hp", 0)),
            hp=int(base_stats.get("hp", base_stats.get("max_hp", 0))),
            downed=bool(base_stats.get("downed", False)),
            ghost=bool(base_stats.get("ghost", False)),
            cosmetics=cosmetics,
            damage_dealt=int(base_stats.get("damage_dealt", 0)),
            support_done=int(base_stats.get("support_done", 0)),
            votes_cast=int(base_stats.get("votes_cast", 0)),
        )
        state.heroes[identity_key] = hero
        return hero

    def _join(self, state: GameState, identity: str, event: GameEvent) -> list[GameEvent]:
        hero = state.heroes.get(identity)
        if hero is None:
            hero = HeroState(
                identity_key=identity,
                display_name=(event.actor.display_name if event.actor else None) or "Wayfarer",
                chat_color=event.actor.color if event.actor else None,
                viewer_id=event.payload.get("engine_viewer_id"),
                class_name=None,
                title="Wayfarer",
                joined=True,
            )
            state.heroes[identity] = hero
            state.key_moments.append(f"{hero.display_name} joined the party")
            state.revision += 1
            return [
                self._emit(
                    state,
                    "hero_joined",
                    {**self._hero_payload(hero), "simulated": bool(event.payload.get("simulated"))},
                    event,
                )
            ]
        if sha256(identity.encode()).hexdigest() in state.opted_out:
            return [self._emit(state, "toast", {"text": "Opted-out heroes cannot rejoin."}, event)]
        hero.joined = True
        hero.display_name = (event.actor.display_name if event.actor else None) or hero.display_name
        if event.actor and event.actor.color:
            hero.chat_color = event.actor.color
        state.revision += 1
        return [self._emit(state, "hero_updated", self._hero_payload(hero), event)]

    def _select_class(self, state: GameState, identity: str, event: GameEvent) -> list[GameEvent]:
        hero = state.heroes.get(identity)
        class_name = event.payload.get("arguments")
        if hero is None or not hero.joined:
            return [self._emit(state, "toast", {"text": "Join before choosing a class."}, event)]
        if state.state not in {SessionState.LOBBY, SessionState.INTRO}:
            return [
                self._emit(
                    state, "toast", {"text": "Class selection is locked after the lobby."}, event
                )
            ]
        if not isinstance(class_name, str) or class_name.casefold() not in ALLOWED_CLASSES:
            return [
                self._emit(
                    state, "toast", {"text": "Choose warrior, mage, rogue, cleric, or bard."}, event
                )
            ]
        class_name = class_name.casefold()
        if hero.class_name and hero.class_name != class_name:
            return [
                self._emit(
                    state,
                    "toast",
                    {"text": "Your class is already chosen for this campaign."},
                    event,
                )
            ]
        hero.class_name = class_name
        hero.stats = dict(CLASS_STATS[class_name])
        hero.max_hp = hero.stats["max_hp"] + (hero.level - 1) * PROGRESSION[class_name]["max_hp"]
        hero.hp = min(hero.max_hp, hero.hp or hero.max_hp)
        state.revision += 1
        state.key_moments.append(f"{hero.display_name} became a {class_name}")
        return [self._emit(state, "hero_updated", self._hero_payload(hero), event)]

    def _vote(
        self, state: GameState, identity: str, hero: HeroState, event: GameEvent
    ) -> list[GameEvent]:
        if state.state != SessionState.VOTE:
            return [self._emit(state, "toast", {"text": "There is no open vote."}, event)]
        options = state.scene.get("options", [])
        choice = event.payload.get("arguments")
        if not isinstance(choice, int) or not 1 <= choice <= len(options):
            return [self._emit(state, "toast", {"text": f"Choose 1–{len(options)}."}, event)]
        state.votes[identity] = choice
        hero.votes_cast += 1
        state.revision += 1
        return [self._emit(state, "vote_tally", self.vote_tally(state), event)]

    def vote_tally(self, state: GameState) -> dict[str, Any]:
        weights: dict[str, int] = {}
        for identity, choice in state.votes.items():
            hero = state.heroes.get(identity)
            weight = 2 if hero and hero.class_name == "bard" else 1
            weights[str(choice)] = weights.get(str(choice), 0) + weight
        return {
            "scene_id": state.scene_id,
            "tally": weights,
            "votes": len(state.votes),
            "weight_rule": "Bard 2, all other classes 1",
        }

    def _resolve_vote(self, state: GameState, now: datetime) -> list[GameEvent]:
        tally = self.vote_tally(state)["tally"]
        if not tally:
            choice = 1
        else:
            max_weight = max(tally.values())
            tied = sorted(int(key) for key, value in tally.items() if value == max_weight)
            material = f"{state.seed}:{state.scene_id}:{','.join(map(str, tied))}".encode()
            choice = tied[int.from_bytes(sha256(material).digest()[:4], "big") % len(tied)]
        option = state.scene.get("options", [])[choice - 1]
        weighted_stats = []
        for identity, vote in state.votes.items():
            if vote != choice:
                continue
            hero = state.heroes.get(identity)
            if hero and not hero.downed and hero.class_name:
                weight = 2 if hero.class_name == "bard" else 1
                weighted_stats.append((hero.stats.get(option.get("stat", "wisdom"), 0), weight))
        average = sum(value * weight for value, weight in weighted_stats) // max(
            1, sum(weight for _, weight in weighted_stats)
        )
        digest = sha256(f"{state.seed}:{state.scene_index}:{choice}:stat".encode()).digest()
        roll = int.from_bytes(digest[:2], "big") % 20 + 1
        morale = min(MAX_MORALE_BONUS, state.morale_bonus)
        total = average + roll + morale
        adjustment = {"easy": -2, "normal": 0, "hard": 2}.get(
            state.session_config.get("difficulty", "normal"), 0
        )
        difficulty = int(option.get("difficulty", 12)) + adjustment
        outcome = (
            "success"
            if total >= difficulty
            else "partial"
            if total >= difficulty - 5
            else "failure"
        )
        payload = {
            "choice": choice,
            "option": option["text"],
            "tally": tally,
            "stat": option.get("stat"),
            "average_stat": average,
            "seeded_roll": roll,
            "total": total,
            "morale_bonus": morale,
            "difficulty": difficulty,
            "outcome": outcome,
            "tie_rule": "sha256(session seed, scene id, tied choices)",
        }
        state.key_moments.append(f"The party chose: {option['text']} ({outcome})")
        state.morale_bonus = max(0, state.morale_bonus - 1)
        state.revision += 1
        out = [self._emit(state, "vote_result", payload, occurred_at=now)]
        if outcome != "failure":
            out.extend(
                self._reward_party(state, xp=40 if outcome == "success" else 20, gold=5, now=now)
            )
        return out

    def _answer(self, state: GameState, identity: str, event: GameEvent) -> list[GameEvent]:
        if state.state != SessionState.PUZZLE:
            return [self._emit(state, "toast", {"text": "No riddle is active."}, event)]
        answer = event.payload.get("arguments")
        if not isinstance(answer, str):
            return []
        riddle = state.scene.get("riddle", {})
        accepted = [riddle.get("answer", ""), *riddle.get("aliases", [])]
        solved = answer_matches(answer, accepted)
        hero = state.heroes.get(identity)
        out = [
            self._emit(
                state,
                "puzzle_update",
                {"solved": solved, "answered_by": hero.display_name if hero else "A wayfarer"},
                event,
            )
        ]
        if solved:
            state.key_moments.append("The party solved an Emberfall riddle")
            out.extend(self._reward_party(state, xp=25, gold=3, now=event.occurred_at))
        return out

    def _action(
        self, state: GameState, identity: str, hero: HeroState, command: str, event: GameEvent
    ) -> list[GameEvent]:
        if state.state not in {SessionState.COMBAT, SessionState.BOSS}:
            return [
                self._emit(
                    state, "toast", {"text": "That action is not available right now."}, event
                )
            ]
        now_epoch = event.occurred_at.timestamp()
        state.global_action_times = [
            stamp for stamp in state.global_action_times if stamp > now_epoch - 1
        ]
        cooldown_key = f"{identity}:{command}"
        if state.cooldowns.get(cooldown_key, 0) > now_epoch:
            return [
                self._emit(state, "toast", {"text": f"{command.title()} is cooling down."}, event)
            ]
        if (
            state.action_count >= MAX_ACTIONS_PER_SESSION
            or len(state.global_action_times) >= MAX_GLOBAL_ACTIONS_PER_SECOND
        ):
            return [
                self._emit(
                    state, "toast", {"text": "The party action limit has been reached."}, event
                )
            ]
        if hero.downed:
            return [
                self._emit(state, "toast", {"text": "Downed heroes need a cleric's help."}, event)
            ]
        action_index = state.action_count
        state.cooldowns[cooldown_key] = now_epoch + ACTION_COOLDOWNS[command]
        state.global_action_times.append(now_epoch)
        state.action_count += 1
        if command == "heal":
            amount = 24 if hero.class_name == "cleric" else 12
            before = hero.hp
            hero.hp = min(hero.max_hp, hero.hp + amount)
            hero.downed = False
            hero.support_done += hero.hp - before
            return [
                self._emit(state, "hero_updated", self._hero_payload(hero), event),
                self._emit(
                    state,
                    "toast",
                    {"text": f"{hero.display_name} recovered {hero.hp - before} HP."},
                    event,
                ),
            ]
        if command == "shield":
            hero.shield_until = now_epoch + 10
            return [
                self._emit(
                    state, "hero_updated", {**self._hero_payload(hero), "shielded": True}, event
                )
            ]
        if command == "special" and hero.class_name == "cleric":
            target = next(
                (candidate for candidate in state.heroes.values() if candidate.downed), None
            )
            if target:
                target.downed = False
                target.ghost = False
                target.hp = max(1, target.max_hp // 3)
                target.shield_until = now_epoch + 5
                hero.support_done += target.hp
                return [
                    self._emit(state, "hero_updated", self._hero_payload(target), event),
                    self._emit(
                        state,
                        "toast",
                        {"text": f"{target.display_name} returned from ghost form."},
                        event,
                    ),
                ]
        if command == "special" and hero.class_name == "bard":
            for ally in state.heroes.values():
                if ally.joined and not ally.downed:
                    before = ally.hp
                    ally.hp = min(ally.max_hp, ally.hp + 8)
                    hero.support_done += ally.hp - before
        multiplier = 1.0
        if command == "special":
            multiplier = {
                "warrior": 2.0,
                "mage": 2.2,
                "rogue": 2.5,
                "cleric": 1.4,
                "bard": 1.7,
            }.get(hero.class_name or "", 1.5)
        if state.state == SessionState.BOSS and state.enemy.get("mechanic") == "shield_wall":
            multiplier *= 0.5
        if state.enemy.get("mechanic") == "weak_point":
            multiplier *= 1.5
        attack_stat = (
            hero.stats.get("magic", 0) if hero.class_name == "mage" else hero.stats.get("attack", 0)
        )
        damage = max(
            1, int((attack_stat + hero.level * 2) * multiplier) - int(state.enemy.get("defense", 0))
        )
        critical = False
        if (
            hero.class_name == "rogue"
            and self._stable_roll(state, f"{identity}:{action_index}", "crit") <= 4
        ):
            damage = int(damage * 1.5)
            critical = True
        state.enemy["hp"] = max(0, int(state.enemy.get("hp", 0)) - damage)
        hero.damage_dealt += damage
        out = [
            self._emit(
                state,
                "damage",
                {
                    "source": hero.display_name,
                    "target": state.enemy.get("name"),
                    "amount": damage,
                    "enemy_hp": state.enemy["hp"],
                    "action": command,
                    "critical": critical,
                },
                event,
            )
        ]
        reinforcement_damage = min(
            8, sum(int(squad.get("units", 0)) for squad in state.reinforcements) * 2
        )
        if reinforcement_damage and state.enemy.get("hp", 0) > 0:
            state.enemy["hp"] = max(0, int(state.enemy["hp"]) - reinforcement_damage)
            out.append(
                self._emit(
                    state,
                    "damage",
                    {
                        "source": "Visiting reinforcements",
                        "target": state.enemy.get("name"),
                        "amount": reinforcement_damage,
                        "enemy_hp": state.enemy["hp"],
                        "action": "raid_reinforcements",
                    },
                    event,
                )
            )
        if command == "attack":
            state.combo_hits = [hit for hit in state.combo_hits if hit["at"] > now_epoch - 5]
            state.combo_hits.append({"identity": identity, "at": now_epoch})
            distinct = {hit["identity"] for hit in state.combo_hits}
            if len(distinct) >= 3:
                bonus = max(1, damage // 2)
                state.enemy["hp"] = max(0, state.enemy["hp"] - bonus)
                out.append(
                    self._emit(
                        state,
                        "combo",
                        {
                            "participants": len(distinct),
                            "threshold": 3,
                            "bonus_damage": bonus,
                            "enemy_hp": state.enemy["hp"],
                        },
                        event,
                    )
                )
                state.combo_hits.clear()
        if state.state == SessionState.BOSS:
            out.extend(self._boss_phase_if_due(state, event.occurred_at))
            if state.enemy["hp"] <= 0:
                out.extend(
                    self._change(
                        state, SessionState.RECAP, event.occurred_at, "The boss is defeated."
                    )
                )
                out.extend(self._make_recap(state, event.occurred_at))
        state.revision += 1
        return out

    def _enemy_turn_if_due(self, state: GameState, now: datetime) -> list[GameEvent]:
        if not state.enemy or now.timestamp() < float(state.enemy.get("next_attack_at", 0)):
            return []
        targets = sorted(
            (hero for hero in state.heroes.values() if hero.joined and not hero.downed),
            key=lambda h: h.identity_key,
        )
        state.enemy["next_attack_at"] = now.timestamp() + 4
        if not targets:
            return [
                self._emit(
                    state, "combat_tick", {"enemy_turn": "no_active_targets"}, occurred_at=now
                )
            ]
        target = targets[self._stable_roll(state, state.revision, "target") % len(targets)]
        amount = max(1, int(state.enemy.get("attack", 8)) - target.stats.get("defense", 0) // 2)
        if target.shield_until > now.timestamp():
            amount = max(1, amount // 2)
        if state.enemy.get("mechanic") == "aoe_charge":
            targets = [hero for hero in targets if hero.shield_until <= now.timestamp()]
        for victim in targets:
            dealt = amount
            if victim.class_name == "warrior":
                dealt = max(1, int(dealt * 0.8))
            victim.hp = max(0, victim.hp - dealt)
            if victim.hp == 0:
                victim.downed = True
                victim.ghost = True
            state.revision += 1
        return [
            self._emit(
                state,
                "combat_tick",
                {
                    "enemy": state.enemy.get("name"),
                    "targets": [
                        {
                            "name": hero.display_name,
                            "damage": amount,
                            "hp": hero.hp,
                            "downed": hero.downed,
                        }
                        for hero in targets
                    ],
                },
                occurred_at=now,
            )
        ]

    def _begin_scene(self, state: GameState, now: datetime) -> list[GameEvent]:
        state.scene_index += 1
        chosen = (
            self.catalog.scene_by_id(state.preferred_scene_id) if state.preferred_scene_id else None
        )
        state.scene = deepcopy(chosen or self.catalog.scene(state.scene_index))
        state.preferred_scene_id = None
        if state.preferred_scene_flavor:
            state.scene["text"] = state.preferred_scene_flavor
            state.preferred_scene_flavor = None
        state.scene_id = state.scene["id"]
        state.votes.clear()
        self.transition(state, SessionState.VOTE, now)
        return [
            self._emit(
                state,
                "scene_started",
                {
                    "scene_id": state.scene_id,
                    "title": state.scene["title"],
                    "text": state.scene["text"],
                    "options": state.scene["options"],
                },
                occurred_at=now,
            )
        ]

    def _start_combat(self, state: GameState, now: datetime) -> list[GameEvent]:
        self.transition(state, SessionState.COMBAT, now)
        count = sum(hero.joined for hero in state.heroes.values())
        hp = min(500, 90 + count * 12)
        state.enemy = {
            "name": AI_ENEMY_TEMPLATES.get(state.preferred_enemy_id or "", "Cinderling"),
            "hp": hp,
            "max_hp": hp,
            "attack": 8,
            "defense": 2,
            "next_attack_at": now.timestamp() + 4,
            "mechanic": None,
        }
        state.preferred_enemy_id = None
        return [
            self._emit(state, "session_transition", {"state": "COMBAT"}, occurred_at=now),
            self._emit(
                state,
                "combat_tick",
                {
                    "enemy": state.enemy["name"],
                    "enemy_hp": hp,
                    "enemy_max_hp": hp,
                    "active_participants": count,
                },
                occurred_at=now,
            ),
        ]

    def _start_boss(self, state: GameState, now: datetime) -> list[GameEvent]:
        self.transition(state, SessionState.BOSS, now)
        template = (
            self.catalog.boss_by_id(state.preferred_boss_id) if state.preferred_boss_id else None
        ) or self.catalog.boss(state.boss_index)
        state.preferred_boss_id = None
        state.boss_index += 1
        count = sum(hero.joined for hero in state.heroes.values())
        hp = min(1_200, int(template["hp"] * (1 + min(count, 20) * 0.06)))
        state.boss_phase = 1
        state.boss_mechanic_index = 0
        mechanics = list(template["mechanics"])
        if state.preferred_boss_mechanic in BOSS_MECHANICS:
            mechanics[0] = state.preferred_boss_mechanic
        state.preferred_boss_mechanic = None
        mechanic = mechanics[0]
        if mechanic not in BOSS_MECHANICS:
            raise ValueError("Non-allowlisted boss mechanic")
        state.enemy = {
            "name": template["name"],
            "hp": hp,
            "max_hp": hp,
            "attack": 12,
            "defense": template["defense"],
            "mechanic": mechanic,
            "mechanics": mechanics,
            "next_attack_at": now.timestamp() + 4,
            "started_at": now.timestamp(),
        }
        return [
            self._emit(state, "session_transition", {"state": "BOSS"}, occurred_at=now),
            self._emit(
                state,
                "boss_phase",
                {
                    "boss": template["name"],
                    "phase": 1,
                    "mechanic": mechanic,
                    "hp": hp,
                    "max_hp": hp,
                    "active_participants": count,
                },
                occurred_at=now,
            ),
        ]

    def _boss_phase_if_due(self, state: GameState, now: datetime) -> list[GameEvent]:
        if state.state != SessionState.BOSS or not state.enemy:
            return []
        hp_ratio = int(state.enemy.get("hp", 0)) / max(1, int(state.enemy.get("max_hp", 1)))
        target_phase = 3 if hp_ratio <= 0.33 else 2 if hp_ratio <= 0.66 else 1
        if target_phase <= state.boss_phase:
            return []
        mechanics = state.enemy.get("mechanics", [])
        mechanic = mechanics[min(target_phase - 1, len(mechanics) - 1)] if mechanics else "enrage"
        if mechanic not in BOSS_MECHANICS:
            mechanic = "enrage"
        state.boss_phase = target_phase
        state.boss_mechanic_index = target_phase - 1
        state.enemy["mechanic"] = mechanic
        if mechanic == "summon_adds":
            state.enemy["adds"] = int(state.enemy.get("adds", 0)) + 2
            state.enemy["attack"] = int(state.enemy["attack"]) + 2
        elif mechanic == "enrage":
            state.enemy["attack"] = int(state.enemy.get("attack", 12)) + 5
        state.revision += 1
        return [
            self._emit(
                state,
                "boss_phase",
                {
                    "boss": state.enemy["name"],
                    "phase": target_phase,
                    "mechanic": mechanic,
                    "hp": state.enemy["hp"],
                    "max_hp": state.enemy["max_hp"],
                },
                occurred_at=now,
            )
        ]

    def _change(
        self, state: GameState, target: SessionState, now: datetime, narration: str
    ) -> list[GameEvent]:
        self.transition(state, target, now)
        return [
            self._emit(state, "session_transition", {"state": target.value}, occurred_at=now),
            self._emit(state, "narration", {"text": narration}, occurred_at=now),
        ]

    def _pause(self, state: GameState, event: GameEvent, now: datetime) -> list[GameEvent]:
        if not event.payload.get("is_moderator") or state.state not in ACTIVE_STATES:
            return []
        state.resume_state = state.state
        self.transition(state, SessionState.PAUSED, now)
        return [
            self._emit(
                state,
                "paused",
                {"state": "PAUSED", "resume_state": state.resume_state.value},
                event,
            )
        ]

    def _resume(self, state: GameState, event: GameEvent, now: datetime) -> list[GameEvent]:
        if (
            not event.payload.get("is_moderator")
            or state.state != SessionState.PAUSED
            or state.resume_state is None
        ):
            return []
        target, state.resume_state = state.resume_state, None
        self.transition(state, target, now)
        return [self._emit(state, "session_transition", {"state": target.value}, event)]

    def _skip(self, state: GameState, event: GameEvent, now: datetime) -> list[GameEvent]:
        if not event.payload.get("is_moderator"):
            return []
        next_state = {
            SessionState.LOBBY: SessionState.INTRO,
            SessionState.INTRO: SessionState.VOTE,
            SessionState.VOTE: SessionState.COMBAT,
            SessionState.COMBAT: SessionState.PUZZLE,
            SessionState.PUZZLE: SessionState.EVENT,
            SessionState.EVENT: SessionState.BOSS,
            SessionState.BOSS: SessionState.RECAP,
            SessionState.RECAP: SessionState.ENDED,
        }.get(state.state)
        if next_state is None:
            return []
        if next_state == SessionState.VOTE:
            return self._begin_scene(state, now)
        if next_state == SessionState.COMBAT:
            return self._start_combat(state, now)
        if next_state == SessionState.BOSS:
            return self._start_boss(state, now)
        out = self._change(state, next_state, now, "The host advanced the Emberfall chapter.")
        if next_state == SessionState.RECAP:
            out.extend(self._make_recap(state, now))
        return out

    def _opt_out(self, state: GameState, identity: str, event: GameEvent) -> list[GameEvent]:
        hero = state.heroes.pop(identity, None)
        state.opted_out = sorted(set(state.opted_out) | {sha256(identity.encode()).hexdigest()})
        state.votes.pop(identity, None)
        state.revision += 1
        return [
            self._emit(
                state,
                "hero_updated",
                {
                    "opted_out": True,
                    "hero_removed": hero is not None,
                    "simulated": bool(event.payload.get("simulated")),
                },
                event,
            )
        ]

    def _reward_party(
        self, state: GameState, *, xp: int, gold: int, now: datetime
    ) -> list[GameEvent]:
        out = []
        for hero in state.heroes.values():
            if not hero.joined:
                continue
            old_level = hero.level
            hero.xp = min(MAX_XP, hero.xp + max(0, xp))
            hero.gold = min(MAX_GOLD, hero.gold + max(0, gold))
            new_level = level_for_xp(hero.xp)
            if new_level > old_level:
                progression = PROGRESSION.get(hero.class_name or "")
                if progression:
                    for stat, amount in progression.items():
                        hero.stats[stat] = hero.stats.get(stat, 0) + amount * (
                            new_level - old_level
                        )
                    hero.max_hp = hero.stats["max_hp"]
                    hero.hp = min(hero.max_hp, hero.hp + hero.max_hp // 5)
                hero.level = new_level
                hero.title = self._title(new_level)
                unlocks = {5: "emberfall-scout-cloak", 10: "cinder-crown", 20: "lantern-aegis"}
                for threshold, cosmetic in unlocks.items():
                    if old_level < threshold <= new_level and cosmetic not in hero.cosmetics:
                        hero.cosmetics.append(cosmetic)
                state.key_moments.append(f"{hero.display_name} reached level {new_level}")
            out.append(
                self._emit(
                    state,
                    "hero_updated",
                    {
                        **self._hero_payload(hero),
                        "reward_xp": xp,
                        "reward_gold": gold,
                        "level_up": new_level > old_level,
                    },
                    occurred_at=now,
                )
            )
        state.revision += 1
        return out

    def _make_recap(self, state: GameState, now: datetime) -> list[GameEvent]:
        heroes = [hero for hero in state.heroes.values() if hero.joined]
        mvp = {
            "damage": self._top_hero(state, "damage"),
            "support": self._top_hero(state, "support"),
            "votes": self._top_hero(state, "votes"),
        }
        recap = {
            "title": f"The Emberfall Chronicle: {state.scene.get('title', 'A Lantern Road')}",
            "key_moments": state.key_moments[-12:],
            "party_size": len(heroes),
            "mvp_categories": mvp,
            "level_ups": [
                f"{hero.display_name}: {hero.title}" for hero in heroes if hero.level > 1
            ],
            "world_flags": state.world_flags,
            "cliffhanger": "Beyond Emberfall, a second lantern has appeared on the far ridge.",
            "outcome": "victory" if int(state.enemy.get("hp", 1)) <= 0 else "the party regroups",
        }
        state.recap = recap
        state.revision += 1
        return [self._emit(state, "recap", recap, occurred_at=now)]

    def _top_hero(self, state: GameState, _category: str) -> str | None:
        metric = {"damage": "damage_dealt", "support": "support_done", "votes": "votes_cast"}.get(
            _category
        )
        eligible = [hero for hero in state.heroes.values() if hero.joined]
        if not eligible or metric is None:
            return None
        best_score = max(getattr(hero, metric) for hero in eligible)
        tied = sorted(
            hero.display_name
            for hero in eligible
            if getattr(hero, metric) == best_score and best_score > 0
        )
        return tied[0] if tied else None

    def _stable_roll(self, state: GameState, material: Any, purpose: str) -> int:
        digest = sha256(f"{state.seed}:{material}:{purpose}".encode()).digest()
        return int.from_bytes(digest[:4], "big") % 20 + 1

    @staticmethod
    def _identity(event: GameEvent) -> str | None:
        if not event.actor:
            return None
        return event.actor.identity_key or (
            f"twitch:{event.actor.twitch_user_id}" if event.actor.twitch_user_id else None
        )

    @staticmethod
    def _title(level: int) -> str:
        return max(
            (title for threshold, title in TITLES.items() if level >= threshold), default="Wayfarer"
        )

    @staticmethod
    def _hero_payload(hero: HeroState) -> dict[str, Any]:
        return {
            "display_name": hero.display_name,
            "chat_color": hero.chat_color,
            "class_name": hero.class_name,
            "level": hero.level,
            "xp": hero.xp,
            "title": hero.title,
            "hp": hero.hp,
            "max_hp": hero.max_hp,
            "downed": hero.downed,
            "ghost": hero.ghost,
            "gold": hero.gold,
            "stats": hero.stats,
            "cosmetics": hero.cosmetics,
            "passive": {
                "warrior": "20% damage reduction",
                "mage": "magic scales spell damage",
                "rogue": "20% seeded critical chance",
                "cleric": "stronger healing and revive",
                "bard": "double vote weight and party inspiration",
            }.get(hero.class_name or ""),
        }

    def _hero_summary(self, hero: HeroState) -> str:
        return (
            f"{hero.title} {hero.display_name} · {hero.class_name or 'unclassed'} "
            f"· level {hero.level} · {hero.hp}/{hero.max_hp} HP"
        )

    @staticmethod
    def _expire_reinforcements(state: GameState, now_epoch: float) -> None:
        state.reinforcements = [
            squad for squad in state.reinforcements
            if float(squad.get("expires_at", 0)) > now_epoch and int(squad.get("units", 0)) > 0
        ][:MAX_REINFORCEMENT_SQUADS]

    @staticmethod
    def _emit(
        state: GameState,
        event_type: str,
        payload: dict[str, Any],
        source_event: GameEvent | None = None,
        *,
        source: str | None = None,
        occurred_at: datetime | None = None,
    ) -> GameEvent:
        return GameEvent(
            event_id=uuid4(),
            event_type=event_type,
            schema_version=1,
            occurred_at=occurred_at
            or (source_event.occurred_at if source_event else datetime.now(UTC)),
            source=source or (source_event.source if source_event else "simulator"),
            world_id=state.world_id,
            session_id=state.session_id,
            actor=source_event.actor if source_event else None,
            payload=payload,
        )
