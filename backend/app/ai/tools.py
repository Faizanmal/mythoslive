from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartVoteSceneArgs(StrictToolArgs):
    template_id: str = Field(min_length=1, max_length=64)
    flavor_text: str = Field(min_length=20, max_length=320)


class StartCombatArgs(StrictToolArgs):
    enemy_template_id: Literal["cinderling", "ash_wisp", "ember_wolf"]


class SpawnBossArgs(StrictToolArgs):
    template_id: str = Field(min_length=1, max_length=64)
    mechanic: Literal["shield_wall", "aoe_charge", "summon_adds", "weak_point", "enrage"] | None


class StartPuzzleArgs(StrictToolArgs):
    riddle_template_id: str = Field(min_length=1, max_length=64)


class GrantRewardArgs(StrictToolArgs):
    reward_tier: Literal["participation", "milestone"]
    justification: str = Field(min_length=5, max_length=100)


class ApplyWorldFlagArgs(StrictToolArgs):
    flag_id: Literal[
        "lantern_festival",
        "market_open",
        "village_trusts_party",
        "ashfall_cleared",
        "river_crossed",
    ]


class ProposeWorldEventArgs(StrictToolArgs):
    event_id: Literal["lantern_festival", "traveling_cart", "ashfall_clears"]
    description: str = Field(min_length=10, max_length=180)


class RememberFactArgs(StrictToolArgs):
    fact: str = Field(min_length=12, max_length=220)
    kind: Literal["world_fact", "npc", "location", "quest"]
    importance: float = Field(ge=0.1, le=0.8, allow_inf_nan=False)


class NarrateArgs(StrictToolArgs):
    text: str = Field(min_length=1, max_length=350)


class EndSessionArgs(StrictToolArgs):
    closing_style: Literal["triumphant", "tender", "mysterious"]
    closing_line: str = Field(min_length=10, max_length=220)


TOOL_MODELS: dict[str, type[StrictToolArgs]] = {
    "start_vote_scene": StartVoteSceneArgs,
    "start_combat": StartCombatArgs,
    "spawn_boss": SpawnBossArgs,
    "start_puzzle": StartPuzzleArgs,
    "grant_reward": GrantRewardArgs,
    "apply_world_flag": ApplyWorldFlagArgs,
    "propose_world_event": ProposeWorldEventArgs,
    "remember_fact": RememberFactArgs,
    "narrate": NarrateArgs,
    "end_session": EndSessionArgs,
}


def openai_tools() -> list[dict[str, object]]:
    result = []
    for name, model in TOOL_MODELS.items():
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": _TOOL_DESCRIPTIONS[name],
                    "strict": True,
                    "parameters": model.model_json_schema(),
                },
            }
        )
    return result


_TOOL_DESCRIPTIONS = {
    "start_vote_scene": (
        "Choose a local scene template and add one moderated flavor paragraph; "
        "choices stay from that template."
    ),
    "start_combat": (
        "Choose the name and flavor for the next local enemy; "
        "deterministic combat math remains unchanged."
    ),
    "spawn_boss": (
        "Choose a local boss template and only an allowlisted mechanic for the upcoming boss."
    ),
    "start_puzzle": "Choose one existing local riddle by its template ID.",
    "grant_reward": (
        "Request a fixed engine reward tier. The engine may reject it; "
        "never supply amounts or targets."
    ),
    "apply_world_flag": (
        "Propose an allowlisted canonical world flag; streamer approval may be required."
    ),
    "propose_world_event": "Propose one predefined, approval-gated world event.",
    "remember_fact": "Remember a short, non-personal Emberfall world-canon fact only.",
    "narrate": "Emit one moderated, family-friendly narration line for the stream.",
    "end_session": (
        "Suggest a closing line. The deterministic engine controls whether a session can end."
    ),
}
