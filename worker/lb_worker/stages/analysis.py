"""Source-side analysis: separate -> asr -> diarize.

Every stage writes plain JSON/FLAC to out/ so the desktop never needs the models.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..deps import cache_dir, device, ensure, hf_snapshot
from ..registry import stage


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---- separate --------------------------------------------------------------------------
@stage("separate", model_key="separator")
def separate(ctx) -> dict:
    """Vocals / background split. Default model: audio-separator's default
    (a Mel-Band/BS RoFormer vocal model); override with params.model."""
    ensure("audio-separator[gpu]" if device() == "cuda" else "audio-separator[cpu]", probe="audio_separator")
    # audio-separator imports audioread, which current librosa no longer pulls in.
    ensure("audioread", probe="audioread")
    from audio_separator.separator import Separator

    patch_separator_download(ctx.log)
    enable_xpu_for_separator(ctx.log)
    src = ctx.input(ctx.job["inputs"][0])
    model_name = ctx.params.get("model")
    tmp = ctx.work / "sep"
    tmp.mkdir(exist_ok=True)

    def load():
        # overlap 2 (library default 8): a quarter of the windows; on the test clip its
        # vocals matched overlap 8 to 65 dB, far below audibility.
        s = Separator(output_dir=str(tmp), output_format="FLAC",
                      model_file_dir=str(cache_dir("audio-separator")),
                      mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                   "batch_size": 1, "overlap": int(ctx.params.get("overlap", 2)),
                                   "pitch_shift": 0})
        s.load_model(model_name) if model_name else s.load_model()
        return s

    sep = ctx.model(f"separator:{model_name}", load)
    # The loaded model is reused across jobs, but its output folder was fixed when it was
    # loaded (the first job's): point it at this job's folder, or later jobs' stems land
    # in a folder that no longer exists.
    sep.output_dir = str(tmp)
    if getattr(sep, "model_instance", None) is not None:
        sep.model_instance.output_dir = str(tmp)
    files = [Path(tmp / f) if not os.path.isabs(f) else Path(f) for f in sep.separate(str(src))]
    ctx.log(f"separator outputs: {[f.name for f in files]}")
    vocals = next(f for f in files if "(vocals)" in f.name.lower())
    other = next(f for f in files if f is not vocals)
    shutil.move(str(vocals), ctx.out / "vocals.flac")
    shutil.move(str(other), ctx.out / "background.flac")
    return {"model": sep.model_friendly_name if hasattr(sep, "model_friendly_name") else model_name,
            "files": ["vocals.flac", "background.flac"]}


def patch_separator_download(log=print) -> None:
    """audio-separator streams model files straight to their final name and trusts
    any file that exists, so one dropped connection leaves a corrupt model behind.
    Route its downloads through the resumable fetch instead."""
    from audio_separator.separator import Separator

    from ..deps import fetch

    Separator.download_file_if_not_exists = lambda self, url, output_path: fetch(url, output_path, log=log)


def enable_xpu_for_separator(log=print) -> None:
    """audio-separator only knows CUDA, Apple MPS and DirectML. On an Intel Arc GPU
    with PyTorch's XPU build, move its torch models (the RoFormers) to the GPU after
    its own setup has settled for the CPU. ONNX models stay on the CPU."""
    import torch
    from audio_separator.separator import Separator

    if not (hasattr(torch, "xpu") and torch.xpu.is_available()) or getattr(Separator, "_lb_xpu", False):
        return
    original = Separator.setup_torch_device

    def setup(self, system_info):
        original(self, system_info)
        if self.torch_device is not None and self.torch_device.type == "cpu":
            self.torch_device = torch.device("xpu")
            log("separator: using Intel XPU for torch models")

    Separator.setup_torch_device = setup
    Separator._lb_xpu = True


# ---- asr -------------------------------------------------------------------------------
@stage("asr", model_key="whisper")
def asr(ctx) -> dict:
    """faster-whisper with Silero VAD and word timestamps."""
    ensure("faster-whisper>=1.1", probe="faster_whisper")

    size = ctx.params.get("model", "large-v3")
    model = ctx.model(f"whisper:{size}", lambda: load_whisper(size, ctx.log))
    audio = ctx.input(ctx.job["inputs"][0])
    wav = ctx.work / "asr16k.wav"
    _ffmpeg("-i", str(audio), "-ac", "1", "-ar", "16000", str(wav))
    doc = transcribe(model, wav, ctx.params.get("language"), size)  # language None = detect
    _write(ctx.out / "asr.json", doc)
    return {"language": doc["language"], "segments": len(doc["segments"]),
            "words": sum(len(s["words"]) for s in doc["segments"])}


def load_whisper(size: str, log=print):
    from faster_whisper import WhisperModel

    dev = device()
    return WhisperModel(whisper_path(size, log), device=dev, compute_type="float16" if dev == "cuda" else "int8")


def transcribe(model, wav16: Path, lang: str | None, size: str) -> dict:
    """16 kHz mono wav -> asr.json document (segments with word timings)."""
    from faster_whisper import BatchedInferencePipeline

    pipe = BatchedInferencePipeline(model=model)
    segs, info = pipe.transcribe(str(wav16), language=lang, word_timestamps=True,
                                 vad_filter=True, batch_size=16, beam_size=5)
    out = []
    for s in segs:
        out.append({
            "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
            "words": [{"w": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
                       "p": round(w.probability, 3)} for w in (s.words or [])],
        })
    return {"language": info.language, "model": size, "segments": out}


def whisper_path(size: str, log=print) -> str:
    """Resolve a faster-whisper size name to a local snapshot, downloading with retries."""
    from faster_whisper.utils import _MODELS

    repo = _MODELS.get(size, size)
    return hf_snapshot(repo, log=log, allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                                      "tokenizer.json", "vocabulary.*"])


# ---- diarize ---------------------------------------------------------------------------
@stage("diarize", model_key="pyannote")
def diarize(ctx) -> dict:
    """pyannote community-1 on the vocal stem. Writes turns, the exclusive
    (one-speaker-at-a-time) turns and per-speaker centroid embeddings; if an asr.json
    is among the inputs, also stamps a speaker on every word."""
    name = ctx.params.get("pipeline", "pyannote/speaker-diarization-community-1")
    pipe = ctx.model(f"pyannote:{name}", lambda: load_pyannote(name))
    inputs = [ctx.input(r) for r in ctx.job["inputs"]]
    audio = next(p for p in inputs if p.suffix.lower() in (".flac", ".wav", ".mp3"))
    wav = ctx.work / "dia16k.wav"
    _ffmpeg("-i", str(audio), "-ac", "1", "-ar", "16000", str(wav))
    kw = {k: ctx.params[k] for k in ("num_speakers", "min_speakers", "max_speakers") if k in ctx.params}
    data = diarize_wav(pipe, wav, kw, name)
    asr_json = next((p for p in inputs if p.name in ("aligned.json", "asr.json")), None)
    if asr_json:
        _write(ctx.out / "asr_spk.json", stamp_speakers(json.loads(asr_json.read_text(encoding="utf-8")), data["exclusive"]))
    _write(ctx.out / "diarization.json", data)
    talk = {}
    for t in data["exclusive"]:
        talk[t["speaker"]] = talk.get(t["speaker"], 0) + t["end"] - t["start"]
    return {"speakers": data["labels"], "talk_s": {k: round(v, 1) for k, v in talk.items()}}


def load_pyannote(name: str = "pyannote/speaker-diarization-community-1"):
    ensure("pyannote.audio>=4", probe="pyannote.audio")
    import torch
    from pyannote.audio import Pipeline

    token = os.environ.get("HF_TOKEN")
    if not token:  # on a PC: whatever `hf auth login` saved
        from huggingface_hub import get_token

        token = get_token()
    if not token:
        raise RuntimeError("No Hugging Face token (pyannote community-1 is gated): add the HF_TOKEN "
                           "secret in Colab, or run `hf auth login` once on this PC")
    return Pipeline.from_pretrained(name, token=token).to(torch.device(device()))


def diarize_wav(pipe, wav16: Path, kw: dict, name: str) -> dict:
    """16 kHz mono wav -> diarization.json document (turns, exclusive turns, centroids)."""
    import torch

    # Hand pyannote the decoded waveform: given a path, pyannote 4 decodes through
    # torchcodec, which needs FFmpeg's shared libraries (absent from standalone
    # Windows FFmpeg builds).
    ensure("soundfile", probe="soundfile")
    import soundfile as sf

    x, sr = sf.read(str(wav16), dtype="float32", always_2d=True)
    res = pipe({"waveform": torch.from_numpy(x.T.copy()), "sample_rate": sr}, **kw)

    ann = getattr(res, "speaker_diarization", res)
    excl = getattr(res, "exclusive_speaker_diarization", None)
    turns = [{"start": round(t.start, 3), "end": round(t.end, 3), "speaker": spk}
             for t, _, spk in ann.itertracks(yield_label=True)]
    ex_turns = [{"start": round(t.start, 3), "end": round(t.end, 3), "speaker": spk}
                for t, _, spk in excl.itertracks(yield_label=True)] if excl is not None else turns
    embs = getattr(res, "speaker_embeddings", None)
    labels = ann.labels()
    centroids = {lab: [round(float(x), 5) for x in embs[i]] for i, lab in enumerate(labels)} \
        if embs is not None and len(embs) == len(labels) else {}

    return {"pipeline": name, "turns": turns, "exclusive": ex_turns, "centroids": centroids, "labels": list(labels)}


def stamp_speakers(doc: dict, ex_turns: list[dict]) -> dict:
    """Give every word, and each segment by majority, the speaker talking at that time."""
    for seg in doc["segments"]:
        for w in seg["words"]:
            w["spk"] = _speaker_at(ex_turns, (w["start"] + w["end"]) / 2)
        seg["speaker"] = _majority([w.get("spk") for w in seg["words"]])
    return doc


def _speaker_at(turns: list[dict], t: float) -> str | None:
    best, gap = None, 1e9
    for tr in turns:
        if tr["start"] <= t <= tr["end"]:
            return tr["speaker"]
        d = min(abs(t - tr["start"]), abs(t - tr["end"]))
        if d < gap:
            best, gap = tr["speaker"], d
    return best if gap < 1.0 else None


def _majority(xs: list) -> str | None:
    xs = [x for x in xs if x]
    return max(set(xs), key=xs.count) if xs else None
