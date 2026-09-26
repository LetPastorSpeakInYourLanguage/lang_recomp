"""Regroup word-timed ASR output into sentence units.

Translation and voicing both work on sentences, not ASR fragments: a sentence is
the unit a translator can render faithfully, and its time slot (the span of the
words it came from) is where its dub goes. Nothing ever has to be split back.
"""
from __future__ import annotations

import re

_END = re.compile(r"[.?!…]['\")\]]*$")


def sentences(asr: dict, max_gap_s: float = 0.9, max_len_s: float = 18.0) -> list[dict]:
    """Break on sentence-final punctuation, a speaker change, a long pause, or length."""
    words = []
    for seg in asr["segments"]:
        for w in seg.get("words", []):
            if w.get("w"):
                words.append({**w, "spk": w.get("spk") or seg.get("speaker")})
    smooth_speakers(words)
    out: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            out.append({
                "id": len(out) + 1,
                "speaker": _majority([w["spk"] for w in cur]),
                "start": cur[0]["start"], "end": cur[-1]["end"],
                "text": _join([w["w"] for w in cur]),
                "words": [{"w": w["w"], "start": w["start"], "end": w["end"]} for w in cur],
            })
            cur.clear()

    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            if (w["spk"] and cur[-1]["spk"] and w["spk"] != cur[-1]["spk"]) or gap > max_gap_s \
                    or w["end"] - cur[0]["start"] > max_len_s:
                flush()
        cur.append(w)
        if _END.search(w["w"]):
            flush()
    flush()
    for s in out:
        s["slot_s"] = round(s["end"] - s["start"], 3)
    return out


def smooth_speakers(words: list[dict], max_s: float = 0.4) -> None:
    """Give a lone short word that disagrees with both neighbours to the sentence it
    belongs to. Diarization turn edges and word times are each uncertain by a few
    hundred ms, so a boundary word ("I" in "...have? I have one sister") often lands
    in the wrong turn. If the word before it ends a sentence, the stray word starts
    the next speaker's line; otherwise it finishes the current one."""
    for i in range(1, len(words) - 1):
        w, prev, nxt = words[i], words[i - 1], words[i + 1]
        if not (w["spk"] and prev["spk"] and nxt["spk"]) or w["end"] - w["start"] > max_s:
            continue
        if _END.search(w["w"]):
            continue  # "Okay." / "Wow.": a whole one-word reply, keep its speaker
        lone = w["spk"] != prev["spk"] and w["spk"] != nxt["spk"]
        if not lone and prev["spk"] == nxt["spk"]:
            continue  # not at a speaker change: nothing to decide
        w["spk"] = nxt["spk"] if _END.search(prev["w"]) else prev["spk"]


def _join(tokens: list[str]) -> str:
    return re.sub(r"\s+([,.?!;:…])", r"\1", " ".join(t.strip() for t in tokens)).strip()


def _majority(xs):
    xs = [x for x in xs if x]
    return max(set(xs), key=xs.count) if xs else None
