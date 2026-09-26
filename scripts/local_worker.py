"""Run a worker on this PC against the app's local job folder.

    python scripts/local_worker.py              (or double-click Local-Worker.cmd)
    python scripts/local_worker.py --setup-xpu  one-time: Intel Arc GPU environment

Everything it installs or downloads stays inside that folder (default
D:\\LangBridgeLocal, set in the app under Settings):

    <folder>/.venv     its own Python environment (CPU PyTorch): stage installs
                       never touch the Python the app runs on
    <folder>/.venv-xpu optional Intel Arc environment (PyTorch XPU build), used
                       instead of .venv whenever it exists
    <folder>/cache     models (Hugging Face, separator, torch hub) and pip's cache
    <folder>/jobs      job bundles, same protocol as the Drive folder
    <folder>/.scratch  working copies while a job runs

With .venv-xpu, separation, alignment and voicing run on the Arc GPU; without it
everything runs on the CPU (voicing is then very slow: prefer Colab for it).
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from app import settings  # noqa: E402

CPU_STAGES = "ping,prefetch,separate,asr,align,diarize,voice"


def setup_xpu(root: Path) -> None:
    """Create <folder>/.venv-xpu with PyTorch's Intel XPU build (Intel Arc / Core
    Ultra graphics). Needs a recent Intel GPU driver; downloads about 2 GB."""
    env_dir = root / ".venv-xpu"
    py = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        venv.create(env_dir, with_pip=True)
    pip = [str(py), "-m", "pip", "install", "--retries", "10", "--timeout", "60"]
    subprocess.run([*pip, "--upgrade", "pip"], check=True)
    subprocess.run([*pip, "torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/xpu"], check=True)
    subprocess.run([*pip, "numpy", "soundfile", "huggingface_hub"], check=True)
    ok = subprocess.run([str(py), "-c", "import torch; print(torch.xpu.is_available())"],
                        capture_output=True, text=True).stdout.strip()
    if ok == "True":
        print("Intel GPU ready: Local-Worker.cmd will use it from now on.")
    else:
        print("PyTorch installed, but no Intel GPU is visible (update the Intel graphics driver?). "
              f"Delete {env_dir} to go back to the CPU environment.")


def main() -> None:
    root = settings.local_root()
    if root is None:
        sys.exit("No 'This PC' job folder is configured. Add one in the app: Settings.")
    root.mkdir(parents=True, exist_ok=True)
    if "--setup-xpu" in sys.argv[1:]:
        setup_xpu(root)
        return
    # Prefer the Intel Arc environment (PyTorch XPU build) when it has been set up:
    # separation and voicing run about 6x faster there than on the CPU.
    exe = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    xpu = root / ".venv-xpu" / exe
    env_dir = root / (".venv-xpu" if xpu.exists() else ".venv")
    py = env_dir / exe
    print(f"Python environment: {env_dir.name}")
    if not py.exists():
        print(f"Creating the worker's Python environment in {env_dir} (one time, a few minutes)...")
        venv.create(env_dir, with_pip=True)
        pip = [str(py), "-m", "pip", "install", "-q"]
        subprocess.run([*pip, "--upgrade", "pip"], check=True)
        subprocess.run([*pip, "torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu"], check=True)
        subprocess.run([*pip, "numpy", "soundfile", "huggingface_hub"], check=True)

    cache = root / "cache"
    env = os.environ | {
        "LB_CACHE": str(cache),
        # Hub cache only (not HF_HOME), so the token from `hf auth login` is still found.
        "HF_HUB_CACHE": str(cache / "hf" / "hub"),
        "TORCH_HOME": str(cache / "torch"),
        "PIP_CACHE_DIR": str(cache / "pip"),
        "PYTHONPATH": str(REPO / "worker"),
        "PYTHONUNBUFFERED": "1",
        # Slow/flaky links: plain HTTP downloads resume cleanly; the chunked Xet CDN
        # path failed mid-download here. Longer timeouts ride out stalls.
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_DOWNLOAD_TIMEOUT": "120",
        "HF_HUB_ETAG_TIMEOUT": "60",
    }
    print(f"Local worker on {root}  (stages: {CPU_STAGES}) - close this window to stop.")
    cmd = [str(py), "-m", "lb_worker.loop", "--root", str(root), "--scratch", str(root / ".scratch"),
           "--poll", "3", "--stages", CPU_STAGES]
    raise SystemExit(subprocess.call(cmd, env=env))


if __name__ == "__main__":
    main()
