import re
import unicodedata
from difflib import SequenceMatcher


def normalize_answer(answer: str) -> str:
    folded = unicodedata.normalize("NFKD", answer).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.casefold()).split())


def answer_matches(answer: str, accepted: list[str], *, threshold: float = 0.90) -> bool:
    if not 0.85 <= threshold <= 1:
        raise ValueError("Puzzle fuzzy-match threshold must be conservative (0.85–1.0)")
    normalized = normalize_answer(answer)
    if not normalized:
        return False
    for candidate in accepted:
        expected = normalize_answer(candidate)
        if normalized == expected:
            return True
        if len(normalized) >= 5 and len(expected) >= 5:
            if SequenceMatcher(None, normalized, expected, autojunk=False).ratio() >= threshold:
                return True
    return False
