"""Which speech recogniser for which source language, and running a Hugging Face one.

Whisper large-v3 (faster-whisper, batched across videos: lb_worker.batch_asr) is the
default for the languages it transcribes well. Any language can instead name a
Hugging Face ASR model — a CTC model (wav2vec2 / MMS / XLS-R family) or a transformers
Whisper fine-tune — in the run's ``asr_models`` option, e.g. ``{"am":
"badrex/Ethio-ASR-amharic"}``; the notebook's ASR_MODELS setting writes it. Either way the
result is the same asr document (segments with timed words), so alignment, speakers,
translation and voicing do not care which recogniser made it.
"""
from __future__ import annotations

import numpy as np

SR = 16000

# Languages Whisper large-v3 transcribes well (FLEURS / Common Voice word error rates in the
# low teens or better). Others still run on Whisper unless a model is named, with a warning.
WHISPER_GOOD = {
    "en", "es", "fr", "de", "it", "pt", "nl", "ru", "tr", "pl", "uk", "ja", "zh", "ko", "ar", "hi", "id",
    "vi", "sv", "cs", "ro", "hu", "el", "fi", "da", "no", "nb", "ca", "he", "fa", "ms", "th", "bg", "hr",
    "sk", "sl", "sr", "lt", "lv", "et", "gl", "tl", "ur", "ta",
}
# Dedicated models used when the run names none for these languages.
DEFAULT_MODELS = {"am": "badrex/Ethio-ASR-amharic"}

# Forced aligners (character CTC models) per language, used when a run names none: the
# widely used community models (WhisperX's defaults where it has one), each checked to exist.
DEFAULT_ALIGNERS = {
    "en": "facebook/wav2vec2-base-960h",
    "fr": "jonatasgrosman/wav2vec2-large-xlsr-53-french",
    "de": "jonatasgrosman/wav2vec2-large-xlsr-53-german",
    "es": "jonatasgrosman/wav2vec2-large-xlsr-53-spanish",
    "it": "jonatasgrosman/wav2vec2-large-xlsr-53-italian",
    "pt": "jonatasgrosman/wav2vec2-large-xlsr-53-portuguese",
    "nl": "jonatasgrosman/wav2vec2-large-xlsr-53-dutch",
    "ru": "jonatasgrosman/wav2vec2-large-xlsr-53-russian",
    "pl": "jonatasgrosman/wav2vec2-large-xlsr-53-polish",
    "ar": "jonatasgrosman/wav2vec2-large-xlsr-53-arabic",
    "ja": "jonatasgrosman/wav2vec2-large-xlsr-53-japanese",
    "zh": "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
    "fa": "jonatasgrosman/wav2vec2-large-xlsr-53-persian",
    "el": "jonatasgrosman/wav2vec2-large-xlsr-53-greek",
    "fi": "jonatasgrosman/wav2vec2-large-xlsr-53-finnish",
    "hu": "jonatasgrosman/wav2vec2-large-xlsr-53-hungarian",
    "tr": "mpoyraz/wav2vec2-xls-r-300m-cv7-turkish",
    "uk": "Yehor/wav2vec2-xls-r-300m-uk-with-small-lm",
    "ko": "kresnik/wav2vec2-large-xlsr-korean",
    "hi": "theainerd/Wav2Vec2-large-xlsr-hindi",
    "he": "imvladikon/wav2vec2-xls-r-300m-hebrew",
    "vi": "nguyenvulebinh/wav2vec2-base-vi",
    "ur": "kingabzpro/wav2vec2-large-xls-r-300m-Urdu",
    "cs": "comodoro/wav2vec2-xls-r-300m-cs-250",
    "da": "saattrupdan/wav2vec2-xls-r-300m-ftspeech",
    "ro": "gigant/romanian-wav2vec2",
    "ca": "softcatala/wav2vec2-large-xlsr-catala",
    "am": "badrex/Ethio-ASR-amharic",
}

GAP_S = 0.6   # a pause this long between words starts a new segment
MAX_SEG_S = 12.0


def choose(lang: str | None, models: dict | None = None, whisper_size: str = "large-v3") -> tuple[str, str]:
    """("whisper", size) or ("hf", repo) for a source language. A named model of
    ``"whisper"`` or ``"whisper:<size>"`` forces Whisper for that language."""
    named = {str(k).lower(): str(v).strip() for k, v in (models or {}).items() if str(v).strip()}
    repo = named.get((lang or "").lower()) or DEFAULT_MODELS.get((lang or "").lower())
    if repo and repo.split(":")[0] == "whisper":
        return "whisper", repo.split(":", 1)[1] if ":" in repo else whisper_size
    if repo:
        return "hf", repo
    return "whisper", whisper_size


def whisper_is_good(lang: str | None) -> bool:
    return lang is None or lang.lower() in WHISPER_GOOD


def segments_from_words(words: list[dict], gap_s: float = GAP_S, max_s: float = MAX_SEG_S) -> list[dict]:
    """Timed words → segments, split at pauses and before they grow too long (a CTC model
    gives no punctuation to split sentences on)."""
    segs: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] >= gap_s or w["end"] - cur[0]["start"] > max_s):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    return [{"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["w"] for w in s), "words": s}
            for s in segs]


def words_from_chunks(chunks: list[dict], offset: float) -> list[dict]:
    """A transformers ASR pipeline's word chunks (``return_timestamps="word"``) → timed
    words, shifted to the video's time."""
    out = []
    for c in chunks:
        text = (c.get("text") or "").strip()
        ts = c.get("timestamp") or (None, None)
        if not text or ts[0] is None:
            continue
        start = float(ts[0]) + offset
        end = float(ts[1]) + offset if ts[1] is not None else start + 0.3
        out.append({"w": text, "start": round(start, 3), "end": round(max(end, start + 0.02), 3), "p": 1.0})
    return out


def load_hf(repo: str, log=print):
    """A transformers ASR pipeline for ``repo`` on the GPU when there is one."""
    import torch
    from transformers import pipeline

    dev = 0 if torch.cuda.is_available() else -1
    log(f"ASR model {repo} ({'GPU' if dev == 0 else 'CPU'})")
    return pipeline("automatic-speech-recognition", model=repo, device=dev,
                    torch_dtype=torch.float16 if dev == 0 else torch.float32)


def transcribe_hf(pipe, audios: dict[str, np.ndarray], language: str | None, repo: str,
                  batch_size: int = 16) -> dict[str, dict]:
    """{video id: 16 kHz mono float32} → {video id: asr document}: speech windows (Silero
    VAD, ≤ 30 s) of every video through the model in batches, words timed per window."""
    from .batch_asr import merge_windows, speech

    jobs = []  # (video, window start, samples)
    for vid, a in audios.items():
        for s, e in merge_windows(speech(a)):
            jobs.append((vid, s, a[int(s * SR):int(e * SR)]))
    words: dict[str, list[dict]] = {vid: [] for vid in audios}
    if jobs:
        outs = pipe([{"raw": x, "sampling_rate": SR} for _, _, x in jobs], batch_size=batch_size,
                    return_timestamps="word")
        for (vid, s, _), o in zip(jobs, outs):
            words[vid] += words_from_chunks(o.get("chunks") or [], s)
    return {vid: {"language": language, "model": repo, "segments": segments_from_words(ws)}
            for vid, ws in words.items()}
