"""Transcribe many videos in one pass of an already-loaded Whisper.

Batched faster-whisper fills the GPU with up to ``batch_size`` 30-second windows at a
time — but one 6-minute video only has a dozen windows, so a video at a time leaves the
GPU half idle and pays the per-call overhead again and again. Here the speech windows
of a whole group of videos (Silero VAD per video, merged into ≤30 s windows that never
cross a video boundary) go through one ``transcribe(clip_timestamps=…)`` call over the
videos' audio joined end to end, and each result is shifted back to its own video.
"""
from __future__ import annotations

import bisect

import numpy as np

SR = 16000
GAP_S = 1.0          # silence between joined videos (no window ever spans it)
MAX_WINDOW_S = 29.5  # Whisper reads 30 s at a time


def merge_windows(speech: list[tuple[float, float]], max_s: float = MAX_WINDOW_S) -> list[tuple[float, float]]:
    """Speech regions (seconds) → windows of at most ``max_s`` seconds, each covering
    whole regions where it can (a region longer than a window is cut into pieces)."""
    out: list[list[float]] = []
    for s, e in speech:
        while e - s > max_s:  # one very long stretch of speech
            out.append([s, s + max_s])
            s += max_s
        if out and e - out[-1][0] <= max_s:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def join(audios: dict[str, np.ndarray], windows: dict[str, list[tuple[float, float]]], gap_s: float = GAP_S):
    """One long signal of every video, the clip list for Whisper, and each video's offset."""
    parts, offsets, clips, t = [], {}, [], 0.0
    gap = np.zeros(int(gap_s * SR), dtype=np.float32)
    for vid, a in audios.items():
        offsets[vid] = t
        parts += [a.astype(np.float32), gap]
        clips += [{"start": round(t + s, 3), "end": round(t + e, 3)} for s, e in windows[vid]]
        t += len(a) / SR + gap_s
    return (np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)), clips, offsets


def split(segments: list[dict], offsets: dict[str, float]) -> dict[str, list[dict]]:
    """Joined-signal segments → each video's segments, times relative to that video."""
    order = sorted(offsets, key=offsets.get)
    starts = [offsets[v] for v in order]
    out: dict[str, list[dict]] = {v: [] for v in order}
    for seg in segments:
        vid = order[max(0, bisect.bisect_right(starts, seg["start"] + 1e-6) - 1)]
        off = offsets[vid]
        out[vid].append({**seg, "start": round(seg["start"] - off, 3), "end": round(seg["end"] - off, 3),
                         "words": [{**w, "start": round(w["start"] - off, 3), "end": round(w["end"] - off, 3)}
                                   for w in seg.get("words", [])]})
    return out


def speech(audio: np.ndarray) -> list[tuple[float, float]]:
    """Silero VAD (faster-whisper's) → speech regions in seconds."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    return [(t["start"] / SR, t["end"] / SR) for t in get_speech_timestamps(audio, VadOptions())]


def transcribe_many(model, audios: dict[str, np.ndarray], language: str | None, size: str,
                    batch_size: int = 16) -> dict[str, dict]:
    """{video id: 16 kHz mono float32} → {video id: asr.json document}, one Whisper pass."""
    from faster_whisper import BatchedInferencePipeline

    windows = {vid: merge_windows(speech(a)) for vid, a in audios.items()}
    signal, clips, offsets = join(audios, windows)
    docs = {vid: {"language": language, "model": size, "segments": []} for vid in audios}
    if not clips:
        return docs
    pipe = BatchedInferencePipeline(model=model)
    segs, info = pipe.transcribe(signal, language=language, word_timestamps=True, clip_timestamps=clips,
                                 batch_size=batch_size, beam_size=5)
    flat = [{"start": s.start, "end": s.end, "text": s.text.strip(),
             "words": [{"w": w.word.strip(), "start": w.start, "end": w.end, "p": round(w.probability, 3)}
                       for w in (s.words or [])]} for s in segs]
    for vid, ss in split(flat, offsets).items():
        docs[vid] = {"language": info.language, "model": size, "segments": ss}
    return docs
