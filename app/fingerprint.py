"""Audio fingerprints for finding parts that repeat across a series (intros, openers,
outros, jingles, sign-offs).

ffmpeg's built-in Chromaprint muxer turns audio into ~8 frames per second, each a
32-bit integer describing the chroma (pitch-class) pattern of ~0.12 s of sound. The
same recording gives nearly the same integers wherever it appears, even re-encoded;
unrelated sound differs in about half the bits. Two searches use that:

- ``find_part``: slide a known part over a source and report the offsets where the
  mean number of differing bits is low (a recurring clip → its occurrences).
- ``shared_runs``: find long stretches two sources have in common without knowing
  them in advance (Jellyfin Intro Skipper's method: exact-value matches vote for a
  time shift between the two, then each likely shift is checked frame by frame).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

FRAME_S = 4096 / 3 / 11025  # ≈0.1238 s between Chromaprint items (algorithm 1, 11025 Hz)
# Item i describes the sound from i·FRAME_S for ~2.6 s (a file of T seconds gives about
# T/FRAME_S − 21 items). Items still match across a boundary for ~SPAN frames before the
# following sound pulls them apart (measured on synthetic chords: 17–18 frames). So a
# part's searchable items stop SPAN before its end, and a found run's end is extended by it.
SPAN = 18
HEAD = 4                    # items starting up to ~4 frames before a shared stretch already match it
TAIL = 12                   # a found run's last clean item ends ~12 frames before the stretch does
MIN_PART_FRAMES = 16        # ⇒ a part must be ≳ 4 s long to be searched for
PART_BITS = 9.0             # mean differing bits (of 32) for a part to count as found
RUN_BITS = 10.0             # smoothed per-frame differing bits inside a shared run
TRIM_BITS = 5.0             # a run's edge frames (3-frame mean) must match this closely


def compute(audio: str | Path) -> np.ndarray:
    """The Chromaprint frames of an audio or video file (raw uint32)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-vn", "-ac", "1",
                        "-f", "chromaprint", "-fp_format", "raw", "-"], capture_output=True)
    if p.returncode:
        raise RuntimeError(f"ffmpeg chromaprint failed: {p.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype="<u4").copy()


def cached(audio: Path, cache: Path) -> np.ndarray:
    """``compute`` once per audio file; recomputed when the audio is newer."""
    if cache.exists() and cache.stat().st_mtime >= audio.stat().st_mtime:
        return np.load(cache)
    fp = compute(audio)
    np.save(cache, fp)
    return fp


def to_frames(t: float) -> int:
    return int(round(t / FRAME_S))


def to_seconds(i: int | float) -> float:
    return round(float(i) * FRAME_S, 2)


def part_frames(fp: np.ndarray, start: float, end: float) -> tuple[int, np.ndarray]:
    """The items that describe only sound inside [start, end): (first index, items).
    Raises ValueError when the span is too short to search for."""
    a, b = to_frames(start), min(len(fp), to_frames(end) - SPAN)
    if b - a < MIN_PART_FRAMES:
        raise ValueError(f"too short to search for: needs about {to_seconds(MIN_PART_FRAMES + SPAN):.0f} s or more")
    return a, fp[a:b]


def _bits(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.bitwise_count(np.bitwise_xor(a, b))


def find_part(part: np.ndarray, src: np.ndarray, max_bits: float = PART_BITS,
              skip: tuple[int, int] | None = None) -> list[tuple[int, float]]:
    """Where ``part`` occurs in ``src``: [(start frame, mean differing bits)], best
    first, non-overlapping. ``skip`` is a frame range not to report (the part's own
    place when searching its own source)."""
    m = len(part)
    if m == 0 or len(src) < m:
        return []
    n = len(src) - m + 1
    score = np.empty(n, dtype=np.float32)
    step = max(1, 4_000_000 // m)  # bound the window matrix to a few MB
    for i in range(0, n, step):
        win = np.lib.stride_tricks.sliding_window_view(src[i:i + step + m - 1], m)
        score[i:i + len(win)] = _bits(win, part).mean(axis=1)
    out: list[tuple[int, float]] = []
    taken = np.zeros(n, dtype=bool)
    if skip is not None:
        taken[max(0, skip[0] - m + 1):max(0, skip[1])] = True
    for i in np.argsort(score, kind="stable"):
        if score[i] > max_bits:
            break
        if taken[i]:
            continue
        out.append((int(i), round(float(score[i]), 2)))
        taken[max(0, i - m + 1):i + m] = True  # no overlapping second report
    return out


def shared_runs(a: np.ndarray, b: np.ndarray, min_s: float = 8.0, max_bits: float = RUN_BITS,
                gap: int = 6, shifts: int = 8) -> list[dict]:
    """Long stretches of the same sound in ``a`` and ``b``:
    [{a_start, a_end, b_start, b_end, score}] in seconds, longest first."""
    if len(a) == 0 or len(b) == 0:
        return []
    index: dict[int, list[int]] = {}
    for i, v in enumerate(a.tolist()):
        index.setdefault(v, []).append(i)
    # Silence and steady tones repeat one value many times; they would vote for every
    # shift at once (and cost quadratic time), so they do not vote.
    index = {v: p for v, p in index.items() if len(p) <= 20}
    votes = np.zeros(len(a) + len(b), dtype=np.int32)  # shift = i_a - i_b + len(b)
    for j, v in enumerate(b.tolist()):
        for i in index.get(v, ()):
            votes[i - j + len(b)] += 1
    if not votes.any():
        return []
    smooth = np.convolve(votes, np.ones(5, dtype=np.int32), mode="same")  # near-equal shifts vote together
    cands: list[int] = []
    for s in np.argsort(-smooth, kind="stable"):
        if smooth[s] < 3 or len(cands) >= shifts:
            break
        if all(abs(int(s) - c) > 4 for c in cands):
            cands.append(int(s))

    min_len = to_frames(min_s)
    found: list[dict] = []
    # The vote peak can be a frame off the true alignment (the two sources' items need
    # not start at the same instant), so each candidate's neighbours are tried too and
    # the best-matching alignment of each stretch wins.
    for s in sorted({x + d for x in cands for d in range(-2, 3)}):
        shift = s - len(b)  # frame i in a lines up with frame i - shift in b
        lo, hi = max(0, shift), min(len(a), len(b) + shift)
        if hi - lo < min_len:
            continue
        bits = _bits(a[lo:hi], b[lo - shift:hi - shift]).astype(np.float32)
        ok = np.convolve(bits, np.ones(5) / 5, mode="same") <= max_bits
        edge = np.convolve(bits, np.ones(3) / 3, mode="same")
        for r0, r1 in _runs(ok, gap):
            while r0 < r1 and edge[r0] > TRIM_BITS:  # smoothing blurs the edges: keep the clean frames
                r0 += 1
            while r1 > r0 and edge[r1 - 1] > TRIM_BITS:
                r1 -= 1
            if r1 - r0 + TAIL < min_len:
                continue
            end = r1 - 1 + TAIL  # the last clean item still describes TAIL frames of shared sound
            r0 = min(r0 + HEAD, end)  # and the first clean items begin a little before it
            found.append({"a_start": to_seconds(lo + r0), "a_end": to_seconds(lo + end), "b_start": to_seconds(lo + r0 - shift),
                          "b_end": to_seconds(lo + end - shift), "score": round(float(bits[r0:r1].mean()), 2)})
    runs: list[dict] = []
    for run in sorted(found, key=lambda r: r["score"]):
        if not any(_overlap(run, x) for x in runs):
            runs.append(run)
    return sorted(runs, key=lambda r: r["a_start"] - r["a_end"])


def _runs(ok: np.ndarray, gap: int) -> list[tuple[int, int]]:
    """[start, end) of True stretches, bridging False gaps up to ``gap`` frames."""
    out: list[list[int]] = []
    for i in np.flatnonzero(ok):
        if out and i - out[-1][1] <= gap:
            out[-1][1] = int(i) + 1
        else:
            out.append([int(i), int(i) + 1])
    return [(x, y) for x, y in out]


def _overlap(r: dict, s: dict) -> bool:
    return min(r["a_end"], s["a_end"]) > max(r["a_start"], s["a_start"]) and \
        min(r["b_end"], s["b_end"]) > max(r["b_start"], s["b_start"])
