import json
import sys
from pathlib import Path

import pytest

from app import bulk, db, project, series, tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker.stages import bulk as stage  # noqa: E402


@pytest.fixture()
def channel(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path / "lib")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lib" / "t.db")
    started = []
    monkeypatch.setattr(tasks, "start", lambda *a, **k: started.append(a) or "task")
    db._local.c = None
    s = series.create("6 Minute English", "course", "en", ["am"], feed_url="https://www.youtube.com/playlist?list=x")
    entries = [{"id": f"v{i:02d}", "title": f"Episode {i}", "url": f"https://www.youtube.com/watch?v=v{i:02d}"} for i in range(45)]
    r = bulk.add(s["id"], entries)
    yield s, r, started
    db._local.c = None


def _finish(pid, ok=True, error="download failed: Sign in to confirm you're not a bot"):
    """What the worker leaves for one video."""
    d = bulk._item_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    if not ok:
        (d / "error.json").write_text(json.dumps({"error": error}))
        return
    rem = db.meta(pid)["remote"]
    video = Path(project.queue(rem["root"]).layout.root) / rem["dest"] / "video.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"mp4")
    words = [{"w": "Hello.", "start": 0.5, "end": 1.0, "spk": "SPEAKER_00"}, {"w": "Hi.", "start": 1.5, "end": 1.9, "spk": "SPEAKER_01"}]
    (d / "asr_spk.json").write_text(json.dumps({"segments": [{"start": 0.5, "end": 1.9, "text": "Hello. Hi.", "words": words}]}))
    (d / "diarization.json").write_text(json.dumps({"exclusive": [{"start": 0.4, "end": 1.2, "speaker": "SPEAKER_00"},
                                                                  {"start": 1.4, "end": 2.0, "speaker": "SPEAKER_01"}],
                                                    "centroids": {}}))
    (d / "done.json").write_text(json.dumps({"video": rem["dest"] + "/video.mp4", "duration": 360.0}))


def test_a_channel_is_added_without_downloading_anything(channel):
    s, r, started = channel
    assert len(r["added"]) == 45 and started == []  # no import task: nothing is fetched here
    assert all(not project.get(pid)["video"] for pid in r["added"])


def test_videos_go_to_colab_in_batches_once(channel):
    s, r, _ = channel
    q = bulk.queue(s["id"], "colab", batch=20)
    assert q["videos"] == 45 and len(q["jobs"]) == 3
    job = json.loads((project.queue("colab").layout.job_dir(q["jobs"][0]) / "job.json").read_text(encoding="utf-8"))
    p = job["params"]
    assert job["stage"] == "bulk" and len(p["items"]) == 20 and p["steps"] == ["fetch", "asr", "align", "diarize"]
    assert p["language"] == "en" and p["aligner"]  # the source language's aligner goes along
    item = p["items"][0]
    assert item["url"].startswith("https://www.youtube.com/") and item["dest"].startswith("library/")
    assert bulk.queue(s["id"], "colab")["videos"] == 0  # already queued: not sent twice
    assert bulk.status(s["id"])["videos"]["queued"] == 45


def test_finished_videos_load_and_play_from_drive(channel):
    s, r, _ = channel
    bulk.queue(s["id"], "colab")
    a, b, c = r["added"][:3]
    _finish(a)
    _finish(b)
    _finish(c, ok=False)
    st = bulk.status(s["id"])
    assert st["videos"]["done"] == 2 and st["videos"]["failed"] == 1 and "not a bot" in st["failures"][0]["error"]
    got = bulk.load(s["id"])
    assert sorted(got["loaded"]) == sorted([a, b]) and got["errors"] == []
    p = project.get(a)
    assert p["video"] == p["audio"] and p["video"].endswith("video.mp4") and "colab" in p["video"]  # on "Drive", not here
    assert not (project.pdir(a) / "clip.mp4").exists() and not (project.pdir(a) / "vocals.flac").exists()
    assert [x["text"] for x in project.sentences(a)] == ["Hello.", "Hi."]
    assert project.summary(a)["counts"]["characters"] == 2  # speakers became the work's cast
    assert bulk.status(s["id"])["videos"]["loaded"] == 2
    again = bulk.retry_failed(s["id"])
    assert again["videos"] == 1 and bulk.status(s["id"])["videos"]["queued"] >= 1


class Ctx:
    """Just enough of the worker's job context to run the bulk stage."""

    def __init__(self, tmp, params):
        self.params = params
        self.out = tmp / "scratch" / "out"
        self.work = tmp / "scratch"
        self.drive_dir = tmp / "drive" / "jobs" / "j1"
        self.out.mkdir(parents=True)
        self.drive_dir.mkdir(parents=True)
        self.worker = type("W", (), {"layout": type("L", (), {"root": tmp / "drive"})()})()
        self.logs, self.checkpoints = [], 0

    def cancelled(self):
        return False

    def set_progress(self, *a):
        pass

    def log(self, m):
        self.logs.append(m)

    def checkpoint(self):
        self.checkpoints += 1


def test_the_stage_resumes_and_isolates_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(stage, "ensure", lambda *a, **k: None)
    fetched = []

    def fake_fetch(it, dest, height, log):
        if it["id"] == "bad":
            raise RuntimeError("download failed: Sign in to confirm you're not a bot")
        fetched.append(it["id"])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "video.mp4").write_bytes(b"x")
        return dest / "video.mp4"

    monkeypatch.setattr(stage, "fetch", fake_fetch)
    monkeypatch.setattr(stage, "_duration", lambda p: 360.0)
    monkeypatch.setattr(stage, "_fingerprint", lambda *a: None)
    monkeypatch.setattr(stage, "_ffmpeg", lambda *a: None)
    monkeypatch.setattr(stage, "analyse", lambda ctx, wav, out, steps: {"segments": 3})
    items = [{"id": i, "url": "u", "dest": f"library/w/{i}"} for i in ("a", "bad", "c")]
    ctx = Ctx(tmp_path, {"items": items})
    (ctx.drive_dir / "out" / "a").mkdir(parents=True)
    (ctx.drive_dir / "out" / "a" / "done.json").write_text("{}")  # finished by an earlier session
    res = stage.bulk(ctx)
    assert res == {"items": 3, "done": 1, "failed": 1, "skipped": 1}
    assert fetched == ["c"] and ctx.checkpoints == 2
    assert "not a bot" in json.loads((ctx.out / "bad" / "error.json").read_text())["error"]
    assert json.loads((ctx.out / "c" / "done.json").read_text())["video"] == "library/w/c/video.mp4"
