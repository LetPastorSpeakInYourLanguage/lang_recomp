"""Subtitles and captions as a transcript: SRT/VTT → the same document Whisper produces.

A person may already have subtitles (their own, or YouTube's): they can stand in for
transcription. ``to_doc`` turns them into ``{"segments": [{start, end, text, words}]}``,
so everything after transcription (alignment, speakers, lines) treats them alike.

- Manual subtitles give text per cue; each word's time is spread over its cue by its
  length (a first guess that forced alignment can then correct).
- YouTube's automatic captions carry a time for every word (``<00:00:01.920><c> word</c>``)
  and repeat the previous line in each new cue; the repeats are dropped.
"""
from __future__ import annotations

import html
import re

TIME = r"(\d+:)?\d{1,2}:\d{2}[.,]\d{3}"
CUE = re.compile(rf"^\s*({TIME})\s*-->\s*({TIME})")
INLINE = re.compile(r"<(\d+:)?\d{1,2}:\d{2}\.\d{3}>")
TAG = re.compile(r"</?[^>]+>")


def seconds(t: str) -> float:
    parts = t.replace(",", ".").split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return round(parts[0] * 3600 + parts[1] * 60 + parts[2], 3)


def parse(text: str) -> list[dict]:
    """Cues of an SRT or WebVTT file: [{start, end, text, words?}]; `words` when the cue
    carries per-word times (YouTube automatic captions)."""
    cues, cur = [], None
    for raw in text.replace("\r", "").split("\n"):
        m = CUE.match(raw)
        if m:
            cur = {"start": seconds(m.group(1)), "end": seconds(m.group(3)), "lines": []}
            cues.append(cur)
            continue
        if cur is None:
            continue
        if not raw.strip():
            if cur["lines"]:  # YouTube puts a blank line right after the timing line
                cur = None
            continue
        if raw.strip().isdigit() and not cur["lines"]:
            continue  # an SRT cue number
        cur["lines"].append(raw)
    out = []
    for c in cues:
        timed = [ln for ln in c["lines"] if INLINE.search(ln)]
        if timed:  # automatic captions: the words of this cue, each with its time
            words = _inline_words(timed[-1], c["start"], c["end"])
            out.append({"start": c["start"], "end": c["end"], "text": " ".join(w["w"] for w in words), "words": words})
        else:
            txt = _clean(" ".join(c["lines"]))
            if txt:
                out.append({"start": c["start"], "end": c["end"], "text": txt})
    if any("words" in c for c in out):  # drop the repeated lines of automatic captions
        out = [c for c in out if "words" in c]
    return out


def _clean(s: str) -> str:
    s = html.unescape(TAG.sub("", s))
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", s)  # [Music], (laughs)
    s = re.sub(r"^\s*(>>|-)\s*", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _inline_words(line: str, start: float, end: float) -> list[dict]:
    parts = re.split(r"(<(?:\d+:)?\d{1,2}:\d{2}\.\d{3}>)", line)
    words, t = [], start
    for p in parts:
        if INLINE.fullmatch(p):
            t = seconds(p[1:-1])
            continue
        for w in _clean(p).split():
            words.append({"w": w, "start": t, "end": t})
    for i, w in enumerate(words):  # a word lasts until the next begins
        w["end"] = round(words[i + 1]["start"] if i + 1 < len(words) else end, 3)
        if w["end"] <= w["start"]:
            w["end"] = round(w["start"] + 0.2, 3)
    return words


def _spread(cue: dict) -> list[dict]:
    """Words of a cue without word times: its span shared by the words' lengths."""
    toks = cue["text"].split()
    total = sum(len(t) + 1 for t in toks) or 1
    span, t, out = cue["end"] - cue["start"], cue["start"], []
    for tok in toks:
        d = span * (len(tok) + 1) / total
        out.append({"w": tok, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def to_doc(cues: list[dict], language: str | None = None, max_gap: float = 0.8, max_len: float = 15.0) -> dict:
    """Cues → transcript document. Words keep their times (or get spread ones); segments
    break at a sentence end, a pause over ``max_gap`` or ``max_len`` seconds."""
    words = []
    for c in cues:
        words += c.get("words") or _spread(c)
    segs, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or w["end"] - cur[0]["start"] > max_len):
            segs.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.?!]['\")\]]?$", w["w"]):
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return {"language": language, "model": "captions", "source": "captions",
            "segments": [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["w"] for w in s), "words": s}
                         for s in segs]}


def load(text: str, language: str | None = None) -> dict:
    return to_doc(parse(text), language)
