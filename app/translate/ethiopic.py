"""Length estimates for the dubbing budget.

Ethiopic script is an abugida: each fidel is a consonant+vowel syllable (or a bare
consonant in sixth-order form), so counting fidels is a cheap, script-native
syllable estimate for Amharic — no phonemizer needed.
"""
from __future__ import annotations

import re

_ETHIOPIC = [(0x1200, 0x137F), (0x1380, 0x139F), (0x2D80, 0x2DDF), (0xAB00, 0xAB2F)]
_PUNCT_NUM = (0x1360, 0x137C)  # ፠ ፡ ። ፣ ፤ ፥ ፦ ፧ ፨ and Ethiopic numerals

# Starting point only; the voice stage measures real rates per character and replaces it.
AM_SYL_PER_S = 5.5


def is_fidel(ch: str) -> bool:
    o = ord(ch)
    if _PUNCT_NUM[0] <= o <= _PUNCT_NUM[1]:
        return False
    return any(a <= o <= b for a, b in _ETHIOPIC)


def am_syllables(text: str) -> int:
    return sum(1 for ch in text if is_fidel(ch)) + len(re.findall(r"\d+", text)) * 2


def en_syllables(text: str) -> int:
    """Vowel-group heuristic; good enough to compare against the source duration."""
    n = 0
    for w in re.findall(r"[A-Za-z']+", text.lower()):
        groups = len(re.findall(r"[aeiouy]+", w))
        if w.endswith("e") and groups > 1 and not w.endswith(("le", "ee")):
            groups -= 1
        n += max(1, groups)
    return n


def budget(text_am: str, slot_s: float, rate: float = AM_SYL_PER_S) -> dict:
    """How the Amharic line fits its source time slot. ratio > 1 means too long."""
    syl = am_syllables(text_am)
    est = syl / rate if rate else 0.0
    return {"syllables": syl, "est_s": round(est, 2), "slot_s": round(slot_s, 2),
            "ratio": round(est / slot_s, 2) if slot_s > 0 else None,
            "max_syllables": int(slot_s * rate)}
