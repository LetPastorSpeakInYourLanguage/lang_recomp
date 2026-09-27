"""E2: is "the same video" recognised across copies, formats, trims and intros?

For each main video: an exact copy, a second download at another resolution, a
re-encode, an MP3, a copy with the first 10 s cut, and one with 7 s of another video in
front. Each is matched against the main video's fingerprint (Chromaprint, app.fingerprint)
and must be found with the right time offset; other videos (negatives) must never match.
Quick hashes (size + first and last 4 MB) must be equal for the exact copy only. Link
identity (extractor:id) must be equal across the usual forms of one YouTube link.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from .common import ffmpeg, save, table

CHUNK = 4 << 20
WINDOW = (30.0, 90.0)  # the part of a variant that is looked up (seconds)
# offset = where the variant's audio sits in the original, minus where it sits in the variant
EXPECTED = {"copy": 0.0, "redownload": 0.0, "reencode": 0.0, "mp3": 0.0, "trim10": 10.0, "intro7": -7.0}


def quick_hash(path: str | Path) -> str:
    """SHA-256 of the size and the first and last 4 MB: equal for copies of one file,
    reading at most 8 MB (a streamed Drive file is not downloaded whole)."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(p, "rb") as f:
        h.update(f.read(CHUNK))
        if size > CHUNK:
            f.seek(max(CHUNK, size - CHUNK))
            h.update(f.read(CHUNK))
    return h.hexdigest()


def link_forms(video_id: str) -> list[str]:
    return [f"https://www.youtube.com/watch?v={video_id}", f"https://youtu.be/{video_id}",
            f"https://m.youtube.com/watch?v={video_id}&t=30s", f"https://www.youtube.com/watch?v={video_id}&list=WL",
            f"https://www.youtube.com/embed/{video_id}"]


def link_id(url: str) -> str | None:
    """yt-dlp's extractor and id for a link, without downloading (e.g. ``Youtube:abc``)."""
    p = subprocess.run([sys.executable, "-m", "yt_dlp", "--skip-download", "--no-playlist", "--no-warnings",
                        "--print", "%(extractor_key)s:%(id)s", "--", url], capture_output=True, text=True)
    out = p.stdout.strip().splitlines()
    return out[-1] if p.returncode == 0 and out else None


def ensure_fingerprints(log=print) -> str:
    """ffmpeg's chromaprint muxer, or fpcalc (installed with apt on Colab/Kaggle)."""
    from app import fingerprint as fp

    probe = Path(tempfile.gettempdir()) / "lb_fp_probe.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(probe))
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(probe), "-f", "chromaprint", "-fp_format", "raw", "-"],
                       capture_output=True)
    if p.returncode == 0:
        return "ffmpeg"
    if not shutil.which("fpcalc"):
        log("this ffmpeg has no chromaprint: installing fpcalc (libchromaprint-tools)")
        subprocess.run(["apt-get", "install", "-y", "-qq", "libchromaprint-tools"], capture_output=True)
    fp.fpcalc(probe)  # raises if still unavailable
    return "fpcalc"


def make_variants(video: Path, other: Path, out: Path, redownload: Path | None) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    v = {"copy": out / "copy.mp4", "reencode": out / "reencode.mp4", "mp3": out / "audio.mp3",
         "trim10": out / "trim10.m4a", "intro7": out / "intro7.m4a"}
    if not v["copy"].exists():
        shutil.copyfile(video, v["copy"])
    if not v["reencode"].exists():
        ffmpeg("-i", str(video), "-vf", "scale=-2:240", "-c:v", "libx264", "-crf", "32", "-preset", "veryfast",
               "-c:a", "aac", "-b:a", "64k", str(v["reencode"]))
    if not v["mp3"].exists():
        ffmpeg("-i", str(video), "-vn", "-c:a", "libmp3lame", "-b:a", "128k", str(v["mp3"]))
    if not v["trim10"].exists():
        ffmpeg("-ss", "10", "-i", str(video), "-vn", "-c:a", "aac", "-b:a", "96k", str(v["trim10"]))
    if not v["intro7"].exists():
        ffmpeg("-t", "7", "-i", str(other), "-i", str(video), "-filter_complex",
               "[0:a]aresample=44100,aformat=channel_layouts=stereo[a0];[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];"
               "[a0][a1]concat=n=2:v=0:a=1[a]", "-map", "[a]", "-c:a", "aac", "-b:a", "96k", str(v["intro7"]))
    if redownload is not None:
        v["redownload"] = redownload
    return v


def match(variant_fp: np.ndarray, source_fp: np.ndarray, window=WINDOW) -> tuple[float | None, float]:
    """(offset in seconds, mean differing bits of the best place) of the variant's window
    inside the source; offset None when the window is not found at all."""
    from app import fingerprint as fp

    a, part = fp.part_frames(variant_fp, *window)
    found = fp.find_part(part, source_fp, max_bits=32.0)
    if not found:
        return None, 32.0
    frame, bits = found[0]
    return fp.to_seconds(frame - a), bits


def run(mains: list[dict], negatives: list[Path], out: Path, log=print) -> dict:
    """``mains``: [{"name", "video": Path, "redownload": Path|None, "other": Path, "links": [..]}]."""
    from app import fingerprint as fp

    method = ensure_fingerprints(log)
    neg_fps = {p.name if p.name != "video.mp4" else p.parent.name: fp.compute(p) for p in negatives}
    rows, links = [], []
    for m in mains:
        src_fp = fp.compute(m["video"])
        src_hash = quick_hash(m["video"])
        for kind, path in make_variants(m["video"], m["other"], out / "variants" / m["name"], m.get("redownload")).items():
            vfp = fp.compute(path)
            off, bits = match(vfp, src_fp)
            neg_bits = min((match(vfp, n)[1] for n in neg_fps.values()), default=None)
            exp = EXPECTED[kind]
            rows.append({"video": m["name"], "variant": kind, "same_quick_hash": quick_hash(path) == src_hash,
                         "offset_s": off, "expected_s": exp,
                         "offset_ok": off is not None and abs(off - exp) <= 0.2 + fp.FRAME_S,
                         "bits": bits, "best_negative_bits": neg_bits})
            log(f"{m['name']} {kind}: {rows[-1]}")
        for u in m.get("links", []):
            links.append({"video": m["name"], "link": u, "id": link_id(u)})
    pos = [r["bits"] for r in rows]
    neg = [r["best_negative_bits"] for r in rows if r["best_negative_bits"] is not None]
    result = {"method": method, "rows": rows, "links": links,
              "positives_max_bits": max(pos) if pos else None, "negatives_min_bits": min(neg) if neg else None,
              "all_offsets_ok": all(r["offset_ok"] for r in rows),
              "quick_hash_only_for_copy": all(r["same_quick_hash"] == (r["variant"] == "copy") for r in rows),
              "link_ids_agree": all(len({x["id"] for x in links if x["video"] == m["name"]}) == 1 for m in mains)}
    if pos and neg:
        result["threshold_bits"] = round((max(pos) + min(neg)) / 2, 1)  # the middle of the gap
        result["separated"] = max(pos) < min(neg)
    save(out, "e2_identity", result)
    print(table(rows, ["video", "variant", "same_quick_hash", "offset_s", "expected_s", "offset_ok", "bits",
                       "best_negative_bits"]))
    print({k: v for k, v in result.items() if k not in ("rows", "links")})
    return result
