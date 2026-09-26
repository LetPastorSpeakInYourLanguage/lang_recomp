"""Bulk: many videos per job, fetched and analysed on the worker (a whole channel on Colab).

Nothing passes through the desktop: the worker downloads each video from its origin
straight into the job folder's library (``<root>/<item.dest>/video.mp4``, on Drive when
the worker is Colab), and the desktop plays and reads it from there (Drive for Desktop).

params: {"items": [{"id", "url", "clip": [start, end] | null, "dest": "library/<work>/<source>",
                    "title"?}],
         "steps": ["fetch", "asr", "align", "diarize"]   (fetch only = just bring the media),
         "height": 720, "asr_model": "large-v3", "language": "en", "aligner": "<hf repo>" | null,
         "max_speakers": int | null}

Per item: <dest>/video.mp4 (+ fingerprint.npy when ffmpeg has Chromaprint), and in
out/<id>/: asr.json, aligned.json, asr_spk.json, diarization.json and done.json — or
error.json with the reason (e.g. YouTube refusing the worker). Items are independent and
saved as they finish: a job taken over after a dead session skips finished items. The
models load once per job and stay loaded (Whisper, the aligner and pyannote fit a T4
together), which is what makes a batch fast. Voice separation is left out: it is only
needed for a video someone dubs, and runs then.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..deps import ensure
from ..registry import stage
from .align import align_doc, load_aligner
from .analysis import _ffmpeg, _write, diarize_wav, load_pyannote, load_whisper, stamp_speakers, transcribe

PYANNOTE = "pyannote/speaker-diarization-community-1"


@stage("bulk", model_key="bulk")
def bulk(ctx) -> dict:
    items = ctx.params["items"]
    steps = set(ctx.params.get("steps") or ["fetch", "asr", "align", "diarize"])
    root = ctx.worker.layout.root
    ensure("yt-dlp", probe="yt_dlp")
    if steps & {"asr", "align", "diarize"}:
        ensure("faster-whisper>=1.1", probe="faster_whisper")
        ensure("soundfile", probe="soundfile")
    done = failed = skipped = 0
    for k, it in enumerate(items):
        if ctx.cancelled():
            break
        out = ctx.out / it["id"]
        if (out / "done.json").exists() or (ctx.drive_dir / "out" / it["id"] / "done.json").exists():
            skipped += 1
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / "error.json").unlink(missing_ok=True)
        ctx.set_progress(k / len(items), f"{k + 1}/{len(items)} {it.get('title', it['id'])[:50]}")
        t0 = time.time()
        try:
            dest = root / it["dest"]
            video = fetch(it, dest, ctx.params.get("height", 720), ctx.log)
            info = {"video": f"{it['dest']}/video.mp4", "duration": _duration(video)}
            if "fetch" in steps:
                _fingerprint(video, dest, ctx.log)
            if steps & {"asr", "align", "diarize"}:
                wav = ctx.work / f"{it['id']}.wav"
                _ffmpeg("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav))
                info |= analyse(ctx, wav, out, steps)
                wav.unlink(missing_ok=True)
            _write(out / "done.json", info | {"seconds": round(time.time() - t0, 1)})
            done += 1
        except Exception as e:  # one video must not sink the batch
            _write(out / "error.json", {"error": f"{type(e).__name__}: {e}"[-1500:]})
            ctx.log(f"{it['id']}: FAILED {type(e).__name__}: {str(e)[-300:]}")
            failed += 1
        ctx.checkpoint()  # this item's results are safe on Drive now
    return {"items": len(items), "done": done, "failed": failed, "skipped": skipped}


def fetch(it: dict, dest: Path, height: int, log=print) -> Path:
    """The item's video, clip range applied, as dest/video.mp4 (kept if already there)."""
    video = dest / "video.mp4"
    if video.exists() and video.stat().st_size > 0:
        return video
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / "video.part.mp4"
    cmd = [sys.executable, "-m", "yt_dlp", "-f", f"bv*[height<={height}]+ba/b[height<={height}]/b",
           "--merge-output-format", "mp4", "--retries", "10", "--fragment-retries", "10",
           "--no-playlist", "--force-overwrites", "-o", str(tmp)]
    runtime = _js_runtime()
    if runtime:
        cmd += ["--js-runtimes", runtime]
    clip = it.get("clip")
    if clip and (clip[0] or clip[1]):
        cmd += ["--download-sections", f"*{clip[0] or 0}-{clip[1] or 'inf'}", "--force-keyframes-at-cuts"]
    last = ""
    for attempt in range(3):
        p = subprocess.run(cmd + ["--", it["url"]], capture_output=True, text=True)
        if p.returncode == 0 and tmp.exists():
            tmp.replace(video)  # only a complete download gets the final name
            return video
        last = (p.stderr or p.stdout)[-800:]
        if "Sign in to confirm" in last or "not a bot" in last:
            break  # YouTube refuses this machine: retrying will not help
        log(f"{it['id']}: download attempt {attempt + 1} failed; retrying")
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"download failed: {last.strip()}")


def _js_runtime() -> str | None:
    """yt-dlp needs a JavaScript runtime for YouTube: node if present, else deno from PyPI."""
    if shutil.which("node"):
        return "node"
    if not shutil.which("deno"):
        try:
            ensure("deno", probe=None)
        except Exception:
            return None
    return "deno" if shutil.which("deno") else None


def _duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return round(float(p.stdout.strip()), 3)
    except ValueError:
        return 0.0


def _fingerprint(video: Path, dest: Path, log=print) -> None:
    """Chromaprint frames for finding recurring parts, next to the video (optional)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-f", "chromaprint",
                        "-fp_format", "raw", "-"], capture_output=True)
    if p.returncode == 0 and p.stdout:
        import numpy as np

        np.save(dest / "fingerprint.npy", np.frombuffer(p.stdout, dtype="<u4"))
    else:
        log("no chromaprint in this ffmpeg; the desktop computes fingerprints when needed")


def analyse(ctx, wav: Path, out: Path, steps: set) -> dict:
    """Transcribe, align and diarize one 16 kHz wav; models stay loaded for the next item."""
    import soundfile as sf

    size = ctx.params.get("asr_model", "large-v3")
    doc = transcribe(ctx.model(f"whisper:{size}", lambda: load_whisper(size, ctx.log)), wav,
                     ctx.params.get("language"), size)
    _write(out / "asr.json", doc)
    repo = ctx.params.get("aligner")
    if repo and "align" in steps:
        audio, sr = sf.read(str(wav), dtype="float32")
        ok, total = align_doc(doc, audio, sr, ctx.model(f"aligner:{repo}", lambda: load_aligner(repo)), repo, ctx.log)
        _write(out / "aligned.json", doc)
    info = {"language": doc["language"], "segments": len(doc["segments"])}
    if "diarize" in steps:
        kw = {"max_speakers": ctx.params["max_speakers"]} if ctx.params.get("max_speakers") else {}
        dia = diarize_wav(ctx.model(f"pyannote:{PYANNOTE}", lambda: load_pyannote(PYANNOTE)), wav, kw, PYANNOTE)
        _write(out / "diarization.json", dia)
        _write(out / "asr_spk.json", stamp_speakers(doc, dia["exclusive"]))
        info["speakers"] = dia["labels"]
    return info
