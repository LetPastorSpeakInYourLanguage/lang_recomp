"""A whole run, fetch to mix, with the models replaced by stand-ins (no GPU, no network):
the orchestration, the app logic it drives, the files it leaves on the device and the
results the app opens are real."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from app import db, mix, project, runs, series, settings, tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker.stages import analysis, bakeoff, run as runmod  # noqa: E402
from lb_worker.stages import align as alignmod  # noqa: E402


def _tone(path: Path, secs: float, hz: float, video: bool = False) -> None:
    src = ["-f", "lavfi", "-i", f"sine=frequency={hz}:duration={secs}"]
    vid = ["-f", "lavfi", "-i", f"color=c=black:s=64x64:d={secs}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p"] if video else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", *src, *vid, "-ac", "1", str(path)], check=True)


class Ctx:
    def __init__(self, tmp: Path, root: Path, run_id: str):
        self.params = {"run": run_id}
        self.layout = type("L", (), {"root": root})()
        self.worker = type("W", (), {"scratch": tmp / "scratch", "_models": {}})()
        self.work = tmp / "work"
        self.work.mkdir(parents=True, exist_ok=True)
        self.logs = []

    def model(self, key, loader):
        if key not in self.worker._models:
            self.worker._models[key] = loader()
        return self.worker._models[key]

    def log(self, m):
        self.logs.append(m)

    def cancelled(self):
        return False

    def set_progress(self, *a):
        pass


@pytest.fixture()
def stubs(monkeypatch):
    def transcribe_many(model, audios, lang, size):
        return {pid: {"language": "en", "model": size, "segments": [
            {"start": 0.3, "end": 1.6, "text": "Hello there.", "words": [{"w": "Hello", "start": 0.3, "end": 0.8}, {"w": "there.", "start": 0.9, "end": 1.6}]},
            {"start": 2.0, "end": 3.4, "text": "Nice to see you.", "words": [{"w": "Nice", "start": 2.0, "end": 2.3}, {"w": "to", "start": 2.3, "end": 2.5},
                                                                              {"w": "see", "start": 2.5, "end": 2.8}, {"w": "you.", "start": 2.8, "end": 3.4}]}]}
            for pid in audios}

    monkeypatch.setattr(runmod.batch_asr, "transcribe_many", transcribe_many)
    monkeypatch.setattr(runmod, "ensure", lambda *a, **k: None)  # no installs in tests
    monkeypatch.setattr(analysis, "load_whisper", lambda *a, **k: "whisper")
    monkeypatch.setattr(analysis, "load_pyannote", lambda *a, **k: "pyannote")
    monkeypatch.setattr(alignmod, "load_aligner", lambda repo: "aligner")
    monkeypatch.setattr(alignmod, "align_doc", lambda doc, *a, **k: (len(doc["segments"]), len(doc["segments"])))
    monkeypatch.setattr(analysis, "diarize_wav", lambda pipe, wav, kw, name: {
        "turns": [], "exclusive": [{"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"}],
        "centroids": {"SPEAKER_00": [1.0] + [0.0] * 255}, "labels": ["SPEAKER_00"]})
    monkeypatch.setattr(analysis, "load_separator", lambda *a, **k: "separator")

    def separate_file(sep, src, tmp, dest, log=print):
        dest.mkdir(parents=True, exist_ok=True)
        _tone(dest / "vocals.flac", 4, 220)
        _tone(dest / "background.flac", 4, 110)
        return dest / "vocals.flac", dest / "background.flac"

    monkeypatch.setattr(analysis, "separate_file", separate_file)
    monkeypatch.setattr(bakeoff, "pip", lambda ctx, *specs: True)

    def sh(cmd, ctx, cwd=None, timeout=3600):
        cmd = [str(c) for c in cmd]
        man = json.loads(Path(cmd[cmd.index("--manifest") + 1]).read_text(encoding="utf-8"))
        out = Path(cmd[cmd.index("--out") + 1])
        if cmd[1].endswith("omnivoice_gen.py"):
            for it in man:
                t = np.arange(16000) / 16000
                wavfile.write(it["out"], 16000, (np.sin(2 * np.pi * 330 * t) * 8000).astype(np.int16))
        else:
            out.write_text(json.dumps({"items": {it["key"]: {"sim": 0.9, "cer": 0.1, "dur": 0.9, "dur_s": 1.0} for it in man["items"]}}))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bakeoff, "sh", sh)

    class Fake:
        def __init__(self, *a, **k):
            pass

        def translate(self, items):
            return {x["id"]: f"[am] {x['text']}" for x in items}

    monkeypatch.setattr(project, "GoogleBatchTranslator", Fake)


def test_a_folder_run_goes_from_videos_to_dubbed_mp4s_and_the_app_opens_it(tmp_path, monkeypatch, stubs):
    lib = tmp_path / "app-library"
    monkeypatch.setattr(db, "DATA", lib)
    monkeypatch.setattr(db, "DB_PATH", lib / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    db._local.c = None
    device = Path(settings.root("colab")["path"])  # the test's stand-in for G:/My Drive/LangBridge
    videos = device.parent / "My videos"
    videos.mkdir(parents=True)
    _tone(videos / "lesson-1.mp4", 4, 440, video=True)
    _tone(videos / "lesson-2.mp4", 4, 520, video=True)
    (videos / "lesson-2.srt").write_text("1\n00:00:00,300 --> 00:00:01,600\nHello there.\n\n2\n00:00:02,000 --> 00:00:03,400\nNice to see you.\n")
    s = series.create("Lessons", "course", "en", ["am"])
    r = runs.create(s["id"], "colab", folder=str(videos), options={"dub_limit": 2})
    assert r["videos"] == 2 and r["stages"] == runs.STAGES
    man = json.loads((device / "runs" / r["run"] / "manifest.json").read_text(encoding="utf-8"))
    assert man["src_lang"] == "en" and man["options"]["aligners"].get("en")

    saved = (db.DATA, db.DB_PATH, settings.PATH)
    res = runmod.Run(Ctx(tmp_path, device, r["run"])).go()
    db.DATA, db.DB_PATH, settings.PATH = saved  # the run pointed the app at its scratch library
    db._local.c = None
    assert res["videos"] == 2
    assert (device / "runs" / r["run"] / "results").glob("*.lbwork")
    state = json.loads((device / "runs" / r["run"] / "state.json").read_text(encoding="utf-8"))
    assert all(v.get("mix") == "done" for v in state["sources"].values()), state

    got = runs.open_results("colab", r["run"])
    assert len(got["sources"]["matched"]) == 2
    for pid in got["sources"]["matched"]:
        p = project.get(pid)
        assert p["video"].startswith(str(videos))  # played where it is, never copied
        assert [x["tr"] for x in project.sentences(pid, "am")] == ["[am] Hello there.", "[am] Nice to see you."]
        mp4 = db.meta(pid)["exports"]["am"]["mp4"]
        assert mp4.startswith(str(device / "library")) and Path(mp4).exists()
        assert mix.mix_dir(pid, "am").is_relative_to(device / "library")
        assert db.row("SELECT COUNT(*) n FROM takes WHERE project_id=? AND chosen=1", pid)["n"] == 2
    subs = [pid for pid in got["sources"]["matched"] if project.get(pid)["name"] == "lesson-2"][0]
    assert db.meta(subs)["transcript"]["source"] == "subtitles"
    listed = runs.listing(f"series:{s['id']}")
    assert listed[0]["done"]["mix"] == 2 and listed[0]["has_results"]


def test_a_library_run_spans_works_and_finds_the_same_teacher_in_all_of_them(tmp_path, monkeypatch, stubs):
    from app import cast, libraries

    lib = tmp_path / "app-library"
    monkeypatch.setattr(db, "DATA", lib)
    monkeypatch.setattr(db, "DB_PATH", lib / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")
    db._local.c = None
    device = Path(settings.root("colab")["path"])
    folder = device.parent / "Teachings"
    (folder / "Faith").mkdir(parents=True)
    (folder / "Grace").mkdir(parents=True)
    (folder / "Faith" / "work.json").write_text(json.dumps({"kind": "speaker", "speakers": ["Pastor A"]}))
    _tone(folder / "Faith" / "01 - Faith.mp4", 4, 440, video=True)
    _tone(folder / "Grace" / "01 - Grace.mp4", 4, 520, video=True)
    (folder / "Grace" / "01 - Grace.srt").write_text("1\n00:00:00,300 --> 00:00:01,600\nHello there.\n")
    L = libraries.create("Teachings", "colab", str(folder), "en", ["am"], kind="speaker")
    libraries.scan(L["id"])
    pids = [v["id"] for w in libraries.tree(L["id"]) for v in w["videos"]]
    r = runs.create_for(pids, "colab", ["fetch", "transcribe"], name="Teachings", owner=f"library:{L['id']}")
    assert r["works"] == 2
    saved = (db.DATA, db.DB_PATH, settings.PATH)
    runmod.Run(Ctx(tmp_path, device, r["run"])).go()
    db.DATA, db.DB_PATH, settings.PATH = saved
    db._local.c = None
    got = runs.open_results("colab", r["run"])
    assert len(got["works"]) == 2 and len(got["sources"]["matched"]) == 2
    chars = {cast.character_of(pid, "SPEAKER_00")["uid"] for pid in pids}
    assert len(chars) == 1 and cast.get(chars.pop())["name"] == "Pastor A"  # one teacher across both works
    grace = next(p for p in pids if project.get(p)["name"] == "01 - Grace")
    assert db.meta(grace)["transcript"]["source"] == "subtitles"
    assert runs.listing(f"library:{L['id']}")[0]["done"]["transcribe"] == 2
