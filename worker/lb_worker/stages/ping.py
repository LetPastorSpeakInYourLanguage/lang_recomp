"""Round-trip probe: proves the desktop -> Drive -> Colab -> Drive -> desktop path and
reports what hardware this session actually got."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time

from ..registry import stage


@stage("ping")
def ping(ctx) -> dict:
    info: dict = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "received_at": time.time(),
        "echo": ctx.job.get("params", {}).get("echo"),
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = torch.version.cuda
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            info["gpu"] = torch.cuda.get_device_name(0)
            info["vram_free_gb"] = round(free / 2**30, 2)
            info["vram_total_gb"] = round(total / 2**30, 2)
        else:
            info["gpu"] = None
    except ImportError:
        info["torch"] = None
    if shutil.which("nvidia-smi"):
        info["driver"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True,
        ).stdout.strip()
    ctx.log(f"ping: {info.get('gpu') or 'no GPU'}")
    (ctx.out / "ping.txt").write_text("pong\n")
    return info
