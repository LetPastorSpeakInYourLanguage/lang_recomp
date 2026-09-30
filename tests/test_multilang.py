"""Any source language, any target; and the Kaggle route: a notebook pushes to a Hugging
Face bucket, the app pulls it, follows the run and opens its dubs (models and the bucket
stood in for)."""
import shutil
import sys
from pathlib import Path

import huggingface_hub
import numpy as np
import pytest

from app import buckets, db, mix, project, runs, settings, tasks
from tests.test_run import _tone, stubs  # noqa: F401  (the fixture)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import asr, batch_asr, research  # noqa: E402


def test_the_recogniser_is_chosen_by_the_source_language():
    assert asr.choose("en") == ("whisper", "large-v3")
    assert asr.choose("tr") == ("whisper", "large-v3") and asr.whisper_is_good("tr")
    assert asr.choose("am") == ("hf", "badrex/Ethio-ASR-amharic")  # built-in: Whisper is weak for Amharic
    assert asr.choose("am", {"am": "whisper"}) == ("whisper", "large-v3")
    assert asr.choose("tr", {"tr": "selimc/whisper-large-v3-turbo-turkish"}) == ("hf", "selimc/whisper-large-v3-turbo-turkish")
    assert asr.choose("en", {"en": "whisper:large-v3-turbo"}) == ("whisper", "large-v3-turbo")
    assert not asr.whisper_is_good("am")
    assert asr.DEFAULT_ALIGNERS["tr"] == "mpoyraz/wav2vec2-xls-r-300m-cv7-turkish"


def test_words_from_a_hugging_face_model_become_timed_segments():
    words = asr.words_from_chunks([{"text": "ሰላም", "timestamp": (0.1, 0.5)}, {"text": " ", "timestamp": (0.5, 0.6)},
                                   {"text": "ነው", "timestamp": (0.6, None)}], offset=10.0)
    assert [w["w"] for w in words] == ["ሰላም", "ነው"] and words[0]["start"] == 10.1 and words[1]["end"] == pytest.approx(10.9)
    segs = asr.segments_from_words(words + [{"w": "እንደገና", "start": 12.0, "end": 12.4, "p": 1.0}])
    assert [s["text"] for s in segs] == ["ሰላም ነው", "እንደገና"]  # split at the 1.1 s pause


def test_a_hugging_face_recogniser_transcribes_every_video_in_one_batch(monkeypatch):
    monkeypatch.setattr(batch_asr, "speech", lambda a: [(0.5, 2.0), (40.0, 41.0)])  # too far apart for one window
    seen = []

    def pipe(inputs, batch_size, return_timestamps):
        seen.append(len(inputs))
        return [{"chunks": [{"text": "ሰላም", "timestamp": (0.0, 0.4)}]} for _ in inputs]

    docs = asr.transcribe_hf(pipe, {"a": np.zeros(45 * 16000, np.float32), "b": np.zeros(45 * 16000, np.float32)}, "am", "x/ctc")
    assert seen == [4]  # 2 windows × 2 videos, one call
    assert [w["start"] for s in docs["a"]["segments"] for w in s["words"]] == [0.5, 40.0]


def _fake_bucket(root: Path):
    """hf://buckets/<ns>/<name> as a folder: sync copies what changed, like the real one."""
    def sync_bucket(source, dest, **kw):
        to_dir = lambda p: root / p.removeprefix("hf://buckets/") if p.startswith("hf://") else Path(p)  # noqa: E731
        src, dst = to_dir(source), to_dir(dest)
        inc = kw.get("include")
        for f in src.rglob("*") if src.exists() else []:
            rel = f.relative_to(src).as_posix()
            if not f.is_file() or rel.startswith("cache/") or rel.endswith(".part"):
                continue
            if inc and not any(Path(rel).match(i) or rel.startswith(i.rstrip("*")) for i in inc):
                continue
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst / rel)
    return sync_bucket


def test_amharic_to_english_on_kaggle_through_a_bucket_and_the_app_plays_the_dub(tmp_path, monkeypatch, stubs):  # noqa: F811
    monkeypatch.setattr(research, "_scratch", lambda: tmp_path / "scratch")
    monkeypatch.setattr(huggingface_hub, "sync_bucket", _fake_bucket(tmp_path / "hf"))
    monkeypatch.setattr(batch_asr, "speech", lambda a: [(0.3, 3.4)])
    monkeypatch.setattr(asr, "load_hf", lambda repo, log=print: lambda inputs, batch_size, return_timestamps: [
        {"chunks": [{"text": "ሰላም", "timestamp": (0.0, 0.5)}, {"text": "ነው", "timestamp": (0.6, 1.2)},
                    {"text": "እንደምን", "timestamp": (1.8, 2.4)}, {"text": "ነህ", "timestamp": (2.5, 3.0)}]} for _ in inputs])
    videos = tmp_path / "kaggle" / "input"
    videos.mkdir(parents=True)
    _tone(videos / "sermon-1.mp4", 4, 440, video=True)
    _tone(videos / "sermon-2.mp4", 4, 520, video=True)
    saved = (db.DATA, db.DB_PATH, settings.PATH)
    res = research.run_folder(videos, tmp_path / "kaggle" / "lb-out", "am", ["en"], hf_token="hf_test",
                              bucket="team/runs")
    assert res["videos"] == 2
    pushed = tmp_path / "hf" / "team" / "runs"
    assert list(pushed.glob("runs/*/results/*.lbwork")) and list(pushed.rglob("*.en.mp4")), "nothing pushed"
    assert not list(pushed.glob("cache/*"))

    # the app on a member's PC: the bucket is a device, synced into a folder here
    monkeypatch.setattr(db, "DATA", tmp_path / "app")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app" / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    settings.PATH = saved[2]
    db._local.c = None
    s = settings.load()
    settings.save(s | {"roots": s["roots"] + [{"id": "hf", "name": "Team bucket", "kind": "bucket",
                                                "bucket": "team/runs", "path": str(tmp_path / "mirror")}]})
    assert settings.root("hf")["bucket"] == "team/runs"
    buckets.sync("hf")
    listed = runs.scan("hf", auto_open=False)
    assert len(listed) == 1 and listed[0]["done"]["mix"] == 2 and listed[0]["has_results"]
    assert listed[0]["state"] == "done"
    got = runs.open_results("hf", listed[0]["run"])
    assert len(got["sources"]["added"]) == 2
    for pid in got["sources"]["added"]:
        mp4 = Path(db.meta(pid)["exports"]["en"]["mp4"])
        assert mp4.exists() and mp4.is_relative_to(tmp_path / "mirror"), mp4  # played from the synced folder
        assert db.meta(pid)["transcript"]["source"] == "asr"  # the Amharic recogniser, not Whisper
        assert project.sentences(pid, "en") and mix.mix_dir(pid, "en").is_relative_to(tmp_path / "mirror")
    db._local.c = None


def test_two_gpus_share_the_voicing_and_the_scoring(tmp_path, monkeypatch, stubs):  # noqa: F811
    from lb_worker.stages import bakeoff
    from lb_worker.stages import run as runmod

    monkeypatch.setattr(research, "_scratch", lambda: tmp_path / "scratch")
    monkeypatch.setattr(runmod, "gpu_count", lambda: 2)
    monkeypatch.setattr(runmod.Run, "_start_gpu1", lambda self: setattr(self, "_sep", None))
    inner, gpus = bakeoff.sh, []

    def sh(cmd, ctx, cwd=None, timeout=3600, env=None, tag=""):
        gpus.append((Path(str(cmd[1])).name, (env or {}).get("CUDA_VISIBLE_DEVICES")))
        return inner(cmd, ctx, cwd, timeout)

    monkeypatch.setattr(bakeoff, "sh", sh)
    videos = tmp_path / "in"
    videos.mkdir()
    _tone(videos / "a.mp4", 4, 440, video=True)
    res = research.run_folder(videos, tmp_path / "out", "en", ["am"], hf_token="hf_test")
    assert res["videos"] == 1 and list((tmp_path / "out").rglob("*.am.mp4"))
    assert sorted(gpus) == [("omnivoice_gen.py", "0"), ("omnivoice_gen.py", "1"), ("score.py", "0"), ("score.py", "1"),
                            ("svc_batch.py", "0"), ("svc_batch.py", "1")]  # native speech, then Seed-VC, on both
    db._local.c = None


def test_a_run_where_nothing_could_be_transcribed_stops_and_shows_as_failed(tmp_path, monkeypatch, stubs):  # noqa: F811
    from lb_worker.stages import run as runmod

    monkeypatch.setattr(research, "_scratch", lambda: tmp_path / "scratch")

    def broken(*a, **k):
        raise AttributeError("type object 'TraceFlags' has no attribute 'RANDOM_TRACE_ID'")

    monkeypatch.setattr(runmod.batch_asr, "transcribe_many", broken)
    videos = tmp_path / "in"
    videos.mkdir()
    _tone(videos / "a.mp4", 4, 440, video=True)
    out = tmp_path / "out"
    saved = (db.DATA, db.DB_PATH, settings.PATH)
    with pytest.raises(RuntimeError, match="no video could be transcribed"):
        research.run_folder(videos, out, "en", ["am"], hf_token="hf_test")
    run_dir = next((out / "runs").iterdir())
    db.DATA, db.DB_PATH, settings.PATH = saved
    db._local.c = None
    s = settings.load()
    settings.save(s | {"roots": s["roots"] + [{"id": "k", "name": "Kaggle", "kind": "bucket", "bucket": "t/r", "path": str(out)}]})
    st = runs.status("k", run_dir.name, "x")
    assert st["state"] == "failed" and "no video could be transcribed" in st["note"]
    db._local.c = None


def test_a_failed_write_does_not_leave_the_database_locked(tmp_path, monkeypatch):
    import sqlite3
    import threading

    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    db.run("INSERT INTO chapters (project_id,id,start,title,updated) VALUES ('p',1,0,'',0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.run("INSERT INTO chapters (project_id,id,start,title,updated) VALUES ('p',1,0,'',0)")
    done = []

    def other_thread():  # another connection can still write at once
        db.run("INSERT INTO chapters (project_id,id,start,title,updated) VALUES ('p',2,5,'',0)")
        done.append(1)

    t = threading.Thread(target=other_thread)
    t.start()
    t.join(10)
    assert done and len(db.rows("SELECT * FROM chapters WHERE project_id='p'")) == 2
    db._local.c = None
