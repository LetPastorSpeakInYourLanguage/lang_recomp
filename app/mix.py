"""Fit, mix and export the dub.

Fit: every dubbed line starts where the original line started (lip onset). A take
longer than its slot first borrows the silence after it (and up to LEAD_S before it),
then is time-compressed with rubberband (formants preserved): freely up to
``max_stretch``, flagged up to ``hard_stretch``, beyond that it overflows into the
next line and is reported. Loudness follows the original line, so shouted lines stay
loud and asides stay quiet.

Mix: background stem, lightly ducked under the dub; extras (characters not marked
for dubbing) keep their original voice; non-speech vocal sounds (laughs, breaths)
between lines can be kept, since they carry across languages.

Everything is mono 48 kHz float32 numpy, decoded and encoded by ffmpeg.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np

from . import cast, db, langs, project, recurring, voice

SR = 48000
GAP_S = 0.08      # silence kept between consecutive dubbed lines
LEAD_S = 0.3      # how far a long line may start before the original onset
FADE_S = 0.01
DEFAULTS = {"duck_db": 4.0, "keep_nonspeech": True, "nonspeech_db": -3.0, "keep_extras": True,
            "max_stretch": 1.12, "hard_stretch": 1.25, "loudness_follow": True}


# ---- audio io ----------------------------------------------------------------------------
def decode(path: str | Path, filters: str | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path)]
    if filters:
        cmd += ["-af", filters]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"ffmpeg could not decode {path}: {p.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def encode_wav(x: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-c:a", "pcm_s16le", str(path)], input=np.clip(x, -1, 1).astype(np.float32).tobytes(),
                       capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-300:])


def db_to_gain(d: float) -> float:
    return float(10 ** (d / 20))


def speech_db(x: np.ndarray) -> float | None:
    """Level of the speech in a clip: RMS over its louder half of 20 ms frames, so
    pauses inside the line do not drag the estimate down."""
    n = len(x) // 960
    if n < 3:
        return None
    frames = np.sqrt((x[: n * 960].reshape(n, 960) ** 2).mean(1) + 1e-12)
    loud = np.sort(frames)[n // 2:]
    return float(20 * np.log10(loud.mean() + 1e-9))


# ---- fit ---------------------------------------------------------------------------------
def fit(lines: list[dict], total_s: float, p: dict) -> list[dict]:
    """lines: [{id, start, end, dur}] in time order (dur = take length).
    Returns placements: start, stretch factor (>1 = faster), placed end, status."""
    out, prev_end = [], -GAP_S  # the first line has nothing before it to keep clear of
    for i, ln in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else total_s
        win_lo = max(0.0, prev_end + GAP_S, ln["start"] - LEAD_S)
        win_hi = max(win_lo + 0.05, nxt - GAP_S)
        onset = max(ln["start"], win_lo)
        d, slot = ln["dur"], ln["end"] - ln["start"]
        factor, status = 1.0, "fits"
        if onset + d <= win_hi:
            start = onset
            status = "fits" if d <= slot + 0.05 else "borrowed"  # used the pause after the line
        elif win_lo + d <= win_hi:
            start, status = win_hi - d, "borrowed"  # also starts a little early
        else:
            need = d / (win_hi - win_lo)
            if need <= p["max_stretch"]:
                factor, status = need, "stretched"
            elif need <= p["hard_stretch"]:
                factor, status = need, "squeezed"
            else:
                factor, status = p["hard_stretch"], "overflow"
            start = win_lo
        end = start + d / factor
        out.append({"id": ln["id"], "start": round(start, 3), "end": round(end, 3), "factor": round(factor, 3),
                    "status": status, "slot_start": ln["start"], "slot_end": ln["end"], "dur": round(d, 3),
                    "overlap_s": round(max(0.0, end - nxt), 3) if status == "overflow" else 0.0})
        prev_end = end
    return out


# ---- render ------------------------------------------------------------------------------
def params(pid: str) -> dict:
    return DEFAULTS | (db.meta(pid).get("mix") or {})


def set_params(pid: str, changes: dict) -> dict:
    p = params(pid) | {k: v for k, v in changes.items() if k in DEFAULTS}
    db.set_meta(pid, mix=p)
    return p


def mix_dir(pid: str, lang: str | None = None) -> Path:
    """Renders live per language: mix/<lang>/. A render from before languages were
    data (files directly in mix/) is moved into the primary language's folder."""
    lang = project.lang_or_primary(pid, lang)
    root = project.pdir(pid) / "mix"
    d = root / lang
    if not d.exists():
        d.mkdir(parents=True)
        if lang == project.get(pid)["tgt_lang"]:
            for name in ("mix.wav", "dub.wav", "fit.json"):
                if (root / name).exists():
                    (root / name).replace(d / name)
    return d


def render(pid: str, lang: str | None = None, update=lambda *a, **k: None) -> dict:
    lang = project.lang_or_primary(pid, lang)
    p = params(pid)
    d = project.pdir(pid)
    # A failed render must not leave the previous mix behind for export to pick up.
    for stale in ("mix.wav", "dub.wav", "fit.json"):
        (mix_dir(pid, lang) / stale).unlink(missing_ok=True)
    chars = cast.labels_of(pid)
    sents = project.sentences(pid, lang)
    takes = {t["sentence_id"]: t for t in voice.lines_takes(pid, chosen_only=True, lang=lang)}
    # a recurring part's lines use the takes chosen at its origin, placed here
    takes |= recurring.origin_takes(sents, lang)

    update(0.05, "decoding stems")
    background = decode(d / "background.flac")
    vocals = decode(d / "vocals.flac")
    total = max(len(background), len(vocals)) / SR
    n = int(total * SR)
    background = np.pad(background, (0, n - len(background)))
    vocals = np.pad(vocals, (0, n - len(vocals)))

    dubbed, extras, missing = [], [], []
    kept = []
    for s in sents:
        c = chars.get(s["speaker"])
        if c is not None and not c["important"]:
            extras.append(s)
            continue
        if s["mode"] == "keep":  # an interjection left in the original language
            kept.append(s)
            continue
        t = takes.get(s["id"])
        if t and t["text"] == s["tr"] and Path(t["path"]).exists():
            dubbed.append((s, t))
        else:
            missing.append(s)
    for s, t in dubbed:
        s["_take"] = t
        s["dur"] = float(t["dur_s"] or 0) or len(decode(t["path"])) / SR
    placements = fit([{"id": s["id"], "start": s["start"], "end": s["end"], "dur": s["dur"]} for s, _ in dubbed], total, p)

    dub = np.zeros(n, dtype=np.float32)
    report = []
    for k, ((s, t), pl) in enumerate(zip(dubbed, placements)):
        update(0.1 + 0.7 * k / max(1, len(dubbed)), f"placing line {k + 1}/{len(dubbed)}")
        f = pl["factor"]
        x = decode(t["path"], f"rubberband=tempo={f:.4f}:formant=preserved:window=short" if f > 1.001 else None)
        gain_db = 0.0
        if p["loudness_follow"]:
            ref = speech_db(vocals[int(s["start"] * SR):int(s["end"] * SR)])
            got = speech_db(x)
            if ref is not None and got is not None:
                gain_db = float(np.clip(ref - got, -12, 12))
        x = x * db_to_gain(gain_db)
        fade = int(FADE_S * SR)
        if len(x) > 2 * fade:
            ramp = np.linspace(0, 1, fade, dtype=np.float32)
            x[:fade] *= ramp
            x[-fade:] *= ramp[::-1]
        i0 = int(pl["start"] * SR)
        room = max(0, n - i0)  # a line pushed past the end of the clip is cut there
        if room < len(x):
            pl["clipped_s"] = round((len(x) - room) / SR, 2)
        dub[i0:i0 + min(room, len(x))] += x[:room]
        report.append(pl | {"speaker": s["speaker"], "gain_db": round(gain_db, 1), "tr": s["tr"], "src": s["text"],
                            "take_id": t["take_id"], "linked": (s.get("linked") or {}).get("title")})

    update(0.85, "mixing")
    # Original voice where it stays: extras' lines, dub gaps (missing takes), and
    # optionally non-speech sounds between lines.
    keep = np.zeros(n, dtype=np.float32)
    pad = int(0.15 * SR)
    spoken = np.zeros(n, dtype=bool)
    for s in sents:
        spoken[max(0, int(s["start"] * SR) - pad):int(s["end"] * SR) + pad] = True
    if p["keep_nonspeech"]:
        keep[~spoken] = db_to_gain(p["nonspeech_db"])
    for s in (extras if p["keep_extras"] else []) + missing + kept:
        keep[int(s["start"] * SR):int(s["end"] * SR)] = 1.0
    keep = _smooth(keep, int(0.02 * SR))
    original_voice = vocals * keep

    # Duck the background under the dub (50 ms attack, 300 ms release envelope).
    active = _envelope(np.abs(dub), int(0.05 * SR), int(0.3 * SR)) > 0.01
    duck = np.where(active, db_to_gain(-p["duck_db"]), 1.0).astype(np.float32)
    duck = _smooth(duck, int(0.08 * SR))
    mix = background * duck + dub + original_voice
    peak = float(np.max(np.abs(mix)) or 1.0)
    if peak > 0.98:  # never clip: scale the whole mix down, keeping its balance
        mix *= 0.98 / peak

    out = mix_dir(pid, lang)
    encode_wav(mix, out / "mix.wav")
    encode_wav(dub, out / "dub.wav")
    summary = {"rendered_at": time.time(), "lang": lang, "params": p, "lines": report, "duration": total,
               "counts": {"dubbed": len(dubbed), "extras": len(extras), "missing": len(missing), "kept": len(kept),
                          **{st: sum(1 for r in report if r["status"] == st)
                             for st in ("fits", "borrowed", "stretched", "squeezed", "overflow")}},
               "missing": [{"id": s["id"], "start": s["start"], "src": s["text"]} for s in missing]}
    (out / "fit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    update(1.0, "done")
    return summary["counts"]


def _smooth(x: np.ndarray, width: int) -> np.ndarray:
    if width < 2:
        return x
    k = np.ones(width, dtype=np.float32) / width
    return np.convolve(x, k, mode="same").astype(np.float32)


def _envelope(x: np.ndarray, attack: int, release: int) -> np.ndarray:
    """Peak envelope at 10 ms resolution: rises within ``attack``, falls over ``release``."""
    hop = int(0.01 * SR)
    m = len(x) // hop
    frames = x[: m * hop].reshape(m, hop).max(1)
    env = np.zeros(m, dtype=np.float32)
    a, r = np.exp(-hop / max(1, attack)), np.exp(-hop / max(1, release))
    level = 0.0
    for i, v in enumerate(frames):
        level = a * level + (1 - a) * v if v > level else r * level + (1 - r) * v
        env[i] = level
    return np.pad(np.repeat(env, hop), (0, len(x) - m * hop))


# ---- export ------------------------------------------------------------------------------
def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(items: list[tuple[float, float, str]], path: Path) -> None:
    lines = []
    for k, (a, b, text) in enumerate(items, 1):
        lines += [str(k), f"{srt_time(a)} --> {srt_time(b)}", text.strip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def export(pid: str, lang: str | None = None, update=lambda *a, **k: None) -> dict:
    lang = project.lang_or_primary(pid, lang)
    proj = project.get(pid)
    mdir = mix_dir(pid, lang)
    fitp = mdir / "fit.json"
    if not fitp.exists() or not (mdir / "mix.wav").exists():
        raise RuntimeError("render the mix first (the last render did not finish)")
    summary = json.loads(fitp.read_text(encoding="utf-8"))
    out = project.pdir(pid) / "export"
    out.mkdir(exist_ok=True)
    base = out / pid
    # Target subtitles follow where the dub actually plays (the original line's time
    # when a line is not dubbed, and the original words for lines kept in the original
    # language); source subtitles follow the source.
    placed = {r["id"]: r for r in summary["lines"]}
    sents = project.sentences(pid, lang)

    def said(s):
        return s["text"] if s["mode"] == "keep" else s["tr"]

    tgt = [(placed[s["id"]]["start"], placed[s["id"]]["end"], s["tr"]) if s["id"] in placed
           else (s["start"], s["end"], said(s)) for s in sents if said(s).strip()]
    src = [(s["start"], s["end"], s["text"]) for s in sents if s["text"].strip()]
    tracks = []
    for items, code in ((tgt, lang), (src, proj["src_lang"])):
        if items:
            path = out / f"{pid}.{code}.srt"
            write_srt(sorted(items), path)
            tracks.append((path, langs.iso3(code)))
    update(0.3, "encoding video")
    mp4 = out / f"{pid}.{lang}.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", proj["video"], "-i", str(mdir / "mix.wav")]
    for path, _ in tracks:
        cmd += ["-i", str(path)]
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-map", "0:a:0"]
    for k in range(len(tracks)):
        cmd += ["-map", f"{k + 2}:s:0"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text",
            "-metadata:s:a:0", f"language={langs.iso3(lang)}", "-metadata:s:a:0", f"title={langs.name(lang)} dub",
            "-metadata:s:a:1", f"language={langs.iso3(proj['src_lang'])}", "-metadata:s:a:1", "title=Original",
            "-disposition:a:0", "default", "-disposition:a:1", "0"]
    for k, (_, tag) in enumerate(tracks):
        cmd += [f"-metadata:s:s:{k}", f"language={tag}"]
    cmd += ["-shortest", str(mp4)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"ffmpeg export failed: {p.stderr[-500:]}")
    exports = db.meta(pid).get("exports") or {}
    db.set_meta(pid, exports=exports | {lang: {"mp4": str(mp4), "at": time.time()}})
    return {"mp4": str(mp4), "subtitles": [str(p) for p, _ in tracks]}
