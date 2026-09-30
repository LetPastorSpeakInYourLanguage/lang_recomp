"""Where the notebook runs and what it runs on: Kaggle, Colab or a local Jupyter/server;
CPU, one GPU or two. Used by notebooks/lang_bridge.ipynb after its first cell has found
the code (that cell cannot import this module yet, so it detects the runtime itself with
the same rules as ``runtime()``).

Nothing here imports torch: the GPU choice (``CUDA_VISIBLE_DEVICES``) only works if it is
set before torch is first imported in the session.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEVICES = ("auto", "cpu", "1 GPU", "2 GPUs")
STORAGES = ("folder", "bucket")
HOMES = {"kaggle": "/kaggle/working", "colab": "/content"}


def runtime() -> str:
    """"kaggle", "colab" or "local". Kaggle sets KAGGLE_KERNEL_RUN_TYPE in every session
    (a /kaggle folder is no proof: Colab has one too); Colab is the one with google.colab."""
    if os.environ.get("KAGGLE_KERNEL_RUN_TYPE"):
        return "kaggle"
    try:
        if importlib.util.find_spec("google.colab") is not None:
            return "colab"
    except (ImportError, ValueError):
        pass
    return "local"


def home(rt: str, work_dir: str | None = None) -> Path:
    """The folder for the code, models and scratch files: WORK_DIR if set, else
    /kaggle/working, /content, or ~/lang-bridge on any other machine."""
    return Path(work_dir).expanduser() if work_dir else Path(HOMES.get(rt) or Path.home() / "lang-bridge")


def gpus() -> list[dict]:
    """NVIDIA GPUs as nvidia-smi sees them (no torch import): [{"name", "memory_gb"}]."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            found.append({"name": name.strip(), "memory_gb": round(float(mem) / 1024, 1)})
        except ValueError:
            continue
    return found


def choose_device(device: str, rt: str, found: list[dict]) -> tuple[int, list[str]]:
    """How many GPUs to use for the DEVICE setting, and warnings for the person."""
    device = (device or "auto").strip()
    if device not in DEVICES:
        raise ValueError(f"DEVICE must be one of: {', '.join(DEVICES)} (not {device!r})")
    have, warn = len(found), []
    if device == "cpu":
        return 0, warn
    want = {"auto": have, "1 GPU": 1, "2 GPUs": 2}[device]
    if have == 0:
        warn.append({"kaggle": "No GPU: in Settings (right panel) → Accelerator, choose GPU T4 x2, then run again.",
                     "colab": "No GPU: Runtime → Change runtime type → T4 GPU, then run again."}.get(
            rt, "No NVIDIA GPU found: running on the CPU (slow for separation and voices)."))
        return 0, warn
    if want > have:
        warn.append(f"DEVICE asks for {want} GPUs but this machine has {have}: using {have}.")
        want = have
    if rt == "kaggle" and have == 1 and device in ("auto", "2 GPUs"):
        warn.append("Kaggle has one GPU here: Accelerator 'GPU T4 x2' gives two (voicing and scoring twice as fast).")
    return want, warn


def apply_device(n_gpus: int, have: int) -> None:
    """Show torch only the GPUs to use. This must happen before torch is imported: once it
    is, the choice is fixed for the session."""
    if "torch" in sys.modules:
        current = os.environ.get("CUDA_VISIBLE_DEVICES")
        seen = have if current is None else len([x for x in current.split(",") if x.strip()])
        if seen != n_gpus:
            raise SystemExit("PyTorch is already loaded in this session, so DEVICE cannot change now: restart "
                             "the session (Colab: Runtime → Restart session; Kaggle/Jupyter: Restart kernel) "
                             "and Run all again.")
        return
    os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in range(n_gpus))


def profile(n_gpus: int) -> dict:
    """Run options that suit the machine: a CPU gets the faster Whisper."""
    return {} if n_gpus else {"asr_model": "large-v3-turbo"}


def check_folder(path: Path) -> None:
    """The workspace must be writable (Kaggle's /kaggle/input is not)."""
    if path.as_posix().startswith("/kaggle/input"):
        raise SystemExit(f"{path} is read-only on Kaggle: use STORAGE = bucket (the bucket is the workspace), "
                         "or a WORKSPACE under /kaggle/working (lost when the session ends).")
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".lb-write-test"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        raise SystemExit(f"cannot write into {path}: {e}")


def mount_drive(*paths: str) -> None:
    """On Colab, connect Google Drive when a setting points into it."""
    if any(p and p.startswith("/content/drive") for p in paths) and not Path("/content/drive/MyDrive").exists():
        from google.colab import drive  # type: ignore

        drive.mount("/content/drive")


def _pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *args], check=True)


def ensure_local(n_gpus: int, log=print) -> None:
    """On a machine of your own: Python ≥ 3.10, PyTorch and ffmpeg (Colab and Kaggle
    have them). The stages install the rest the first time they run."""
    if sys.version_info < (3, 10):
        raise SystemExit(f"Python 3.10 or newer is needed (this is {sys.version.split()[0]}).")
    if importlib.util.find_spec("torch") is None:
        index = "https://download.pytorch.org/whl/cu128" if n_gpus else "https://download.pytorch.org/whl/cpu"
        log(f"installing PyTorch ({'CUDA' if n_gpus else 'CPU'}) — once, about {'3' if n_gpus else '0.3'} GB")
        _pip("torch", "torchaudio", "--index-url", index)
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        log("ffmpeg not found: using a static build (installed once)")
        _pip("static-ffmpeg")
        import static_ffmpeg  # type: ignore

        static_ffmpeg.add_paths()


def _ram_gb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / 2**30, 1)
    except ImportError:
        return None


def mask(secret: str | None) -> str:
    """A secret as it may be printed: its first 4 characters."""
    return f"{secret[:4]}…" if secret else "(not set)"


def card(rt: str, root: Path, found: list[dict], n_gpus: int, storage: str, workspace: Path, bucket: str | None,
         token: str | None) -> str:
    """What the run will use, printed before it starts."""
    use = found[:n_gpus]
    where = f"hf://buckets/{bucket}, worked on in {workspace}" if storage == "bucket" else str(workspace)
    lines = [f"runtime   {rt} · Python {sys.version.split()[0]}",
             "device    " + (", ".join(f"{g['name']} ({g['memory_gb']} GB)" for g in use) if use else "CPU"),
             f"RAM       {_ram_gb() or '?'} GB · free disk {shutil.disk_usage(root).free / 2**30:.0f} GB in {root}",
             f"workspace {where}" + (f" · backed up to hf://buckets/{bucket}" if bucket and storage == "folder" else ""),
             f"HF_TOKEN  {mask(token)}"]
    return "\n".join(lines)


def setup(rt: str, root: Path, device: str = "auto", storage: str = "folder", workspace: str = "",
          bucket: str = "", token: str = "", log=print) -> dict:
    """Everything the run needs from this machine, checked before any work starts.

    Every run has a workspace, the team's working folder, even when all its videos come
    from links: STORAGE = folder → WORKSPACE (a Drive folder on Colab, any folder on your
    machine); STORAGE = bucket → the bucket is the workspace, worked on in a local copy
    (WORKSPACE if set, else WORK_DIR/workspace). ``token`` and ``bucket`` come from the
    notebook's settings (HF_TOKEN in the environment is used when the setting is empty)."""
    storage = (storage or "folder").strip()
    if storage not in STORAGES:
        raise SystemExit(f"STORAGE must be one of: {', '.join(STORAGES)} (not {storage!r})")
    token = (token or "").strip() or os.environ.get("HF_TOKEN") or None
    bucket = (bucket or "").strip().removeprefix("hf://buckets/").strip("/") or None
    workspace = (workspace or "").strip()
    if storage == "folder" and not workspace:
        raise SystemExit("Set WORKSPACE: the team's working folder (videos, links and all results live there; it may "
                         "start empty). On Colab, a Drive folder such as /content/drive/MyDrive/LangBridge/<team>; "
                         "on Kaggle, use STORAGE = bucket.")
    if storage == "bucket" and not bucket:
        raise SystemExit("STORAGE is 'bucket': set BUCKET to your Hugging Face bucket (namespace/name).")
    if bucket and bucket.count("/") < 1:
        raise SystemExit(f"BUCKET must look like namespace/name (not {bucket!r}).")
    if bucket and not token:
        raise SystemExit("A bucket needs HF_TOKEN: a Hugging Face token that can write to it.")
    root.mkdir(parents=True, exist_ok=True)
    if rt == "colab":
        mount_drive(workspace)
    found = gpus()
    n, warnings = choose_device(device, rt, found)
    apply_device(n, len(found))
    if rt == "local":
        ensure_local(n, log)
    ws = Path(workspace).expanduser() if workspace else root / "workspace"
    if rt == "kaggle" and storage == "folder" and not ws.as_posix().startswith("/kaggle/input"):
        warnings.append("A folder on Kaggle is lost when the session ends: STORAGE = bucket keeps the workspace.")
    check_folder(ws)
    os.environ["LB_WORK"] = str(root / "scratch")
    if token:
        os.environ["HF_TOKEN"] = token
    log(card(rt, root, found, n, storage, ws, bucket, token))
    for w in warnings:
        log("⚠ " + w)
    return {"runtime": rt, "root": root, "workspace": ws, "bucket": bucket, "token": token, "gpus": n,
            "storage": storage, "options": profile(n), "warnings": warnings}
