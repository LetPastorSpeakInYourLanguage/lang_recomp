"""What every bench needs: a GPU sampler, audio comparisons, results on disk."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

SR = 44100


def parse_smi(line: str) -> tuple[int, float, float, float] | None:
    """One ``nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total
    --format=csv,noheader,nounits`` line → (gpu, util %, used GB, total GB)."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 4:
        return None
    try:
        i, util, used, total = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    except ValueError:
        return None
    return i, util, used / 1024, total / 1024


class GpuSampler:
    """Samples every GPU twice a second while a block runs (across processes too):

        with GpuSampler() as g:
            work()
        g.stats() → {"0": {"util_mean", "util_max", "mem_max_gb", "mem_total_gb"}, …}
    """

    def __init__(self, every_ms: int = 500):
        self.every_ms, self.samples = every_ms, []
        self._proc = self._thread = None

    def __enter__(self):
        if shutil.which("nvidia-smi"):
            self._proc = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits", f"-lms={self.every_ms}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            self._thread = threading.Thread(target=self._read, daemon=True)
            self._thread.start()
        self.t0 = time.time()
        return self

    def _read(self):
        for line in self._proc.stdout:
            s = parse_smi(line)
            if s:
                self.samples.append(s)

    def __exit__(self, *exc):
        self.seconds = time.time() - self.t0
        if self._proc:
            self._proc.terminate()
            self._thread.join(timeout=2)
        return False

    def stats(self) -> dict:
        out: dict[str, dict] = {}
        for i in sorted({s[0] for s in self.samples}):
            mine = [s for s in self.samples if s[0] == i]
            out[str(i)] = {"util_mean": round(float(np.mean([s[1] for s in mine])), 1),
                           "util_max": max(s[1] for s in mine),
                           "mem_max_gb": round(max(s[2] for s in mine), 2),
                           "mem_total_gb": round(mine[0][3], 1)}
        return out


def read_audio(path: str | Path, sr: int = SR, channels: int = 2) -> np.ndarray:
    """Any audio/video file → float32 [samples, channels] at ``sr``."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True)
    if p.returncode:
        raise RuntimeError(f"ffmpeg could not decode {path}: {p.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, channels).copy()


def diff_db(ref: np.ndarray, x: np.ndarray) -> float:
    """Energy of the difference relative to the reference, in dB (−∞ = identical,
    −50 dB = inaudible difference, 0 dB = as loud as the signal itself)."""
    n = min(len(ref), len(x))
    err = float(np.sum((ref[:n] - x[:n]) ** 2))
    sig = float(np.sum(ref[:n] ** 2)) or 1e-12
    return round(float(10 * np.log10(max(err, 1e-20) / sig)), 1)


def snr_db(ref: np.ndarray, x: np.ndarray) -> float:
    """Signal-to-difference ratio: how close ``x`` is to ``ref`` (higher is closer)."""
    return -diff_db(ref, x)


def ffmpeg(*args: str) -> None:
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"ffmpeg {' '.join(args)[:200]} failed: {p.stderr[-400:]}")


def save(out: Path, name: str, result: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{name}.json"
    f.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return f


def table(rows: list[dict], cols: list[str]) -> str:
    """A plain-text table for the notebook output (and for pasting back)."""
    cells = [[str(r.get(c, "")) for c in cols] for r in rows]
    w = [max(len(c), *(len(x[i]) for x in cells)) if cells else len(c) for i, c in enumerate(cols)]
    line = lambda xs: "  ".join(x.ljust(w[i]) for i, x in enumerate(xs))  # noqa: E731
    return "\n".join([line(cols), line(["-" * n for n in w]), *(line(x) for x in cells)])
