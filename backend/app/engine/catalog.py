import json
from pathlib import Path
from typing import Any

CONTENT_PATH = Path(__file__).parent / "content" / "emberfall.json"
ALLOWED_BOSS_MECHANICS = frozenset(
    {"shield_wall", "aoe_charge", "summon_adds", "weak_point", "enrage"}
)


class ContentCatalog:
    def __init__(self, content: dict[str, Any] | None = None) -> None:
        self.data = content if content is not None else json.loads(CONTENT_PATH.read_text("utf-8"))
        if len(self.data.get("scenes", [])) < 20:
            raise ValueError("Emberfall requires at least 20 scenes")
        if len(self.data.get("bosses", [])) < 6:
            raise ValueError("Emberfall requires at least 6 boss templates")
        if len(self.data.get("riddles", [])) < 15:
            raise ValueError("Emberfall requires at least 15 riddles")
        if any(set(boss["mechanics"]) - ALLOWED_BOSS_MECHANICS for boss in self.data["bosses"]):
            raise ValueError("Boss template contains a non-allowlisted mechanic")

    def scene(self, index: int) -> dict[str, Any]:
        scenes = self.data["scenes"]
        return scenes[index % len(scenes)]

    def scene_by_id(self, template_id: str) -> dict[str, Any] | None:
        return next((scene for scene in self.data["scenes"] if scene["id"] == template_id), None)

    def boss(self, index: int) -> dict[str, Any]:
        bosses = self.data["bosses"]
        return bosses[index % len(bosses)]

    def boss_by_id(self, template_id: str) -> dict[str, Any] | None:
        return next((boss for boss in self.data["bosses"] if boss["id"] == template_id), None)

    def riddle(self, index: int) -> dict[str, Any]:
        riddles = self.data["riddles"]
        return riddles[index % len(riddles)]

    def riddle_by_id(self, template_id: str) -> dict[str, Any] | None:
        return next(
            (riddle for riddle in self.data["riddles"] if riddle["id"] == template_id), None
        )
