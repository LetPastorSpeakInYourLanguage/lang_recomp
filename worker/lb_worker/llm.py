"""A local instruction model for the run, behind one small interface (WORKSPACE_PLAN Phase 5).

It is llama.cpp's own server, prebuilt (no compiling, and nothing touches the session's
PyTorch), with a quantised Gemma 4 (Google's QAT Q4_0 GGUF, Apache 2.0, no sign-up):
- parallel slots with continuous batching: several requests are generated together;
- JSON-schema-constrained output: an answer always parses, nothing is retried;
- loaded once for all the work of a run, stopped before the GPU is needed for voicing.

The release archive is cached (Drive on Colab, ``cache_dir``) and unpacked on local disk
each session; the model is downloaded to local disk too. A binary run from, or a 5 GB
model mapped from, a Drive mount is slow or refused.

    with Server("gemma-4-e4b", work_dir, gpu=0, log=log) as llm:
        answers = llm.map(lambda req: llm.chat(req, schema), requests)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

LLAMA_BUILD = "b11298"  # llama.cpp release of 2026-09-30
RELEASE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{build}/{asset}"
MODELS = {
    "gemma-4-e4b": {"repo": "google/gemma-4-E4B-it-qat-q4_0-gguf", "file": "gemma-4-E4B_q4_0-it.gguf",
                    "name": "Gemma 4 E4B", "gb": 4.9},
    "gemma-4-e2b": {"repo": "google/gemma-4-E2B-it-qat-q4_0-gguf", "file": "gemma-4-E2B_q4_0-it.gguf",
                    "name": "Gemma 4 E2B", "gb": 3.2},
}
DEFAULT_MODEL = "gemma-4-e4b"
CPU_MODEL = "gemma-4-e2b"  # a machine without a GPU runs the smaller one


def cuda_major() -> int | None:
    """The CUDA major version this machine's PyTorch (else its driver) uses; None without one."""
    try:
        import torch

        if torch.cuda.is_available() and torch.version.cuda:
            return int(torch.version.cuda.split(".")[0])
    except ImportError:
        pass
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for part in out.split("CUDA Version:")[1:2]:
        return int(part.strip().split(".")[0])
    return None


def asset(system: str | None = None, cuda: int | None = None, gpu: bool = True) -> str:
    """The release file for this machine: CUDA 12/13 on Linux (Colab, Kaggle), Vulkan on a
    Windows GPU (the Intel Arc here), otherwise the CPU build."""
    system = system or platform.system()
    b = LLAMA_BUILD
    if system == "Linux":
        if gpu and cuda:
            return f"llama-{b}-bin-ubuntu-cuda-{'13.4' if cuda >= 13 else '12.8'}-x64.tar.gz"
        return f"llama-{b}-bin-ubuntu-x64.tar.gz"
    if system == "Windows":
        return f"llama-{b}-bin-win-{'vulkan' if gpu else 'cpu'}-x64.zip"
    if system == "Darwin":
        return f"llama-{b}-bin-macos-{'arm64' if platform.machine() == 'arm64' else 'x64'}.tar.gz"
    raise RuntimeError(f"no llama.cpp build for {system}")


def fetch_build(name: str, cache: Path, dest: Path, log=print) -> Path:
    """The llama-server program: the archive from the cache (downloaded once), unpacked into
    ``dest`` on local disk."""
    exe_name = "llama-server.exe" if name.endswith(".zip") else "llama-server"
    here = dest / name.removesuffix(".zip").removesuffix(".tar.gz")
    found = next(here.rglob(exe_name), None) if here.exists() else None
    if found:
        return found
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.exists():
        log(f"downloading llama.cpp {LLAMA_BUILD} ({name})")
        tmp = archive.with_suffix(archive.suffix + ".part")
        with requests.get(RELEASE_URL.format(build=LLAMA_BUILD, asset=name), stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        os.replace(tmp, archive)
    shutil.rmtree(here, ignore_errors=True)
    here.mkdir(parents=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(here)
    else:
        with tarfile.open(archive) as t:
            t.extractall(here, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    found = next(here.rglob(exe_name), None)
    if not found:
        raise RuntimeError(f"{name} has no {exe_name}")
    found.chmod(0o755)
    return found


def fetch_model(key: str, dest: Path, log=print) -> Path:
    from huggingface_hub import hf_hub_download

    m = MODELS[key]
    if not (dest / m["file"]).exists():
        log(f"downloading {m['name']} ({m['gb']} GB, once per session)")
    return Path(hf_hub_download(m["repo"], m["file"], local_dir=str(dest)))


def _cuda_lib_dirs() -> list[str]:
    """CUDA runtime/cuBLAS the prebuilt server links to: the ones PyTorch's wheels ship
    (site-packages/nvidia/*/lib), so no system CUDA toolkit is needed."""
    dirs = []
    for sp in map(Path, sys.path):
        nv = sp / "nvidia"
        if nv.is_dir():
            dirs += [str(p) for p in nv.glob("*/lib") if p.is_dir()]
    return dirs


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, model: str, work_dir: Path, cache: Path | None = None, gpu: int | None = 0,
                 slots: int = 4, ctx_per_slot: int = 4096, log=print, start_timeout: float = 900):
        if model not in MODELS:
            raise ValueError(f"unknown model {model!r}; choose one of: {', '.join(MODELS)}")
        self.model, self.work, self.gpu, self.slots = model, Path(work_dir), gpu, slots
        self.cache = Path(cache) if cache else self.work / "cache"
        self.ctx, self.log, self.start_timeout = ctx_per_slot * slots, log, start_timeout
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.tokens = 0
        self.lock = threading.Lock()

    @property
    def name(self) -> str:
        return MODELS[self.model]["name"]

    def command(self, exe: Path, gguf: Path, port: int) -> list[str]:
        return [str(exe), "-m", str(gguf), "--host", "127.0.0.1", "--port", str(port),
                "-np", str(self.slots), "-c", str(self.ctx), "--jinja",
                "-ngl", "99" if self.gpu is not None else "0"]

    def start(self) -> "Server":
        self.work.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        cuda = cuda_major() if self.gpu is not None else None
        exe = fetch_build(asset(cuda=cuda, gpu=self.gpu is not None), self.cache, self.work / "llama.cpp", self.log)
        gguf = fetch_model(self.model, self.work / "models", self.log)
        port = _free_port()
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = os.pathsep.join([str(exe.parent), *_cuda_lib_dirs(), env.get("LD_LIBRARY_PATH", "")])
        if self.gpu is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu)
        self.server_log = self.work / "llama-server.log"
        fh = open(self.server_log, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(self.command(exe, gguf, port), stdout=fh, stderr=subprocess.STDOUT, env=env)
        self.url = f"http://127.0.0.1:{port}"
        t0 = time.time()
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"the model server stopped at start: {self._tail()}")
            try:
                if requests.get(self.url + "/health", timeout=5).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.time() - t0 > self.start_timeout:
                self.stop()
                raise RuntimeError(f"the model server did not start in {self.start_timeout:.0f} s: {self._tail()}")
            time.sleep(1)
        self.log(f"{self.name} ready in {time.time() - t0:.0f} s ({'GPU ' + str(self.gpu) if self.gpu is not None else 'CPU'},"
                 f" {self.slots} at a time)")
        return self

    def _tail(self) -> str:
        try:
            return " | ".join(self.server_log.read_text(encoding="utf-8", errors="replace").splitlines()[-6:])[-600:]
        except OSError:
            return "(no server log)"

    def chat(self, messages: list[dict] | str, schema: dict | None = None, max_tokens: int = 1024,
             temperature: float = 0.3, full: bool = False):
        """One answer; with ``schema`` the answer is JSON of that shape, parsed (a JSON grammar
        slows the large Gemma vocabulary down and can run into endless whitespace: plain text
        parsed by the caller is the faster choice). ``full``: {text, finish} (finish
        "length" = cut off at max_tokens)."""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False}}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
        r = requests.post(self.url + "/v1/chat/completions", json=body, timeout=600)
        r.raise_for_status()
        data = r.json()
        with self.lock:
            self.tokens += int((data.get("usage") or {}).get("completion_tokens") or 0)
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        if full:
            return {"text": text, "finish": choice.get("finish_reason")}
        return json.loads(text) if schema else text

    def generate(self, prompt: str, schema: dict | None = None):
        return self.chat(prompt, schema)

    def map(self, fn, items: list) -> list:
        """``fn`` over ``items``, as many at once as the server has slots; results in order,
        an exception in place of a failed item."""
        def safe(x):
            try:
                return fn(x)
            except Exception as e:  # one bad request never stops the others
                return e

        with ThreadPoolExecutor(max_workers=self.slots) as ex:
            return list(ex.map(safe, items))

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def __enter__(self) -> "Server":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
