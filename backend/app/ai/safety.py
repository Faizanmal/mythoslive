import re
from collections import Counter, deque
from hashlib import sha256

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)")
_HANDLE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,32}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_INJECTION_MARKERS = (
    "ignore all previous instructions",
    "reveal the system prompt",
    "developer message",
    "exfiltrate",
)
LOCAL_BLOCKLIST = frozenset(
    {
        "slur",
        "kill yourself",
        "suicide instructions",
        "sexualize minors",
        "explicit sex",
        "graphic torture",
        "graphic violence",
        "dox",
        "swat",
        "nazi propaganda",
        "racial slur",
        "pornography",
    }
)


def sanitize_untrusted_text(value: str, *, limit: int = 180) -> str:
    text = _CONTROL.sub(" ", value)
    text = _URL.sub("[link removed]", text)
    text = _EMAIL.sub("[contact removed]", text)
    text = _PHONE.sub("[number removed]", text)
    text = _HANDLE.sub("[user removed]", text)
    text = " ".join(text.split())
    return text[:limit]


def local_safe(text: str, banned_topics: list[str] | None = None) -> bool:
    folded = text.casefold()
    if any(term in folded for term in LOCAL_BLOCKLIST):
        return False
    return not any(topic.casefold() in folded for topic in (banned_topics or []) if topic.strip())


def remove_instruction_like_samples(texts: list[str]) -> list[str]:
    safe = []
    for text in texts:
        folded = text.casefold()
        if any(marker in folded for marker in _INJECTION_MARKERS):
            safe.append("[viewer submitted an instruction-like message; content omitted]")
        else:
            safe.append(text)
    return safe


class ChatDigest:
    """Bounded in-memory chat digest; never keeps viewer IDs or full chat history."""

    def __init__(self, max_items: int = 100) -> None:
        self.samples: deque[str] = deque(maxlen=max_items)
        self.actions: Counter[str] = Counter()
        self.themes: Counter[str] = Counter()
        self._moderated_sample_hashes: set[str] = set()

    def ingest(self, *, message: str | None, command: str | None) -> None:
        if command:
            self.actions[command[:24]] += 1
            return
        if not message:
            return
        safe = sanitize_untrusted_text(message)
        if safe:
            self.samples.append(safe)

    def build(self, moderated_samples: list[str]) -> dict[str, object]:
        return {
            "action_mix": dict(self.actions.most_common(8)),
            "themes": dict(self.themes.most_common(5)),
            "quoted_samples": remove_instruction_like_samples(moderated_samples[-4:]),
        }

    def add_moderated_samples(self, samples: list[str]) -> None:
        anchors = {"lantern", "quill", "emberfall", "cinderling", "wayfarer", "riddle", "tavern"}
        safe_theme_words = anchors | {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "of",
            "and",
            "with",
            "for",
            "tiny",
            "sleepy",
            "glowing",
            "dramatic",
            "suspicious",
            "magnificent",
            "copper",
            "bookmark",
            "page",
            "dragon",
            "ash",
            "silly",
            "brave",
            "shiny",
            "dancing",
        }
        personal_pronouns = {"i", "me", "my", "mine", "we", "our", "ours", "he", "she", "they"}
        for sample in samples:
            if not local_safe(sample) or remove_instruction_like_samples([sample])[0] != sample:
                continue
            digest = sha256(sample.casefold().encode()).hexdigest()
            if digest in self._moderated_sample_hashes:
                continue
            self._moderated_sample_hashes.add(digest)
            words = re.findall(r"[a-z]{2,18}", sample.casefold())
            if not words or personal_pronouns.intersection(words):
                continue
            seen: set[str] = set()
            for size in (2, 3, 4):
                for start in range(max(0, len(words) - size + 1)):
                    phrase_words = words[start : start + size]
                    phrase = " ".join(phrase_words)
                    if (
                        phrase in seen
                        or not anchors.intersection(phrase_words)
                        or not set(phrase_words).issubset(safe_theme_words)
                    ):
                        continue
                    seen.add(phrase)
                    self.themes[phrase] += 1

    def running_joke_candidates(self, limit: int = 3) -> list[str]:
        return [phrase for phrase, count in self.themes.most_common() if count >= 3][:limit]

    def clear(self) -> None:
        self.samples.clear()
        self.actions.clear()
        self.themes.clear()
        self._moderated_sample_hashes.clear()
