"""Will a translated line fit its place in the dub, before anything is voiced?

A line's place is its **window**: from its own start (or up to ``LEAD_S`` earlier, but
never before the previous line has ended) to the next line's start. The mixer
(`app/mix.py` `fit`) places each take in that window and speeds it up freely to
``MAX_STRETCH``, flagged to ``HARD_STRETCH``; beyond that it overflows into the next line.

``need`` = predicted spoken length / window length: the speed-up the line would need.
A line is **tight** when even ``HARD_STRETCH`` cannot make it fit without overlapping a
neighbour (the owner's rule, 2026-09-30); only tight lines are shortened
(`worker/lb_worker/shorten.py`, decision 47). Neighbours are taken at their source
times, so one line's verdict never depends on how another was voiced.
"""
from __future__ import annotations

import math

from .length import default_rate, syllables

GAP_S = 0.08         # silence kept between consecutive dubbed lines
LEAD_S = 0.3         # how far a long line may start before the original onset
MAX_STRETCH = 1.12   # speed-up applied freely by the mixer
HARD_STRETCH = 1.25  # the most the mixer squeezes; beyond it a take overflows
MIN_SIM = 0.75       # a shortened version must keep at least this much of the meaning

# Native speech + Seed-VC (decision 46) speaks at this rate (syllables/s, spikes/voice_paths
# on the camille clip, 2026-09-30: native voices 6.02, edge-tts 5.99); used until takes of a
# project give a measured rate.
NATIVE_RATE = {"am": 6.0}


def rate_for(lang: str, measured: float | None = None) -> float:
    return measured or NATIVE_RATE.get(lang) or default_rate(lang)


def window(lines: list[dict], i: int, total_s: float | None = None) -> tuple[float, float]:
    """(lo, hi) seconds a line's take may occupy; ``lines`` in time order."""
    s = lines[i]
    lo = s["start"] - LEAD_S
    if i:
        lo = max(lo, lines[i - 1]["end"] + GAP_S)
    lo = max(0.0, lo)
    hi = lines[i + 1]["start"] - GAP_S if i + 1 < len(lines) else (total_s or s["end"])
    return lo, max(lo + 0.05, hi)


def predict_s(text: str, lang: str, rate: float) -> float:
    return syllables(text, lang) / rate if rate else 0.0


def need(text: str, lang: str, rate: float, win: tuple[float, float]) -> float:
    return round(predict_s(text, lang, rate) / (win[1] - win[0]), 3)


def is_tight(n: float | None) -> bool:
    return n is not None and n > HARD_STRETCH


def of_lines(lines: list[dict], lang: str, rate: float, total_s: float | None = None,
             key: str = "tr") -> list[dict | None]:
    """{need, tight} per line (None where there is no text), lines in time order."""
    out: list[dict | None] = []
    for i, s in enumerate(lines):
        if not s.get(key):
            out.append(None)
            continue
        n = need(s[key], lang, rate, window(lines, i, total_s))
        out.append({"need": n, "tight": is_tight(n)})
    return out


def word_caps(words: int, n: float) -> tuple[int, int]:
    """Word limits for two shorter English versions of a line that needs ``n``: one aimed
    just inside the free speed-up, one with a safety margin. The model's counts are
    never trusted; the results are measured."""
    a = max(3, math.floor(words * 1.10 / n))
    b = max(2, min(a - 1, math.floor(words * 0.90 / n)))
    return a, b


def choose(cands: list[dict], min_sim: float = MIN_SIM) -> tuple[dict, str]:
    """Pick among candidates ``{kind, text, need, sim}`` (Google's own has sim 1.0):
    the most faithful one that fits freely; else the shortest faithful one the mixer
    can still squeeze; else Google's original. Returns (candidate, status) with status
    fits | closer | too_long."""
    ok = [c for c in cands if (c.get("sim") or 0) >= min_sim and c.get("text")]
    free = [c for c in ok if c["need"] <= MAX_STRETCH]
    if free:
        return max(free, key=lambda c: (c["sim"], -c["need"])), "fits"
    hard = [c for c in ok if c["need"] <= HARD_STRETCH]
    if hard:
        return min(hard, key=lambda c: c["need"]), "closer"
    orig = next((c for c in cands if c["kind"] == "google"), cands[0])
    return orig, "too_long"
