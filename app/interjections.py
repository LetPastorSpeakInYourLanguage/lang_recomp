"""Which lines can stay in the original language.

Short interjections ("wow", "ehm", "yeah", "oh nice", "okay") read as natural in any
language, and a dubbed "ዋው" often sounds worse than the speaker's own. A line is
suggested for keeping when it is short and made only of words from the keep-list
(editable in Settings). The suggestion is computed on read, so it applies to every
project retroactively; an explicit per-line choice always wins.
"""
from __future__ import annotations

import re

from . import settings

DEFAULT_KEEP_WORDS = [
    "wow", "whoa", "oh", "ooh", "ah", "aah", "aw", "aww", "eh", "ehm", "em", "erm", "um", "umm", "uh", "uhh",
    "uh-huh", "uhhuh", "mhm", "mm", "mmm", "hmm", "huh", "yeah", "yea", "yep", "yup", "ok", "okay", "nice",
    "cool", "haha", "ha", "hah", "oops", "hey", "alright",
]
MAX_WORDS = 3
MAX_SLOT_S = 1.5


def keep_words() -> set[str]:
    words = settings.load().get("keep_words")
    return {w.strip().lower() for w in (words if isinstance(words, list) else DEFAULT_KEEP_WORDS) if w.strip()}


def suggest_keep(text: str, slot_s: float, words: set[str] | None = None) -> bool:
    tokens = [t for t in re.split(r"[^\w'-]+", text.lower()) if t]
    if not tokens or len(tokens) > MAX_WORDS or slot_s > MAX_SLOT_S:
        return False
    words = keep_words() if words is None else words
    return all(t.strip("'-") in words or t in words for t in tokens)


def effective_mode(mode: str | None, text: str, slot_s: float, words: set[str] | None = None) -> str:
    if mode in ("dub", "keep"):
        return mode
    return "keep" if suggest_keep(text, slot_s, words) else "dub"
