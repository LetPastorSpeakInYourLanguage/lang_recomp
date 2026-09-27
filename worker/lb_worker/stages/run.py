"""Runs: the Lang-Bridge pipeline for a set of videos, on the device the app sent it to.

The app writes ``runs/<run id>/manifest.json`` and ``works/<work uid>.lbwork`` (each
work as it is there, media by reference) into the device's folder and queues one
``pipeline`` job. This stage imports the works into a scratch library, runs the app's own
logic and the models in-process, and publishes ``results/<work uid>.lbwork`` (media by
reference) and ``state.json`` after every stage, so the app can open the results — and a
run that stops resumes where it was. Videos of several works (a library selection) are
batched together.

Stages, in order (a run may stop after any of them, for a person to check the work):
  fetch       videos into the device library (a download thread); YouTube captions for
              the trial videos; a folder run uses the files where they are
  transcribe  Whisper over groups of downloaded videos in one batched pass (their VAD
              windows together), subtitles instead where a video has them, alignment,
              speakers → lines and cast (proposals confirmed when the run says checks pass)
  translate   every line into the run's languages
  voice       voice separation, voice banks, every line of every video voiced in one pass
              per language, every take scored in one pass
  mix         dub mix + MP4 per video and language (on CPU threads)

Light steps run while the download thread is still fetching; each model loads once for
all the work it has in the run.
"""
from __future__ import annotations

import difflib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import batch_asr
from ..deps import ensure
from ..registry import stage

STAGES = ["fetch", "transcribe", "translate", "voice", "mix"]
GROUP_S = 30 * 60   # transcribe downloaded videos in groups of about this much audio
SR = 16000


@stage("pipeline", model_key="pipeline")
def pipeline(ctx) -> dict:
    return Run(ctx).go()


class Run:
    def __init__(self, ctx):
        self.ctx = ctx
        self.root = Path(ctx.layout.root)
        self.id = ctx.params["run"]
        self.dir = self.root / "runs" / self.id
        self.man = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.opt = self.man.get("options") or {}
        self.stages = [s for s in STAGES if s in (self.man.get("stages") or STAGES)]
        sp = self.dir / "state.json"
        self.state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else \
            {"run": self.id, "started": time.time(), "stages": {}, "sources": {}, "timings": {}}
        self.lock = threading.Lock()
        self.app = self._load_app()

    # ---- the app, headless, on a scratch library -------------------------------------------
    def _load_app(self):
        lib = Path(self.ctx.worker.scratch) / "run-library"
        shutil.rmtree(lib, ignore_errors=True)
        lib.mkdir(parents=True)
        (lib / "settings.json").write_text(json.dumps({
            "roots": [{"id": "device", "name": "this device", "kind": "colab", "path": str(self.root)}],
            "active": "device", "aligners": self.opt.get("aligners") or {},
            "keep_words": self.opt.get("keep_words") or []}), encoding="utf-8")
        os.environ["LANGBRIDGE_DATA"] = str(lib)
        # the app package: beside the worker (this repo, or where the notebook copied both),
        # or published next to it on Drive
        for p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[2], self.root / "worker"):
            if (p / "app" / "__init__.py").exists() and str(p) not in sys.path:
                sys.path.insert(0, str(p))
        from app import bulk, cast, db, mix, package, project, settings, voice  # noqa: F401
        from app import banks, captions

        # a second run in the same process: point the already-imported modules at it
        db.DATA, db.DB_PATH, settings.PATH = lib, lib / "langbridge.db", lib / "settings.json"
        db._local.c = None
        project._queues = {}
        return type("App", (), dict(bulk=bulk, cast=cast, db=db, mix=mix, package=package, project=project,
                                    settings=settings, voice=voice, banks=banks, captions=captions))

    # ---- bookkeeping ---------------------------------------------------------------------
    def log(self, msg: str) -> None:
        self.ctx.log(msg)
        if not getattr(self.ctx, "prints", False):  # the research notebook's context prints itself
            print(msg, flush=True)

    def save_state(self) -> None:
        with self.lock:
            tmp = self.dir / "state.json.tmp"
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.dir / "state.json")

    def mark(self, uid: str, step: str, value) -> None:
        with self.lock:
            self.state["sources"].setdefault(uid, {})[step] = value
        self.save_state()

    def done(self, uid: str, step: str) -> bool:
        return self.state["sources"].get(uid, {}).get(step) == "done"

    def publish(self, stage_name: str) -> None:
        A = self.app
        (self.dir / "results").mkdir(exist_ok=True)
        for sid in self.sids:
            uid = A.db.row("SELECT uid FROM series WHERE id=?", sid)["uid"]
            out = self.dir / "results" / f"{uid}.lbwork.part"
            A.package.export(sid, json.loads(A.db.row("SELECT targets FROM series WHERE id=?", sid)["targets"]),
                             media="ref", out=out, ref_root=self.root, note=f"run {self.id}: through {stage_name}")
            os.replace(out, self.dir / "results" / f"{uid}.lbwork")
        self.state["stages"][stage_name] = {"done": time.time()}
        self.save_state()
        self.log(f"· saved to Drive: results through '{stage_name}'")

    # ---- the run -------------------------------------------------------------------------
    def go(self) -> dict:
        A = self.app
        t0 = time.time()
        ensure("yt-dlp", probe="yt_dlp")  # fetching, captions
        if "transcribe" in self.stages:
            ensure("faster-whisper>=1.1", probe="faster_whisper")
            ensure("soundfile", probe="soundfile")
        works = self.man.get("works") or [{"file": "work.lbwork"}]
        self.sids = [A.package.import_work(self.dir / w["file"], fetch=False, ref_root=self.root)["work"] for w in works]
        for f in sorted((self.dir / "results").glob("*.lbwork")) if (self.dir / "results").exists() else []:
            A.package.import_work(f, fetch=False, ref_root=self.root)  # resuming: what this run already made
        uids = self.man.get("sources") or [r["uid"] for sid in self.sids for r in A.db.rows(
            "SELECT uid FROM projects WHERE series_id=? ORDER BY position, created", sid)]
        self.pids = [A.db.row("SELECT id FROM projects WHERE uid=?", u)["id"] for u in uids
                     if A.db.row("SELECT id FROM projects WHERE uid=?", u)]
        self.uid = {pid: A.project.get(pid)["uid"] for pid in self.pids}
        for pid in self.pids:  # every source's media live in the device library, by work
            if not A.project.media_dir(pid):
                wuid = A.db.row("SELECT s.uid FROM series s JOIN projects p ON p.series_id=s.id WHERE p.id=?", pid)["uid"]
                A.db.set_meta(pid, media_dir=str(self.root / "library" / wuid / self.uid[pid]))
        self.langs = self.opt.get("langs") or sorted({t for sid in self.sids for t in json.loads(
            A.db.row("SELECT targets FROM series WHERE id=?", sid)["targets"])})
        self.log(f"Run {self.id}: {len(self.pids)} videos in {len(self.sids)} work(s), stages {', '.join(self.stages)}, "
                 f"languages {', '.join(self.langs)}")
        if "fetch" in self.stages or "transcribe" in self.stages:
            self.fetch_and_transcribe()
        for name, fn in (("translate", self.translate), ("voice", self.voice), ("mix", self.mix)):
            if name in self.stages and not self.ctx.cancelled():
                t = time.time()
                fn()
                self.state["timings"][name] = round(time.time() - t, 1)
                self.publish(name)
        self.state["finished"] = time.time()
        self.save_state()
        return {"videos": len(self.pids), "stages": self.stages, "seconds": round(time.time() - t0, 1)}

    # ---- fetch + transcribe (overlapped) -------------------------------------------------
    def resolve(self, ref: str | None) -> Path | None:
        """A file as this device finds it: "root:<path from the job folder>" (on Drive) or
        "file:<full path>" (on this PC)."""
        if not ref:
            return None
        if ref.startswith("root:"):
            return Path(os.path.normpath(self.root / ref[5:]))
        if ref.startswith("file:"):
            return Path(ref[5:])
        return None

    def video_of(self, pid: str) -> Path | None:
        p = self.app.project.get(pid)
        src = p["source"] or ""
        if src.startswith(("root:", "file:")):  # a library or folder video: already on this device
            return self.resolve(src)
        v = self.app.project.media_dir(pid) / "video.mp4"
        return v if v.exists() else (Path(p["video"]) if p["video"] and Path(p["video"]).exists() else None)

    def fetch_and_transcribe(self) -> None:
        ready: queue.Queue = queue.Queue()
        t = time.time()
        fetcher = threading.Thread(target=self._fetch_all, args=(ready,), daemon=True)
        fetcher.start()
        if "transcribe" in self.stages:
            self._transcribe_as_ready(ready)
        fetcher.join()
        self.state["timings"]["fetch+transcribe"] = round(time.time() - t, 1)
        self.publish("transcribe" if "transcribe" in self.stages else "fetch")

    def _fetch_all(self, ready: queue.Queue) -> None:
        from .bulk import fetch
        A = self.app
        trial = set(self.pids[: int(self.opt.get("captions_download", 0))])
        height = int(self.opt.get("height", 720))
        for k, pid in enumerate(self.pids):
            if self.ctx.cancelled():
                break
            uid, dest = self.uid[pid], A.project.media_dir(pid)
            try:
                video = self.video_of(pid)
                if video is None and "fetch" in self.stages:
                    p = A.project.get(pid)
                    video = fetch({"id": uid, "url": p["source"], "clip": [p["clip_start"], p["clip_end"]]},
                                  dest, height, self.log)
                if video is None:
                    self.mark(uid, "fetch", "missing")
                    continue
                with self.lock:
                    A.db.run("UPDATE projects SET video=?, audio=? WHERE id=?", str(video), str(video), pid)
                if pid in trial and not (dest / "captions.vtt").exists():
                    self._captions(pid, dest)
                self.mark(uid, "fetch", "done")
                self.log(f"fetched {k + 1}/{len(self.pids)}: {A.project.get(pid)['name'][:60]}")
                ready.put(pid)
            except Exception as e:  # one video must not stop the others
                self.mark(uid, "fetch", f"failed: {str(e)[-300:]}")
                self.log(f"fetch failed: {pid}: {str(e)[-200:]}")
        ready.put(None)

    def _captions(self, pid: str, dest: Path) -> None:
        """YouTube's own captions: the uploader's if there are any, else the automatic ones."""
        url = self.app.project.get(pid)["source"]
        for kind, flag in (("manual", "--write-subs"), ("auto", "--write-auto-subs")):
            subprocess.run([sys.executable, "-m", "yt_dlp", "--skip-download", flag, "--sub-langs", "en.*,en",
                            "--sub-format", "vtt", "-o", str(dest / "captions"), "--", url], capture_output=True, text=True)
            got = sorted(dest.glob("captions*.vtt"))
            if got:
                got[0].replace(dest / "captions.vtt")
                for extra in got[1:]:
                    extra.unlink(missing_ok=True)
                with self.lock:
                    self.app.db.set_meta(pid, captions={"kind": kind, "path": str(dest / "captions.vtt")})
                return

    def _transcribe_as_ready(self, ready: queue.Queue) -> None:
        group, secs = [], 0.0
        while True:
            pid = ready.get()
            if pid is not None:
                if self.done(self.uid[pid], "transcribe"):
                    continue
                group.append(pid)
                secs += self.app.project.get(pid)["duration"] or 360
            if group and (pid is None or secs >= GROUP_S):
                try:
                    self._transcribe_group(group)
                except Exception:
                    self.log(f"transcription of a group failed:\n{traceback.format_exc()[-1500:]}")
                    for g in group:
                        self.mark(self.uid[g], "transcribe", "failed")
                group, secs = [], 0.0
            if pid is None:
                break

    def _audio16(self, pid: str):
        import numpy as np

        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.video_of(pid)), "-vn", "-ac", "1", "-ar", str(SR),
                              "-f", "f32le", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.float32).copy()

    def _transcribe_group(self, group: list[str]) -> None:
        from .align import align_doc, load_aligner
        from .analysis import diarize_wav, load_pyannote, load_whisper, stamp_speakers

        A, ctx = self.app, self.ctx
        t = time.time()
        audios = {pid: self._audio16(pid) for pid in group}
        with self.lock:
            for pid, a in audios.items():
                A.db.run("UPDATE projects SET duration=COALESCE(duration, ?) WHERE id=?", round(len(a) / SR, 3), pid)
        # a video with its own subtitles is not transcribed: they are its transcript
        subs = {}
        for pid in group:
            f = self.resolve((A.db.meta(pid).get("refs") or {}).get("subtitles"))
            if f is not None and f.exists():
                subs[pid] = f
        need = {pid: a for pid, a in audios.items() if pid not in subs}
        docs = {}
        if need:
            size = self.opt.get("asr_model", "large-v3")
            whisper = ctx.model(f"whisper:{size}", lambda: load_whisper(size, self.log))
            docs = batch_asr.transcribe_many(whisper, need, self.man.get("src_lang"), size)
            self.log(f"transcribed {len(need)} videos ({sum(len(a) for a in need.values()) / SR / 60:.0f} min) "
                     f"in one batched pass, {time.time() - t:.0f} s")
        align_subs = bool(self.opt.get("align_subtitles", True))
        for pid, path in subs.items():
            docs[pid] = A.captions.load(Path(path).read_text(encoding="utf-8", errors="replace"), self.man.get("src_lang"))
            docs[pid]["aligned"] = False
        repo = (self.opt.get("aligners") or {}).get(self.man.get("src_lang") or "")
        aligner = ctx.model(f"aligner:{repo}", lambda: load_aligner(repo)) if repo else None
        pyannote = ctx.model("pyannote", lambda: load_pyannote())
        align_trial = set(self.pids[: int(self.opt.get("captions_align", 0))])
        for pid in group:
            uid, dest = self.uid[pid], A.project.media_dir(pid)
            dest.mkdir(parents=True, exist_ok=True)
            wav = ctx.work / f"{uid}.wav"
            _write_wav(wav, audios[pid])
            doc = docs[pid]
            if aligner and (pid not in subs or align_subs):
                align_doc(doc, audios[pid], SR, aligner, repo, lambda *_: None)
                doc["aligned"] = True
            cap = self._caption_file(pid)
            if cap:  # the captions trial: kept beside, compared later
                raw = A.captions.load(cap.read_text(encoding="utf-8", errors="replace"), self.man.get("src_lang"))
                _dump(dest / "captions_raw.json", raw)
                if aligner and pid in align_trial:
                    al = json.loads(json.dumps(raw))
                    align_doc(al, audios[pid], SR, aligner, repo, lambda *_: None)
                    _dump(dest / "captions_aligned.json", al)
                _dump(dest / "whisper.json", doc)
            kw = {"max_speakers": self.opt["max_speakers"]} if self.opt.get("max_speakers") else {}
            dia = diarize_wav(pyannote, wav, kw, "pyannote/speaker-diarization-community-1")
            asr = stamp_speakers(doc, dia["exclusive"])
            _dump(dest / "asr_spk.json", asr)
            _dump(dest / "diarization.json", dia)
            wav.unlink(missing_ok=True)
            with self.lock:
                A.project.ingest_docs(pid, asr, dia)
                A.db.set_meta(pid, transcript={"source": "subtitles" if pid in subs else "whisper",
                                               "aligned": bool(doc.get("aligned")), "run": self.id})
                if self.opt.get("assume_checked", True):  # the owner's rule for this run: checks pass
                    for a in A.db.rows("SELECT label FROM appearances WHERE source_id=? AND status='proposed'", pid):
                        A.cast.confirm(pid, a["label"])
                self._name_declared_speaker(pid)
            self.mark(uid, "transcribe", "done")
        self.log(f"· group of {len(group)} transcribed, aligned and diarized in {time.time() - t:.0f} s")
        self.publish("transcribe")
        self._report()

    def _name_declared_speaker(self, pid: str) -> None:
        """A work that names its speakers (work.json "speakers"): its main voice, while still
        unnamed, is the first of them — the teacher of a teaching series. Later videos and
        works match that voice, so the same person is one character everywhere."""
        A = self.app
        sid = A.project.get(pid)["series_id"]
        names = json.loads(A.db.row("SELECT settings FROM series WHERE id=?", sid)["settings"] or "{}").get("speakers") or []
        if not names:
            return
        main = A.db.row("SELECT character_uid FROM appearances WHERE source_id=? ORDER BY talk_s DESC LIMIT 1", pid)
        if main:
            c = A.cast.get(main["character_uid"])
            if c["auto"]:
                A.cast.update(c["uid"], name=names[0])

    def _caption_file(self, pid: str) -> Path | None:
        """The trial's YouTube captions for a video, if it has them. The file is the truth:
        a restarted run rebuilds its catalogue and skips fetching what is already there."""
        cap = self.app.db.meta(pid).get("captions")
        for f in ([Path(cap["path"])] if cap else []) + [self.app.project.media_dir(pid) / "captions.vtt"]:
            if f.exists():
                return f
        return None

    def _report(self) -> None:
        """Captions vs Whisper for the trial videos (raw and aligned captions)."""
        A, rows = self.app, []
        for pid in self.pids:
            d = A.project.media_dir(pid)
            wf = d / "whisper.json" if (d / "whisper.json").exists() else d / "asr_spk.json"
            cap = self._caption_file(pid)
            if not wf.exists() or not ((d / "captions_raw.json").exists() or cap):
                continue
            wh = json.loads(wf.read_text(encoding="utf-8"))
            if wh.get("source") == "subtitles":
                continue
            row = {"video": A.project.get(pid)["name"], "kind": (A.db.meta(pid).get("captions") or {}).get("kind")}
            for name in ("captions_raw", "captions_aligned"):
                f = d / f"{name}.json"
                if f.exists():
                    row[name] = compare(wh, json.loads(f.read_text(encoding="utf-8")))
                elif name == "captions_raw" and cap:
                    row[name] = compare(wh, A.captions.load(cap.read_text(encoding="utf-8", errors="replace"),
                                                            self.man.get("src_lang")))
            rows.append(row)
        _dump(self.dir / "report.json", {"run": self.id, "captions": rows})

    # ---- translate -----------------------------------------------------------------------
    def langs_of(self, pid: str) -> list[str]:
        own = self.app.project.targets(pid)
        return [l for l in self.langs if l in own] or own if not self.opt.get("langs") else self.opt["langs"]

    def translate(self) -> None:
        A = self.app
        for k, pid in enumerate(self.pids):
            if not A.db.row("SELECT 1 FROM sentences WHERE project_id=?", pid):
                continue
            for lang in self.langs_of(pid):
                if lang not in A.project.targets(pid):
                    A.project.add_target(pid, lang)
                if all(s["tr"] for s in A.project.sentences(pid, lang)):
                    continue
                try:
                    A.project._translate(pid, lang, None, False, lambda *a: None)
                except Exception as e:
                    self.log(f"translation failed for {pid} ({lang}): {str(e)[-200:]}")
            self.mark(self.uid[pid], "translate", "done")
            if (k + 1) % 25 == 0:
                self.log(f"translated {k + 1}/{len(self.pids)}")

    # ---- voice (heavy) ---------------------------------------------------------------------
    def dub_set(self) -> list[str]:
        A = self.app
        have = [pid for pid in self.pids if A.db.row("SELECT 1 FROM sentences WHERE project_id=?", pid)]
        n = self.opt.get("dub_limit")
        return have if n is None else have[: int(n)]

    def _free_models(self) -> None:
        self.ctx.worker._models.clear()
        try:
            import gc

            import torch

            gc.collect()
            torch.cuda.empty_cache()
        except ImportError:
            pass

    def voice(self) -> None:
        from .analysis import load_separator, separate_file
        from .bakeoff import TTS, pip, sh
        from .voice import take_score

        A, ctx = self.app, self.ctx
        dub = self.dub_set()
        self.log(f"voice: {len(dub)} videos")
        todo = [pid for pid in dub if not A.project.stem(pid, "vocals").exists()]
        if todo:
            self._free_models()  # Whisper, aligner and pyannote are done: make room
            sep = load_separator(None, 2, self.log)
            for pid in todo:
                t = time.time()
                separate_file(sep, self.video_of(pid), ctx.work / "sep" / self.uid[pid], A.project.media_dir(pid), self.log)
                self.log(f"separated {A.project.get(pid)['name'][:50]} in {time.time() - t:.0f} s")
            del sep
            self._free_models()
        engine = dict(A.voice.ENGINE) | {"takes": int(self.opt.get("takes", 1))}
        for lang in self.langs:
            items, meta, speakers = [], {}, {}
            for pid in dub:
                uid, dest = self.uid[pid], A.project.media_dir(pid)
                chars = A.voice.characters_plan(pid, ctx.work / "banks" / uid)
                for label, c in chars.items():
                    if c.get("bank_file"):
                        key = f"{uid}:{label}"
                        speakers[key] = [str(ctx.work / "banks" / uid / f) for f in c["heldout_files"]]
                        c["ref"] = str(ctx.work / "banks" / uid / c["bank_file"])
                if lang not in self.langs_of(pid):
                    continue
                for s in A.voice.lines_to_voice(pid, lang, {k: v for k, v in chars.items() if v.get("ref")}):
                    c = chars[s["speaker"]]
                    for k in range(engine["takes"]):
                        out = dest / "takes" / lang / f"{s['id']}_t{k}.wav"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        key = f"{uid}|{s['id']}|{k}"
                        items.append({"key": key, "text": s["tr"], "ref_audio": c["ref"], "ref_text": c["bank_text"],
                                      "speed": engine["speed"], "seed": 1000 + k, "out": str(out), "skip_existing": True})
                        meta[key] = {"pid": pid, "line": s["id"], "take": k, "text": s["tr"], "slot_s": s["slot_s"],
                                     "speaker": f"{uid}:{s['speaker']}"}
            if not items:
                continue
            todo = sum(1 for it in items if not Path(it["out"]).exists())
            self.log(f"voice {lang}: {len(items)} takes for {len(dub)} videos ({todo} to make), one model load")
            if todo:
                if not pip(ctx, "omnivoice"):
                    raise RuntimeError("pip install omnivoice failed")
                man = ctx.work / f"gen_{lang}.json"
                man.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
                from app import langs as L
                t = time.time()
                self.log(f"voicing {todo} {lang} takes with OmniVoice ({engine['steps']} steps): loading the model, "
                         "then a progress line every 30 s")
                sh([sys.executable, TTS / "omnivoice_gen.py", "--model", engine["model"], "--manifest", man,
                    "--out", ctx.work / f"gen_{lang}_res.json", "--steps", str(engine["steps"]),
                    "--language", L.name(lang), "--batch", str(engine.get("batch", 1))], ctx, timeout=12 * 3600)
                self.log(f"voiced {todo} takes in {time.time() - t:.0f} s")
            made = [it for it in items if Path(it["out"]).exists()]
            sman = ctx.work / f"score_{lang}.json"
            sman.write_text(json.dumps({"speakers": speakers, "items": [
                {"key": it["key"], "wav": it["out"], "speaker": meta[it["key"]]["speaker"], "text": it["text"],
                 "slot_s": meta[it["key"]]["slot_s"]} for it in made]}, ensure_ascii=False), encoding="utf-8")
            res = ctx.work / f"score_{lang}_res.json"
            asr = (self.opt.get("aligners") or {}).get(lang) or "none"
            self.log(f"scoring {len(made)} {lang} takes (voice likeness" + ("" if asr == "none" else ", read back by ASR")
                     + ") to pick the best take per line")
            t = time.time()
            sh([sys.executable, TTS / "score.py", "--manifest", sman, "--out", res, "--no-emotion", "--asr", asr], ctx)
            scores = json.loads(res.read_text(encoding="utf-8"))["items"] if res.exists() else {}
            self.log(f"scored {len(scores)} takes in {time.time() - t:.0f} s")
            per: dict[str, dict] = {}
            for it in made:
                m, sc = meta[it["key"]], scores.get(it["key"], {})
                t = {"take": m["take"], "path": it["out"], "text": m["text"],
                     **{k: sc.get(k) for k in ("sim", "cer", "dur", "dur_s", "asr")}}
                per.setdefault(m["pid"], {}).setdefault(m["line"], {"takes": []})["takes"].append(t)
            for pid, lines in per.items():
                for ln in lines.values():
                    ln["best"] = max(ln["takes"], key=take_score)["take"]
                with self.lock:
                    A.voice.record_takes(pid, lang, f"run-{self.id}", lines)
        for pid in dub:
            self.mark(self.uid[pid], "voice", "done")

    # ---- mix (CPU) -------------------------------------------------------------------------
    def mix(self) -> None:
        A = self.app

        def one(pid: str, lang: str) -> None:
            t = time.time()
            A.mix.render(pid, lang)
            A.mix.export(pid, lang)
            self.log(f"mixed and exported {A.project.get(pid)['name'][:50]} ({lang}) in {time.time() - t:.0f} s")

        jobs = [(pid, lang) for pid in self.dub_set() for lang in self.langs_of(pid)]
        with ThreadPoolExecutor(max_workers=int(self.opt.get("mix_threads", 2))) as ex:
            for f in [ex.submit(one, pid, lang) for pid, lang in jobs]:
                try:
                    f.result()
                except Exception as e:
                    self.log(f"mix failed: {str(e)[-300:]}")
        for pid in self.dub_set():
            self.mark(self.uid[pid], "mix", "done")


def _write_wav(path: Path, x) -> None:
    """16 kHz mono float → 16-bit wav (standard library only)."""
    import wave

    import numpy as np

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _norm(w: str) -> str:
    return "".join(ch for ch in w.lower() if ch.isalnum() or ch == "'")


def compare(ref: dict, hyp: dict) -> dict:
    """How far a transcript (captions) is from another (Whisper): word error rate, and
    for matching words how far apart their start times are."""
    a = [(_norm(w["w"]), w["start"]) for s in ref["segments"] for w in s["words"] if _norm(w["w"])]
    b = [(_norm(w["w"]), w["start"]) for s in hyp["segments"] for w in s["words"] if _norm(w["w"])]
    sm = difflib.SequenceMatcher(a=[x[0] for x in a], b=[x[0] for x in b], autojunk=False)
    errors = 0
    deltas = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            deltas += [abs(a[i][1] - b[j][1]) for i, j in zip(range(i1, i2), range(j1, j2))]
        else:
            errors += max(i2 - i1, j2 - j1)
    deltas.sort()
    return {"words": len(a), "wer": round(errors / max(1, len(a)), 3),
            "timing_median_s": round(deltas[len(deltas) // 2], 3) if deltas else None,
            "timing_p90_s": round(deltas[int(len(deltas) * 0.9)], 3) if deltas else None}
