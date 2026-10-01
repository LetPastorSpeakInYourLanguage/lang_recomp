"""The notebooks run anywhere: runtime and device detection, settings-only secrets, and
the notebooks themselves (worker/lb_worker/env.py, scripts/build_notebook.py)."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

from lb_worker import deps, env, research  # noqa: E402

import build_notebook  # noqa: E402

T4 = {"name": "Tesla T4", "memory_gb": 15.0}


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("KAGGLE_KERNEL_RUN_TYPE", "CUDA_VISIBLE_DEVICES", "LB_WORK", "HF_TOKEN", "LB_YT_COOKIES"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_runtime(clean_env):
    real = importlib.util.find_spec
    clean_env.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "google.colab" else real(n, *a))
    assert env.runtime() == "local"
    clean_env.setattr(importlib.util, "find_spec", lambda n, *a: object() if n == "google.colab" else real(n, *a))
    assert env.runtime() == "colab"
    clean_env.setenv("KAGGLE_KERNEL_RUN_TYPE", "Interactive")
    assert env.runtime() == "kaggle"  # Kaggle wins even where google.colab happens to be installed


def test_home():
    assert env.home("kaggle") == Path("/kaggle/working")
    assert env.home("colab") == Path("/content")
    assert env.home("local") == Path.home() / "lang-bridge"
    assert env.home("colab", "/tmp/x") == Path("/tmp/x")


def test_choose_device():
    assert env.choose_device("auto", "kaggle", [T4, T4]) == (2, [])
    n, warn = env.choose_device("auto", "kaggle", [T4])
    assert n == 1 and "T4 x2" in warn[0]
    assert env.choose_device("auto", "colab", [T4]) == (1, [])
    assert env.choose_device("1 GPU", "kaggle", [T4, T4]) == (1, [])
    assert env.choose_device("cpu", "kaggle", [T4, T4]) == (0, [])
    n, warn = env.choose_device("2 GPUs", "colab", [T4])
    assert n == 1 and "using 1" in warn[0]
    n, warn = env.choose_device("auto", "colab", [])
    assert n == 0 and "T4 GPU" in warn[0]
    assert env.choose_device("auto", "local", [])[0] == 0
    with pytest.raises(ValueError):
        env.choose_device("gpu", "local", [])


def test_apply_device(clean_env):
    clean_env.delitem(sys.modules, "torch", raising=False)
    env.apply_device(1, 2)
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0"
    env.apply_device(0, 2)
    assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
    clean_env.setitem(sys.modules, "torch", object())  # loaded already: only the same choice is possible
    clean_env.delenv("CUDA_VISIBLE_DEVICES")
    env.apply_device(2, 2)
    with pytest.raises(SystemExit, match="restart"):
        env.apply_device(1, 2)


def _setup(tmp_path, monkeypatch, **kw):
    found = kw.pop("found", [])
    monkeypatch.setattr(env, "gpus", lambda: found)
    monkeypatch.setattr(env, "ensure_local", lambda *a: None)
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    logs = []
    args = dict(rt="local", root=tmp_path / "home", device="auto", storage="folder", workspace="", bucket="", token="")
    args.update(kw)
    return env.setup(**args, log=logs.append), "\n".join(logs)


def test_setup_needs_a_workspace_folder(tmp_path, clean_env):
    with pytest.raises(SystemExit, match="Set WORKSPACE"):
        _setup(tmp_path, clean_env)  # even for links only: results always belong to a folder


def test_setup_folder(tmp_path, clean_env):
    m, log = _setup(tmp_path, clean_env, workspace=str(tmp_path / "Preaching"), token="hf_secretvalue123")
    assert m["workspace"] == tmp_path / "Preaching" and m["workspace"].is_dir()
    assert m["gpus"] == 0 and m["options"] == {"asr_model": "large-v3-turbo"}  # CPU: the faster Whisper
    assert os.environ["LB_WORK"] == str(tmp_path / "home" / "scratch")
    assert os.environ["HF_TOKEN"] == "hf_secretvalue123"
    assert "hf_s…" in log and "secretvalue" not in log  # the token is never printed


def test_setup_bucket(tmp_path, clean_env):
    with pytest.raises(SystemExit, match="set BUCKET"):
        _setup(tmp_path, clean_env, storage="bucket")
    with pytest.raises(SystemExit, match="HF_TOKEN"):
        _setup(tmp_path, clean_env, storage="bucket", bucket="org/runs")
    with pytest.raises(SystemExit, match="namespace/name"):
        _setup(tmp_path, clean_env, storage="bucket", bucket="runs", token="hf_x")
    m, log = _setup(tmp_path, clean_env, storage="bucket", bucket="hf://buckets/org/runs/", token="hf_x",
                    found=[T4, T4], rt="kaggle")
    assert m["bucket"] == "org/runs" and m["workspace"] == tmp_path / "home" / "workspace" and m["gpus"] == 2
    assert "hf://buckets/org/runs" in log and "Tesla T4" in log
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "0,1"


def test_setup_token_from_environment(tmp_path, clean_env):
    clean_env.setenv("HF_TOKEN", "hf_fromserver")
    m, _ = _setup(tmp_path, clean_env, workspace=str(tmp_path / "ws"))
    assert m["token"] == "hf_fromserver"


def test_youtube_cookies_are_checked_and_only_a_copy_is_used(tmp_path, clean_env):
    with pytest.raises(SystemExit, match="YT_COOKIES"):
        _setup(tmp_path, clean_env, workspace=str(tmp_path / "ws"), yt_cookies=str(tmp_path / "missing.txt"))
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    clean_env.setattr(deps.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    _, log = _setup(tmp_path, clean_env, workspace=str(tmp_path / "ws"), yt_cookies=str(jar))
    assert os.environ["LB_YT_COOKIES"] == str(jar) and "cookies" in log
    args = deps.yt_cookies()
    assert args[0] == "--cookies" and Path(args[1]) != jar and Path(args[1]).read_text() == jar.read_text()
    _setup(tmp_path, clean_env, workspace=str(tmp_path / "ws"))  # cleared again: no cookies
    assert deps.yt_cookies() == []


def test_readonly_workspace():
    with pytest.raises(SystemExit, match="read-only"):
        env.check_folder(Path("/kaggle/input/videos"))


def test_secret_reads_only_the_environment(clean_env):
    clean_env.setitem(sys.modules, "kaggle_secrets", None)  # an import would fail loudly
    assert research.secret("HF_TOKEN") is None
    clean_env.setenv("HF_TOKEN", "hf_env")
    assert research.secret("HF_TOKEN") == "hf_env"


def test_notebooks_are_built_and_clean():
    for path, cells in build_notebook.NOTEBOOKS.items():
        nb = json.loads(path.read_text(encoding="utf-8"))
        assert nb["cells"] == cells, f"{path.name} is out of date: python scripts/build_notebook.py"
        code = ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]
        for src in code:
            compile(src, path.name, "exec")
        settings = code[0]
        assert 'HF_TOKEN = ""' in settings and 'DEVICE = "auto"' in settings  # never ship a token
        assert "kaggle_secrets" not in "".join(code) and "userdata" not in "".join(code)
    main = "".join(build_notebook.CELLS[1]["source"])
    assert 'STORAGE = "folder"  #@param ["folder", "bucket"]' in main and 'BUCKET = ""' in main
    assert 'WORKSPACE = ""' in main and "OUTPUT" not in main and "VIDEOS" not in main


def test_get_code_uses_this_checkout(tmp_path, monkeypatch):
    """On a local machine, a notebook opened inside a checkout runs that checkout (no network)."""
    for k in ("KAGGLE_KERNEL_RUN_TYPE",):
        monkeypatch.delenv(k, raising=False)
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "google.colab" else real(n, *a))
    monkeypatch.chdir(ROOT / "notebooks")
    monkeypatch.setattr(sys, "path", list(sys.path))
    ns = {"WORK_DIR": str(tmp_path), "CODE_BRANCH": "main"}
    exec(build_notebook.GET_CODE, ns)
    assert ns["RUNTIME"] == "local" and ns["CODE"] == ROOT and ns["ROOT"] == tmp_path
    assert not (tmp_path / "lang_recomp").exists()


def test_a_download_youtube_refuses_says_how_to_fix_it(tmp_path, monkeypatch):
    from lb_worker.stages import bulk

    tries = []

    def refuse(cmd, **k):
        tries.append(cmd)
        return type("P", (), {"returncode": 1, "stdout": "", "stderr": "ERROR: Sign in to confirm you're not a bot"})()

    monkeypatch.setattr(bulk.subprocess, "run", refuse)
    monkeypatch.setattr(bulk, "_js_runtime", lambda: None)
    monkeypatch.setenv("LB_YT_COOKIES", "")
    with pytest.raises(RuntimeError, match="YT_COOKIES"):
        bulk.fetch({"id": "x", "url": "https://youtu.be/x"}, tmp_path, 720)
    assert len(tries) == 1  # no pointless retries
