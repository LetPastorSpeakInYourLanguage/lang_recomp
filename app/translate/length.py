"""How long a line will take to say, per script, for the dubbing length budget.

Counts spoken syllables cheaply, without a phonemizer:
- Ethiopic (Amharic, Tigrinya, ...): one fidel is one consonant+vowel syllable.
- Alphabets (Latin, Cyrillic, Greek): vowel groups, the English heuristic.
- CJK: one character is one syllable; Hangul: one block is one syllable.
- Anything else: characters / 2.5, a rough fallback.

The speaking rate starts from a per-script default and is replaced by the rate
measured from chosen takes of that language (`voice.calibrate_rate`).
"""
from __future__ import annotations

import re

from ..langs import script as lang_script

_ETHIOPIC = [(0x1200, 0x137F), (0x1380, 0x139F), (0x2D80, 0x2DDF), (0xAB00, 0xAB2F)]
_ETH_PUNCT = (0x1360, 0x137C)  # ፠ ፡ ። ፣ ... and Ethiopic numerals
DEFAULT_RATE = {"ethiopic": 5.5, "latin": 5.0, "cyrillic": 5.0, "cjk": 6.0, "hangul": 6.0, None: 5.0}


def _is_fidel(ch: str) -> bool:
    o = ord(ch)
    return not (_ETH_PUNCT[0] <= o <= _ETH_PUNCT[1]) and any(a <= o <= b for a, b in _ETHIOPIC)


def detect_script(text: str) -> str | None:
    counts = {"ethiopic": 0, "latin": 0, "cyrillic": 0, "cjk": 0, "hangul": 0}
    for ch in text:
        o = ord(ch)
        if _is_fidel(ch):
            counts["ethiopic"] += 1
        elif ch.isascii() and ch.isalpha() or 0x00C0 <= o <= 0x024F:
            counts["latin"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["cyrillic"] += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3040 <= o <= 0x30FF:
            counts["cjk"] += 1
        elif 0xAC00 <= o <= 0xD7AF:
            counts["hangul"] += 1
    best = max(counts, key=counts.get)
    return best if counts[best] else None


def syllables(text: str, lang: str | None = None) -> int:
    sc = (lang_script(lang) if lang else None) or detect_script(text)
    numbers = len(re.findall(r"\d+", text)) * 2
    if sc == "ethiopic":
        return sum(1 for ch in text if _is_fidel(ch)) + numbers
    if sc in ("latin", "cyrillic"):
        n = 0
        for w in re.findall(r"[^\W\d_]+", text.lower()):
            groups = len(re.findall(r"[aeiouyаеёиоуыэюяáéíóúàèìòùâêîôûäëïöü]+", w))
            if w.endswith("e") and groups > 1 and not w.endswith(("le", "ee")):
                groups -= 1
            n += max(1, groups)
        return n + numbers
    if sc in ("cjk", "hangul"):
        return sum(1 for ch in text if ch.isalpha()) + numbers
    return round(sum(1 for ch in text if ch.isalnum()) / 2.5) + numbers


def default_rate(lang: str | None) -> float:
    return DEFAULT_RATE.get(lang_script(lang) if lang else None, 5.0)


def budget(text: str, slot_s: float, rate: float | None = None, lang: str | None = None) -> dict:
    """How a translated line fits its source time slot. ratio > 1 means too long."""
    rate = rate or default_rate(lang)
    syl = syllables(text, lang)
    est = syl / rate if rate else 0.0
    return {"syllables": syl, "est_s": round(est, 2), "slot_s": round(slot_s, 2),
            "ratio": round(est / slot_s, 2) if slot_s > 0 else None,
            "max_syllables": int(slot_s * rate), "rate": rate}
