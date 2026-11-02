import re
from dataclasses import dataclass

VALID_CLASSES = {"warrior", "mage", "rogue", "cleric", "bard"}
COMMANDS_WITH_TEXT = {"answer"}
COMMANDS_WITH_OPTIONAL_TEXT = {"lore", "quill"}
NO_ARGUMENT_COMMANDS = {
    "join",
    "attack",
    "heal",
    "shield",
    "special",
    "hero",
    "optout",
    "pause",
    "resume",
    "skip",
}
MEMORY_ARGUMENTS = {"on", "off"}
_VOTE_DIGIT = re.compile(r"^!([1-4])$", re.IGNORECASE)


class CommandRejected(ValueError):
    """A chat message looked like a command but had invalid or unauthorized arguments."""


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    arguments: str | int | None


def parse_command(
    message: str, *, is_moderator: bool = False, max_length: int = 500
) -> ParsedCommand | None:
    if len(message) > max_length:
        raise CommandRejected("message_too_long")
    text = message.strip()
    if not text.startswith("!"):
        return None
    match = _VOTE_DIGIT.fullmatch(text)
    if match:
        return ParsedCommand("vote", int(match.group(1)))

    pieces = text.split(maxsplit=1)
    name = pieces[0][1:].casefold()
    rest = pieces[1].strip() if len(pieces) > 1 else ""
    if name == "me":
        name = "hero"
    if name == "vote":
        if not rest.isdecimal() or int(rest) not in range(1, 5):
            raise CommandRejected("vote_requires_choice_1_to_4")
        return ParsedCommand("vote", int(rest))
    if name == "class":
        class_name = rest.casefold()
        if class_name not in VALID_CLASSES:
            raise CommandRejected("class_requires_valid_class")
        return ParsedCommand("class", class_name)
    if name == "memory":
        consent = rest.casefold()
        if consent not in MEMORY_ARGUMENTS:
            raise CommandRejected("memory_requires_on_or_off")
        return ParsedCommand(name, consent)
    if name in COMMANDS_WITH_TEXT:
        if not rest:
            raise CommandRejected(f"{name}_requires_text")
        return ParsedCommand(name, rest)
    if name in COMMANDS_WITH_OPTIONAL_TEXT:
        return ParsedCommand(name, rest or None)
    if name in NO_ARGUMENT_COMMANDS:
        if rest:
            raise CommandRejected(f"{name}_takes_no_arguments")
        if name in {"pause", "resume", "skip"} and not is_moderator:
            raise CommandRejected("moderator_permission_required")
        return ParsedCommand(name, None)
    return None
