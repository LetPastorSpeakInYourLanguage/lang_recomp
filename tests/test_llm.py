"""The local model server wrapper (worker/lb_worker/llm.py), with the server and HTTP faked."""
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import llm  # noqa: E402


def test_the_build_matches_the_machine():
    b = llm.LLAMA_BUILD
    assert llm.asset("Linux", 12) == f"llama-{b}-bin-ubuntu-cuda-12.8-x64.tar.gz"
    assert llm.asset("Linux", 13) == f"llama-{b}-bin-ubuntu-cuda-13.4-x64.tar.gz"
    assert llm.asset("Linux", None) == llm.asset("Linux", 12, gpu=False) == f"llama-{b}-bin-ubuntu-x64.tar.gz"
    assert llm.asset("Windows") == f"llama-{b}-bin-win-vulkan-x64.zip"
    assert llm.asset("Windows", gpu=False) == f"llama-{b}-bin-win-cpu-x64.zip"


def test_the_archive_is_cached_once_and_unpacked_locally(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"#!/bin/sh\n"
        info = tarfile.TarInfo("build/bin/llama-server")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    calls = []

    class R:
        def __init__(self, url, **k):
            calls.append(url)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield buf.getvalue()

    monkeypatch.setattr(llm.requests, "get", R)
    name = llm.asset("Linux", 12)
    exe = llm.fetch_build(name, tmp_path / "cache", tmp_path / "a", log=lambda *a: None)
    assert exe.name == "llama-server" and (tmp_path / "cache" / name).exists()
    assert len(calls) == 1 and llm.LLAMA_BUILD in calls[0]
    llm.fetch_build(name, tmp_path / "cache", tmp_path / "b", log=lambda *a: None)  # another session: no download
    assert len(calls) == 1


def test_the_server_runs_parallel_slots_on_the_chosen_gpu():
    s = llm.Server("gemma-4-e4b", Path("w"), gpu=0, slots=4, ctx_per_slot=2048)
    cmd = s.command(Path("llama-server"), Path("m.gguf"), 9000)
    assert cmd[cmd.index("-np") + 1] == "4" and cmd[cmd.index("-c") + 1] == "8192"
    assert cmd[cmd.index("-ngl") + 1] == "99" and "--jinja" in cmd
    cpu = llm.Server("gemma-4-e2b", Path("w"), gpu=None).command(Path("x"), Path("m"), 1)
    assert cpu[cpu.index("-ngl") + 1] == "0"
    with pytest.raises(ValueError):
        llm.Server("gpt-9", Path("w"))


class Proc:
    def __init__(self, *a, **k):
        self.alive = True

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0

    kill = terminate


def _no_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "fetch_build", lambda *a, **k: tmp_path / "llama-server")
    monkeypatch.setattr(llm, "fetch_model", lambda *a, **k: tmp_path / "m.gguf")
    monkeypatch.setattr(llm, "cuda_major", lambda: 12)
    monkeypatch.setattr(llm.subprocess, "Popen", Proc)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def test_a_server_that_never_answers_is_stopped_with_its_log(tmp_path, monkeypatch):
    _no_downloads(monkeypatch, tmp_path)

    def down(*a, **k):
        raise llm.requests.ConnectionError("refused")

    monkeypatch.setattr(llm.requests, "get", down)
    s = llm.Server("gemma-4-e4b", tmp_path, start_timeout=0)
    with pytest.raises(RuntimeError, match="did not start"):
        s.start()
    assert s.proc is None


def test_answers_follow_the_schema_and_tokens_are_counted(tmp_path, monkeypatch):
    _no_downloads(monkeypatch, tmp_path)
    monkeypatch.setattr(llm.requests, "get", lambda *a, **k: type("R", (), {"status_code": 200})())
    sent = []

    def post(url, json=None, timeout=None):
        sent.append(json)
        return type("R", (), {"raise_for_status": lambda self: None,
                              "json": lambda self: {"choices": [{"message": {"content": '{"ok": true}'}}],
                                                    "usage": {"completion_tokens": 7}}})()

    monkeypatch.setattr(llm.requests, "post", post)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    with llm.Server("gemma-4-e4b", tmp_path, log=lambda *a: None) as s:
        out = s.map(lambda q: s.chat(q, schema), ["a", "b", "c"])
    assert out == [{"ok": True}] * 3 and s.tokens == 21
    assert sent[0]["response_format"]["json_schema"]["schema"] == schema
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert s.proc is None  # stopped on leaving
    assert s.chat("hi", full=True) == {"text": '{"ok": true}', "finish": None}


def test_one_failed_request_does_not_stop_the_others(tmp_path):
    s = llm.Server("gemma-4-e4b", tmp_path, slots=2)

    def fn(x):
        if x == 2:
            raise ValueError("bad")
        return x * 10

    out = s.map(fn, [1, 2, 3])
    assert out[0] == 10 and isinstance(out[1], ValueError) and out[2] == 30
    json.dumps(out[0])
