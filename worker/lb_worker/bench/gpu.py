"""E1: how fast each GPU stage can go here, and how full the GPU gets.

Run #1 (Colab T4) separated at 3.2 s per window with 2.5 of 15 GB in use: one window at
a time. This measures, on the same excerpts, every setting worth trying and whether it
changes the result:

    separation   batch_size × half precision, stems compared with the batch-1 baseline
    audio copy   separation from an Opus copy (what a Kaggle run gets for local videos)
    whisper      batch_size of the batched pipeline (lb_worker.batch_asr)
    omnivoice    takes per call (its generate() takes lists), one voice prompt reused
"""
from __future__ import annotations

import gc
import json
import subprocess
import sys
import time
from pathlib import Path

from .common import GpuSampler, diff_db, ffmpeg, read_audio, save, snr_db, table

# (batch_size, autocast, native_fp16); the first is the baseline the others are compared with
SEP_GRID = [(1, False, False), (4, False, False), (8, False, False), (16, False, False),
            (8, True, False), (16, True, False), (16, False, True)]  # (1, False, True) is the default now
INAUDIBLE_DB = -50.0
WHISPER_BATCHES = (8, 16, 32)
OMNI_BATCHES = (1, 4, 8, 16)

# Short, plain Amharic sentences of mixed length for the voicing bench (content does not
# matter for speed; they are spoken with the voice of the first excerpt).
AMHARIC = [
    "ሰላም፣ እንኳን ደህና መጣችሁ።", "ዛሬ ስለ ምግብ እንነጋገራለን።", "ይህ በጣም አስደሳች ጥያቄ ነው።",
    "ብዙ ሰዎች ጠዋት ቡና መጠጣት ይወዳሉ።", "ልጆች በትምህርት ቤት አዳዲስ ነገሮችን ይማራሉ።",
    "አየሩ ዛሬ ትንሽ ቀዝቃዛ ነው።", "መጽሐፍ ማንበብ አእምሮን ያሰፋል።", "እባክህ ቀስ ብለህ ተናገር።",
    "ከተማዋ በምሽት በጣም ጸጥ ትላለች።", "ጤናማ ምግብ መመገብ ለሰውነት ጠቃሚ ነው።", "ቤተሰቤ በገጠር ይኖራሉ።",
    "ይህንን ሃሳብ ከሌላ አቅጣጫ እንመልከተው።", "እውነቱን ለመናገር፣ እኔም አላውቅም ነበር።",
    "ሳይንቲስቶች የአየር ንብረት ለውጥን ያጠናሉ።", "በሚቀጥለው ሳምንት እንደገና እንገናኛለን።", "ስፖርት መሥራት ጭንቀትን ይቀንሳል።",
]


def _free() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "xpu") and torch.xpu.is_available():  # Intel Arc: its memory is the PC's RAM
            torch.xpu.empty_cache()
    except ImportError:
        pass


def prepare(sources: list[str], out: Path, seconds: int = 120, start: int = 60, log=print) -> list[dict]:
    """Excerpts (``seconds`` from ``start``) of links or files → 44.1 kHz stereo WAVs, plus
    Opus copies at 160 and 96 kb/s decoded back to WAV."""
    from ..deps import ensure

    items = []
    for k, src in enumerate(sources):
        d = out / "excerpts" / f"{k:02d}"
        d.mkdir(parents=True, exist_ok=True)
        wav = d / "excerpt.wav"
        if not wav.exists():
            if src.startswith("http"):
                ensure("yt-dlp", probe="yt_dlp")
                # audio only: cutting a video section re-encodes it (AV1 on YouTube: minutes on a CPU)
                p = subprocess.run([sys.executable, "-m", "yt_dlp", "-f", "ba/b", "--no-playlist", "--retries", "10",
                                    "--download-sections", f"*{start}-{start + seconds}", "-o", str(d / "audio.%(ext)s"),
                                    "--", src], capture_output=True, text=True)
                got = sorted(d.glob("audio.*"))
                if p.returncode or not got:
                    raise RuntimeError(f"download failed: {(p.stderr or p.stdout)[-400:]}")
                ffmpeg("-i", str(got[0]), "-vn", "-ac", "2", "-ar", "44100", str(wav))
            else:
                ffmpeg("-ss", str(start), "-t", str(seconds), "-i", src, "-vn", "-ac", "2", "-ar", "44100", str(wav))
        it = {"name": f"{k:02d}", "source": src, "wav": str(wav), "seconds": round(len(read_audio(wav)) / 44100, 1)}
        for kbps in (160, 96):
            enc, dec = d / f"excerpt.{kbps}k.opus", d / f"excerpt.{kbps}k.wav"
            if not dec.exists():
                ffmpeg("-i", str(wav), "-c:a", "libopus", "-b:a", f"{kbps}k", str(enc))
                ffmpeg("-i", str(enc), "-ac", "2", "-ar", "44100", str(dec))
            it[f"opus{kbps}"] = str(dec)
        items.append(it)
        log(f"excerpt {it['name']}: {it['seconds']} s from {src[:70]}")
    return items


def _label(cfg: tuple) -> str:
    b, ac, fp16 = cfg
    return f"batch {b}" + (" +autocast" if ac else "") + (" +fp16" if fp16 else "")


def _separate(items: list[dict], cfg: tuple, dest: Path, key: str = "wav", log=print) -> dict:
    from ..stages.analysis import load_separator, separate_file

    t = time.time()
    sep = load_separator(None, 2, log, batch_size=cfg[0], autocast=cfg[1], native_fp16=cfg[2])
    load_s = time.time() - t
    try:
        with GpuSampler() as g:
            for it in items:
                separate_file(sep, Path(it[key]), dest / "tmp" / it["name"], dest / it["name"], log)
    finally:
        del sep
        _free()
    return {"seconds": g.seconds, "load_s": round(load_s, 1), "gpu": g.stats()}


def bench_separation(items: list[dict], out: Path, grid=SEP_GRID, log=print) -> dict:
    audio_s = sum(it["seconds"] for it in items)
    rows, base = [], None
    for cfg in grid:
        dest = out / "sep" / _label(cfg).replace(" ", "_").replace("+", "")
        row = {"setting": _label(cfg)}
        try:
            r = _separate(items, cfg, dest, log=log)
        except Exception as e:  # e.g. out of GPU memory at a large batch
            rows.append(row | {"error": f"{type(e).__name__}: {str(e)[:120]}"})
            log(f"separation {row['setting']}: {rows[-1]['error']}")
            _free()
            continue
        gpu0 = next(iter(r["gpu"].values()), {})
        vocals = {it["name"]: read_audio(dest / it["name"] / "vocals.flac") for it in items}
        if base is None:  # the baseline itself
            base, worst = vocals, None
        else:
            worst = max(diff_db(base[n], v) for n, v in vocals.items())
        row |= {"s": round(r["seconds"], 2), "x_realtime": round(audio_s / max(r["seconds"], 1e-6), 2),
                "gpu_util": gpu0.get("util_mean"), "gpu_mem_gb": gpu0.get("mem_max_gb"),
                "vs_baseline_db": worst, "same_result": worst is None or worst <= INAUDIBLE_DB, "dir": str(dest)}
        rows.append(row)
        log(f"separation {row['setting']}: {row['s']} s for {audio_s:.0f} s of audio "
            f"({row['x_realtime']}× real time), GPU {row['gpu_util']} % / {row['gpu_mem_gb']} GB, "
            f"vs baseline {worst} dB")
    ok = [r for r in rows if r.get("same_result")]
    best = min(ok, key=lambda r: r["x_realtime"] * -1) if ok else None
    result = {"audio_s": audio_s, "rows": rows, "best": best and best["setting"]}
    save(out, "e1_separation", result)
    print(table(rows, ["setting", "s", "x_realtime", "gpu_util", "gpu_mem_gb", "vs_baseline_db", "same_result", "error"]))
    return result


def bench_audio_copy(items: list[dict], out: Path, sep_result: dict, log=print) -> dict:
    """Stems from the Opus copies vs stems from the original, with the best setting."""
    best = next((r for r in sep_result["rows"] if r["setting"] == sep_result.get("best")), sep_result["rows"][0])
    cfg = next(c for c in SEP_GRID if _label(c) == best["setting"])
    rows = []
    for kbps in (160, 96):
        dest = out / "sep_opus" / f"{kbps}k"
        _separate(items, cfg, dest, key=f"opus{kbps}", log=log)
        for it in items:
            ref = read_audio(Path(best["dir"]) / it["name"] / "vocals.flac")
            x = read_audio(dest / it["name"] / "vocals.flac")
            rows.append({"copy": f"opus {kbps}k", "excerpt": it["name"], "vocals_snr_db": snr_db(ref, x)})
    result = {"setting": best["setting"], "rows": rows,
              "note": "higher is closer to the original; also listen to sep_opus/*/vocals.flac"}
    save(out, "e1_audio_copy", result)
    print(table(rows, ["copy", "excerpt", "vocals_snr_db"]))
    return result


def bench_whisper(items: list[dict], out: Path, batches=WHISPER_BATCHES, size: str = "large-v3", log=print) -> dict:
    import difflib

    from .. import batch_asr
    from ..deps import ensure

    ensure("faster-whisper>=1.1", probe="faster_whisper")
    from ..stages.analysis import load_whisper

    audios = {it["name"]: read_audio(it["wav"], 16000, 1)[:, 0] for it in items}
    audio_s = sum(len(a) for a in audios.values()) / 16000
    model = load_whisper(size, log)
    rows, first = [], None
    try:
        for bs in batches:
            with GpuSampler() as g:
                docs = batch_asr.transcribe_many(model, audios, "en", size, batch_size=bs)
            words = [w["w"].lower() for n in sorted(docs) for s in docs[n]["segments"] for w in s["words"]]
            first = first or words
            gpu0 = next(iter(g.stats().values()), {})
            rows.append({"batch": bs, "s": round(g.seconds, 1), "x_realtime": round(audio_s / g.seconds, 1),
                         "gpu_util": gpu0.get("util_mean"), "gpu_mem_gb": gpu0.get("mem_max_gb"), "words": len(words),
                         "same_words": round(difflib.SequenceMatcher(a=first, b=words, autojunk=False).ratio(), 3)})
            log(f"whisper batch {bs}: {rows[-1]}")
            (out / "whisper").mkdir(parents=True, exist_ok=True)
            (out / "whisper" / f"docs_b{bs}.json").write_text(json.dumps(docs), encoding="utf-8")
    finally:
        del model
        _free()
    result = {"audio_s": audio_s, "rows": rows}
    save(out, "e1_whisper", result)
    print(table(rows, ["batch", "s", "x_realtime", "gpu_util", "gpu_mem_gb", "words", "same_words"]))
    return result


def reference(items: list[dict], sep_dir: Path, out: Path, at: float = 20.0, seconds: float = 8.0) -> tuple[Path, str | None]:
    """An ~8 s voice reference cut from the first excerpt's vocals, with the words Whisper
    heard there (so OmniVoice need not transcribe it again)."""
    name = items[0]["name"]
    ref = out / "omnivoice" / "ref.wav"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-ss", str(at), "-t", str(seconds), "-i", str(sep_dir / name / "vocals.flac"), "-ac", "1", "-ar", "24000", str(ref))
    text = None
    docs = sorted((out / "whisper").glob("docs_b*.json"))
    if docs:
        doc = json.loads(docs[0].read_text(encoding="utf-8"))[name]
        words = [w["w"] for s in doc["segments"] for w in s["words"] if at <= w["start"] and w["end"] <= at + seconds]
        text = " ".join(words) or None
    return ref, text


def bench_omnivoice(ref: Path, ref_text: str | None, out: Path, batches=OMNI_BATCHES, steps: int = 16,
                    n: int = 32, log=print) -> dict:
    """In its own process (OmniVoice's dependencies stay apart, as in the runner)."""
    from ..stages.bakeoff import pip

    class _Ctx:  # what pip() needs
        def log(self, m):
            log(m)

    if not pip(_Ctx(), "omnivoice"):
        raise RuntimeError("pip install omnivoice failed")
    texts = (AMHARIC * (n // len(AMHARIC) + 1))[:n]
    res = out / "omnivoice" / "result.json"
    cmd = [sys.executable, str(Path(__file__).with_name("omnivoice_bench.py")), "--ref", str(ref),
           "--texts", json.dumps(texts, ensure_ascii=False), "--batches", ",".join(map(str, batches)),
           "--steps", str(steps), "--out", str(res), "--wavs", str(out / "omnivoice")]
    if ref_text:
        cmd += ["--ref-text", ref_text]
    p = subprocess.run(cmd, capture_output=True, text=True)
    log(p.stdout[-3000:])
    if p.returncode or not res.exists():
        raise RuntimeError(f"omnivoice bench failed: {(p.stderr or p.stdout)[-1500:]}")
    result = json.loads(res.read_text(encoding="utf-8"))
    save(out, "e1_omnivoice", result)
    print(table(result["rows"], ["batch", "s", "takes_per_min", "audio_x_realtime", "gpu_util", "gpu_mem_gb", "failed"]))
    return result
