"""Self-contained CTC forced-alignment core, vendored from whisperX `alignment.py`.

These are whisperX's *current* DP functions (BSD-2-Clause, C. Max Bain), reproduced
verbatim so our alignment matches whisperX bit-for-bit: `get_trellis` builds the
probability trellis, `backtrack` finds the optimal path (returning None on failure),
`merge_repeats` collapses it into per-character segments, `merge_words` groups characters
into words. Plus `interpolate_nans`, a pandas-free port of whisperX's gap filler for words
that had no alignable characters.

`torch` is imported lazily so importing this module stays cheap.
Source: https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py
and pytorch.org forced_alignment_with_torchaudio_tutorial.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Point:
    token_index: int
    time_index: int
    score: float


@dataclass
class Segment:
    label: str
    start: int
    end: int
    score: float

    @property
    def length(self) -> int:
        return self.end - self.start


def get_trellis(emission, tokens, blank_id: int = 0):
    import torch

    num_frame = emission.size(0)
    num_tokens = len(tokens)

    trellis = torch.empty((num_frame + 1, num_tokens + 1))
    trellis[0, 0] = 0
    trellis[1:, 0] = torch.cumsum(emission[:, blank_id], 0)
    trellis[0, -num_tokens:] = -float("inf")
    trellis[-num_tokens:, 0] = float("inf")

    for t in range(num_frame):
        trellis[t + 1, 1:] = torch.maximum(
            # stay at the same token (emit blank)
            trellis[t, 1:] + emission[t, blank_id],
            # advance to the next token
            trellis[t, :-1] + emission[t, tokens],
        )
    return trellis


def backtrack(trellis, emission, tokens, blank_id: int = 0):
    import torch

    j = trellis.size(1) - 1
    t_start = torch.argmax(trellis[:, j]).item()

    path = []
    for t in range(t_start, 0, -1):
        stayed = trellis[t - 1, j] + emission[t - 1, blank_id]
        changed = trellis[t - 1, j - 1] + emission[t - 1, tokens[j - 1]]

        prob = emission[t - 1, tokens[j - 1] if changed > stayed else blank_id].exp().item()
        path.append(Point(j - 1, t - 1, prob))

        if changed > stayed:
            j -= 1
            if j == 0:
                break
    else:
        return None  # alignment failed

    return path[::-1]


def merge_repeats(path, transcript):
    i1, i2 = 0, 0
    segments = []
    while i1 < len(path):
        while i2 < len(path) and path[i1].token_index == path[i2].token_index:
            i2 += 1
        score = sum(path[k].score for k in range(i1, i2)) / (i2 - i1)
        segments.append(Segment(transcript[path[i1].token_index], path[i1].time_index, path[i2 - 1].time_index + 1, score))
        i1 = i2
    return segments


def merge_words(segments, separator: str = "|"):
    words = []
    i1, i2 = 0, 0
    while i1 < len(segments):
        if i2 >= len(segments) or segments[i2].label == separator:
            if i1 != i2:
                segs = segments[i1:i2]
                word = "".join(s.label for s in segs)
                length = sum(s.length for s in segs) or 1
                score = sum(s.score * s.length for s in segs) / length
                words.append(Segment(word, segments[i1].start, segments[i2 - 1].end, score))
            i1 = i2 + 1
            i2 = i1
        else:
            i2 += 1
    return words


def interpolate_nans(values: list, method: str = "nearest") -> list:
    """Fill None entries in a list of floats (pandas-free port of whisperX's gap filler).

    `nearest` copies the closest known value; `linear` interpolates between the
    surrounding known values (ends filled with the nearest known); `ignore` leaves Nones.
    """
    if method == "ignore":
        return list(values)
    known = [(i, v) for i, v in enumerate(values) if v is not None]
    if not known:
        return list(values)

    out = list(values)
    for i, v in enumerate(out):
        if v is not None:
            continue
        # nearest known index on each side
        left = max((k for k in known if k[0] < i), default=None, key=lambda kv: kv[0])
        right = min((k for k in known if k[0] > i), default=None, key=lambda kv: kv[0])
        if method == "linear" and left and right:
            (li, lv), (ri, rv) = left, right
            out[i] = lv + (rv - lv) * (i - li) / (ri - li)
        else:  # nearest (and linear at the edges)
            cands = [c for c in (left, right) if c]
            out[i] = min(cands, key=lambda kv: abs(kv[0] - i))[1]
    return out
