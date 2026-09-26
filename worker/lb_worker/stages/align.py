"""CTC forced alignment with any Hugging Face CTC model, for any language.

whisperX aligns only with the models on its built-in list. Here the aligner is any
repo whose architecture ends in ``ForCTC`` (wav2vec2, wav2vec2-BERT, MMS, HuBERT,
...) and whose vocabulary is characters: pick one per language in the app. The
dynamic programme is whisperX's own (vendored in ``align_core``), so results match
whisperX for the models it does support.

Inputs: an audio file and a transcript JSON in asr.json form
    {"segments": [{"start", "end", "text", "words": [{"w", "start", "end", ...}]}]}
params: {"model": "<hf repo id>", "language": "am"}
Output: out/aligned.json, the same document with word times replaced by aligned
ones (plus a per-word "score"), and "aligner"/"align_ok" per segment. Segments that
cannot be aligned keep their original times, so this step can only improve timing.
"""
from __future__ import annotations

import json
import re
import unicodedata

from .. import align_core
from ..deps import device, ensure
from ..registry import stage

PAD_S = 0.15  # audio kept on each side of a segment, so edge words are not clipped


@stage("align", model_key="aligner")
def align(ctx) -> dict:
    ensure("soundfile", probe="soundfile")
    import soundfile as sf

    repo = ctx.params["model"]
    aligner = ctx.model(f"aligner:{repo}", lambda: load_aligner(repo))

    audio_path = next(p for p in map(ctx.input, ctx.job["inputs"]) if p.suffix.lower() in (".flac", ".wav", ".mp3"))
    doc_path = next(p for p in map(ctx.input, ctx.job["inputs"]) if p.suffix.lower() == ".json")
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    wav16 = ctx.work / "align16k.wav"
    import subprocess

    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio_path), "-ac", "1", "-ar", "16000", str(wav16)], check=True)
    audio, sr = sf.read(str(wav16), dtype="float32")
    ok, total = align_doc(doc, audio, sr, aligner, repo, ctx.log, ctx.set_progress)
    (ctx.out / "aligned.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    ctx.log(f"aligned {ok}/{total} segments with {repo}")
    return {"model": repo, "segments": total, "aligned": ok}


def load_aligner(repo: str) -> dict:
    ensure("transformers", probe="transformers")
    import torch
    from transformers import AutoModelForCTC, AutoProcessor

    dev = device()
    if dev == "cpu" and hasattr(torch, "xpu") and torch.xpu.is_available():
        dev = "xpu"
    proc = AutoProcessor.from_pretrained(repo)
    return {"proc": proc, "model": AutoModelForCTC.from_pretrained(repo).to(dev).eval(), "dev": dev,
            "vocab": proc.tokenizer.get_vocab(),
            "blank": proc.tokenizer.pad_token_id if proc.tokenizer.pad_token_id is not None else 0,
            "delim": getattr(proc.tokenizer, "word_delimiter_token", None) or "|"}


def align_doc(doc: dict, audio, sr: int, a: dict, repo: str, log=print, progress=lambda *_: None) -> tuple[int, int]:
    """Align every segment of an asr.json document in place; returns (aligned, total)."""
    ok = total = 0
    segs = doc["segments"]
    for i, seg in enumerate(segs):
        progress(i / max(1, len(segs)))
        total += 1
        try:
            words = align_segment(seg, audio, sr, a["proc"], a["model"], a["vocab"], a["blank"], a["delim"], a["dev"])
        except Exception as e:  # one bad segment must not sink the rest
            log(f"segment {i}: {type(e).__name__}: {e}")
            words = None
        seg["aligner"] = repo
        seg["align_ok"] = words is not None
        if words is not None:
            seg["words"] = words
            ok += 1
    doc["aligner"] = repo
    return ok, total


def normalise(ch: str, vocab: dict) -> str | None:
    """Map a transcript character onto the model's vocabulary, or None to skip it
    (punctuation the model never emits, for instance)."""
    for c in (ch, ch.lower(), ch.upper(), unicodedata.normalize("NFC", ch)):
        if c in vocab:
            return c
    return None


def align_segment(seg, audio, sr, proc, model, vocab, blank, delim, dev):
    import torch

    original = seg.get("words") or []
    tokens_text = [w["w"] for w in original] if original else seg["text"].split()
    if not tokens_text:
        return None
    t0 = max(0.0, seg["start"] - PAD_S)
    t1 = min(len(audio) / sr, seg["end"] + PAD_S)
    clip = audio[int(t0 * sr):int(t1 * sr)]
    if len(clip) < sr * 0.1:
        return None

    # Character stream with the word delimiter between words; remember each
    # character's word so aligned spans can be regrouped per original word.
    chars, owner = [], []
    for wi, w in enumerate(tokens_text):
        if chars:
            chars.append(delim if delim in vocab else " ")
            owner.append(-1)
        for ch in re.sub(r"\s+", "", w):
            n = normalise(ch, vocab)
            if n is not None:
                chars.append(n)
                owner.append(wi)
    ids = [vocab[c] for c in chars if c in vocab]
    owner = [o for c, o in zip(chars, owner) if c in vocab]
    if not any(o >= 0 for o in owner):
        return None

    inputs = proc(clip, sampling_rate=sr, return_tensors="pt")
    inputs = {k: v.to(dev) for k, v in inputs.items()}
    with torch.inference_mode():
        emission = torch.log_softmax(model(**inputs).logits[0].float(), dim=-1).cpu()
    frames = emission.size(0)
    if frames < len(ids):
        return None
    frame_s = (t1 - t0) / frames

    trellis = align_core.get_trellis(emission, ids, blank)
    path = align_core.backtrack(trellis, emission, ids, blank)
    if path is None:
        return None
    # Frame span and confidence per aligned character (token index -> frames).
    spans: dict[int, list] = {}
    for p in path:
        spans.setdefault(p.token_index, []).append(p)

    words = []
    for wi, text in enumerate(tokens_text):
        mine = [k for k, o in enumerate(owner) if o == wi and k in spans]
        base = original[wi] if wi < len(original) else {"w": text}
        if mine:
            s = spans[mine[0]][0].time_index
            e = spans[mine[-1]][-1].time_index + 1
            score = sum(p.score for k in mine for p in spans[k]) / sum(len(spans[k]) for k in mine)
            words.append({**base, "start": round(t0 + s * frame_s, 3), "end": round(t0 + e * frame_s, 3),
                          "score": round(score, 3)})
        else:
            words.append({**base, "start": None, "end": None, "score": None})
    # Words with nothing alignable (numbers, symbols) sit between their neighbours.
    starts = align_core.interpolate_nans([w["start"] for w in words])
    ends = align_core.interpolate_nans([w["end"] for w in words])
    for w, s, e in zip(words, starts, ends):
        if w["start"] is None:
            w["start"], w["end"], w["interpolated"] = s, e, True
    return words
