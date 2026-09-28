"""Work packages: a published work travels between teams as one `.lbwork` zip.

The format and its rules are in docs/PACKAGE.md. In short: the language-neutral work
(sources, lines, chapters, speakers, cast with voice banks, library) always travels;
target languages travel only when chosen; local state (paths, jobs, workers, settings)
never does. Everything is matched by uid, and importing a work that is already here
adds and fills in without overwriting what people decided.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from . import db, project, series, settings

FORMAT, VERSION = "lang-bridge.work", 1
MEDIA = ("none", "opus", "flac", "ref")  # ref: media stay where they are, referenced under a device root
STEMS = ("audio", "vocals", "background")


# ---- export --------------------------------------------------------------------------------
def _library_of(sid: str) -> dict | None:
    """The library a work was found in (its identity travels, so the same teacher is
    recognised across the library's works wherever they are processed)."""
    lid = (db.row("SELECT library_id FROM series WHERE id=?", sid) or {}).get("library_id")
    if not lid:
        return None
    lib = db.row("SELECT uid, name FROM libraries WHERE id=?", lid)
    return {"uid": lib["uid"], "name": lib["name"]} if lib else {"uid": lid, "name": None}


def _rel(path, root: Path | None) -> str | None:
    """A path as seen from a device root (posix; "../" for a folder beside it on the same
    drive, e.g. a folder of videos elsewhere in My Drive), or None if it is elsewhere."""
    if not path or root is None:
        return None
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()
    except (ValueError, OSError):  # another drive
        return None


def export(sid: str, langs: list[str] | None = None, media: str = "opus", takes: bool = False, note: str = "",
           out: Path | None = None, ref_root: Path | None = None) -> Path:
    """Write the work (and the chosen languages) to data/exports/<work>-<time>.lbwork (or
    ``out``). ``media="ref"`` copies no media: files under ``ref_root`` (a device's job
    folder, e.g. the Drive LangBridge folder) are referenced by their path there, and
    every take of the chosen languages travels as a reference too."""
    if media not in MEDIA:
        raise ValueError(f"media must be one of {', '.join(MEDIA)}")
    w = series.get(sid)
    langs = list(w["targets"] if langs is None else langs)
    srcs = db.rows("SELECT * FROM projects WHERE series_id=? ORDER BY position, created", sid)
    out = out or db.DATA / "exports" / f"{sid}-{time.strftime('%Y%m%d-%H%M%S')}.lbwork"
    out.parent.mkdir(parents=True, exist_ok=True)
    uid_of = {p["id"]: p["uid"] for p in srcs}
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, obj) -> None:
            z.writestr(name, json.dumps(obj, ensure_ascii=False, indent=1))

        put("work.json", {"format": FORMAT, "version": VERSION, "exported_at": time.time(), "note": note,
                          "media": media, "languages": langs,
                          "work": {k: w[k] for k in ("uid", "name", "kind", "src_lang", "targets", "feed_url", "rights", "settings")}
                          | {"library": _library_of(sid)},
                          # where referenced media are, from this file: opened as it lies, no questions
                          "ref_root": Path(os.path.relpath(Path(ref_root).resolve(), out.parent.resolve())).as_posix()
                          if media == "ref" and ref_root is not None else None})
        for p in srcs:
            base, d = f"sources/{p['uid']}/", project.pdir(p["id"])
            meta = json.loads(p["meta"] or "{}")
            refs = None
            if media == "ref":
                have = lambda f: _rel(f, ref_root) if f and Path(f).exists() else None  # noqa: E731 - only real files
                refs = {"dir": _rel(meta.get("media_dir"), ref_root), "video": have(p["video"]),
                        "audio": have(p["audio"]),
                        "stems": {n: have(project.stem(p["id"], n)) for n in ("vocals", "background")},
                        "exports": {lang: {k: have(v) if k == "mp4" else v for k, v in e.items()}
                                    for lang, e in (meta.get("exports") or {}).items()},
                        "subtitles": have(meta.get("subtitles"))}
            put(base + "source.json", {**{k: p[k] for k in ("uid", "name", "source", "origin_id", "published", "position",
                                                            "clip_start", "clip_end", "duration", "src_lang", "max_speakers")},
                                       "mix": meta.get("mix"), "chapter_seq": meta.get("chapter_seq"), "refs": refs,
                                       "transcript": meta.get("transcript"),
                                       # how the device finds this source's files (library videos, subtitles)
                                       "device_refs": meta.get("refs"), "library": meta.get("library")})
            lines = db.rows("SELECT id, start, end, speaker, text, words, reviewed, mode FROM sentences WHERE project_id=?"
                            " ORDER BY start", p["id"])
            for ln in lines:
                ln["words"] = json.loads(ln["words"] or "[]")
            put(base + "lines.json", lines)
            put(base + "chapters.json", db.rows("SELECT id, start, title FROM chapters WHERE project_id=? ORDER BY start", p["id"]))
            dia = d / "diarization.json"
            put(base + "speakers.json", {
                "centroids": (json.loads(dia.read_text(encoding="utf-8")).get("centroids") or {}) if dia.exists() else {},
                "appearances": db.rows("SELECT label, character_uid, status, score, talk_s FROM appearances WHERE source_id=?",
                                       p["id"])})
            if media in ("opus", "flac"):
                for name, f in (("audio", Path(p["audio"] or d / "clip.flac")), ("vocals", d / "vocals.flac"),
                                ("background", d / "background.flac")):
                    if f.exists():
                        enc = Path(tmp) / f"{p['uid']}-{name}.{'opus' if media == 'opus' else 'flac'}"
                        codec = ["-c:a", "libopus", "-b:a", "96k"] if media == "opus" else ["-c:a", "flac"]
                        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-vn", *codec, str(enc)], check=True)
                        z.write(enc, base + f"media/{name}{enc.suffix}")

        people = []
        # the work's own characters, and people of its library who appear in it
        for c in db.rows("SELECT * FROM cast WHERE series_id=? OR uid IN (SELECT a.character_uid FROM appearances a"
                         " JOIN projects p ON p.id=a.source_id WHERE p.series_id=?) ORDER BY created", sid, sid):
            bank = []
            for r in db.rows("SELECT * FROM cast_bank WHERE character_uid=?", c["uid"]):
                if r["source_id"] not in uid_of or not r["path"] or not Path(r["path"]).exists():
                    continue
                name = f"cast/{c['uid']}/{Path(r['path']).name}"
                z.write(r["path"], name)
                bank.append({"source_uid": uid_of[r["source_id"]], **{k: r[k] for k in ("line_id", "start", "end", "text", "role", "manual")},
                             "file": name})
            names = {r["lang"]: r["name"] for r in db.rows("SELECT lang, name FROM cast_names WHERE character_uid=?", c["uid"])
                     if r["lang"] in langs}
            people.append({**{k: c[k] for k in ("uid", "name", "gender", "role", "notes", "color", "important", "auto")},
                           "names": names, "bank": bank})
        put("cast.json", people)

        clips, in_work = [], set()
        for c in db.rows("SELECT * FROM clips WHERE series_id=? AND deleted=0 ORDER BY id", sid):
            revs = []
            for r in db.rows("SELECT rev, segments FROM clip_revisions WHERE clip_id=? ORDER BY rev", c["id"]):
                segs = [{"source_uid": uid_of.get(s["source_id"]), "start": s["start"], "end": s["end"]}
                        for s in json.loads(r["segments"])]
                revs.append({"rev": r["rev"], "segments": segs})
            occ = [{"source_uid": uid_of.get(o["source_id"]), **{k: o[k] for k in ("start", "end", "score", "status")}}
                   for o in db.rows("SELECT * FROM clip_occurrences WHERE clip_id=?", c["id"]) if o["source_id"] in uid_of]
            clips.append({**{k: c[k] for k in ("uid", "title", "kind", "note", "created")},
                          "source_uid": uid_of.get(c["source_id"]), "revisions": revs, "occurrences": occ})
            in_work.add(c["id"])
        colls = []
        for col in db.rows("SELECT * FROM collections WHERE deleted=0"):
            members = [r["item_id"] for r in db.rows("SELECT item_id FROM collection_items WHERE collection_id=? AND item_type='clip'",
                                                     col["id"]) if r["item_id"] in in_work]
            if members:
                uids = {r["id"]: r["uid"] for r in db.rows("SELECT id, uid FROM clips")}
                colls.append({"uid": col["uid"], "name": col["name"], "clips": [uids[m] for m in members]})
        put("library.json", {"clips": clips, "collections": colls})

        for lang in langs:
            put(f"languages/{lang}/translations.json", {
                p["uid"]: db.rows("SELECT sentence_id AS line_id, text, locked, provenance FROM translations"
                                  " WHERE project_id=? AND lang=? AND text<>''", p["id"], lang) for p in srcs})
            put(f"languages/{lang}/profile.json", {
                "aligner": settings.aligner(lang),
                "rates": {p["uid"]: (json.loads(p["meta"] or "{}").get("rates") or {}).get(lang) for p in srcs}})
            if media == "ref":  # every take, where it is (the receiving side picks or keeps the choice)
                put(f"languages/{lang}/takes_ref.json", [
                    {"source_uid": p["uid"], "line_id": t["sentence_id"], "ref": _rel(t["path"], ref_root),
                     **{k: t[k] for k in ("job_id", "take", "text", "sim", "cer", "dur", "dur_s", "asr", "chosen")}}
                    for p in srcs for t in db.rows("SELECT * FROM takes WHERE project_id=? AND lang=?", p["id"], lang)
                    if _rel(t["path"], ref_root)])
            elif takes:
                chosen = []
                for p in srcs:
                    for t in db.rows("SELECT * FROM takes WHERE project_id=? AND lang=? AND chosen=1", p["id"], lang):
                        if t["path"] and Path(t["path"]).exists():
                            name = f"languages/{lang}/takes/{p['uid']}/{t['sentence_id']}{Path(t['path']).suffix}"
                            z.write(t["path"], name)
                            chosen.append({"source_uid": p["uid"], "line_id": t["sentence_id"], "file": name,
                                           **{k: t[k] for k in ("text", "sim", "cer", "dur", "dur_s", "asr")}})
                put(f"languages/{lang}/takes.json", chosen)
    return out


# ---- import --------------------------------------------------------------------------------
def inspect(path: str | Path) -> dict:
    """What a package holds, without importing it."""
    with zipfile.ZipFile(path) as z:
        w = _manifest(z)
        n = len([x for x in z.namelist() if x.endswith("/source.json")])
    here = db.row("SELECT id FROM series WHERE uid=?", w["work"]["uid"])
    return w | {"sources": n, "here": here["id"] if here else None}


def _manifest(z: zipfile.ZipFile) -> dict:
    w = json.loads(z.read("work.json"))
    if w.get("format") != FORMAT:
        raise ValueError("not a Lang-Bridge work package")
    if int(w.get("version", 0)) > VERSION:
        raise ValueError(f"made by a newer Lang-Bridge (package version {w['version']}); update this app first")
    return w


def import_work(path: str | Path, fetch: bool = True, ref_root: Path | None = None) -> dict:
    """Bring a package into this library. A new work is created; a work already here
    (same uid) gains what it lacks, and nothing people decided here is overwritten.
    ``ref_root`` resolves referenced media (packages made with media "ref"): this
    machine's path of the device folder they were referenced under. Returns a report
    of what landed and what was kept or needs attention."""
    rep: dict = {"sources": {"added": [], "matched": []}, "lines": 0, "characters": {"added": 0, "matched": 0},
                 "clips": {"added": 0, "matched": 0}, "translations": {}, "fetching": [], "notes": []}
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        wj = _manifest(z)
        if ref_root is None and wj.get("ref_root"):  # a results package opened where it was written
            ref_root = Path(os.path.normpath(Path(path).resolve().parent / wj["ref_root"]))
        w = wj["work"]
        names = z.namelist()
        here = db.row("SELECT id FROM series WHERE uid=?", w["uid"])
        if here:
            sid = here["id"]
            rep["created"] = False
        else:
            sid = series._slug(w["name"])
            db.run("INSERT INTO series (id,name,kind,feed_url,src_lang,targets,settings,created,uid,rights)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?)", sid, w["name"], w["kind"], w.get("feed_url"), w["src_lang"],
                   json.dumps(w["targets"]), json.dumps(w.get("settings") or {}), time.time(), w["uid"], w.get("rights") or "")
            rep["created"] = True
        rep["work"] = sid
        if w.get("library") and not db.row("SELECT library_id FROM series WHERE id=?", sid)["library_id"]:
            here_lib = db.row("SELECT id FROM libraries WHERE uid=?", w["library"]["uid"])
            db.run("UPDATE series SET library_id=? WHERE id=?", here_lib["id"] if here_lib else w["library"]["uid"], sid)
        targets = list(series.get(sid)["targets"])
        for lang in wj.get("languages", []):  # the languages that arrive become the work's too
            if lang not in targets:
                targets.append(lang)
        db.run("UPDATE series SET targets=? WHERE id=?", json.dumps(targets), sid)

        # the cast first: appearances and banks point at it
        people = json.loads(z.read("cast.json"))
        for c in people:
            cur = db.row("SELECT * FROM cast WHERE uid=?", c["uid"])
            if cur:
                rep["characters"]["matched"] += 1
                for k in ("gender", "role", "notes"):  # fill blanks only
                    if not cur[k] and c.get(k):
                        db.run(f"UPDATE cast SET {k}=? WHERE uid=?", c[k], c["uid"])
                if cur["auto"] and not c["auto"]:  # their name beats our automatic "Speaker 2"
                    db.run("UPDATE cast SET name=?, auto=0 WHERE uid=?", c["name"], c["uid"])
            else:
                rep["characters"]["added"] += 1
                db.run("INSERT INTO cast (uid,series_id,name,gender,role,notes,color,important,auto,created,updated)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?,?)", c["uid"], sid, c["name"], c.get("gender"), c.get("role") or "",
                       c.get("notes") or "", c.get("color") or 0, c.get("important", 1), c.get("auto", 0), time.time(), time.time())
            for lang, name in (c.get("names") or {}).items():
                have = db.row("SELECT name FROM cast_names WHERE character_uid=? AND lang=?", c["uid"], lang)
                if not have:
                    db.run("INSERT INTO cast_names (character_uid,lang,name) VALUES (?,?,?)", c["uid"], lang, name)
                elif have["name"] != name:
                    rep["notes"].append(f"kept this library's {lang} name '{have['name']}' for {c['name']} (package: '{name}')")

        pid_of: dict[str, str] = {}
        need_fetch: list[str] = []
        found = [(json.loads(z.read(x)), x[: -len("source.json")]) for x in names
                 if x.startswith("sources/") and x.endswith("/source.json")]
        for sj, base in sorted(found, key=lambda f: (f[0].get("position") or 0, f[0]["name"])):  # the work's order
            local = db.row("SELECT id FROM projects WHERE uid=?", sj["uid"])
            if local:
                pid = local["id"]
                rep["sources"]["matched"].append(pid)
                lines = json.loads(z.read(base + "lines.json"))
                if lines and not db.row("SELECT 1 FROM sentences WHERE project_id=?", pid):
                    _insert_lines(pid, lines, json.loads(z.read(base + "chapters.json")))  # none here yet: take them all
                    rep["lines"] += len(lines)
                else:
                    rep["lines"] += _merge_lines(pid, lines, rep)
            else:
                pid = _new_source(sid, sj, targets)
                rep["sources"]["added"].append(pid)
                lines = json.loads(z.read(base + "lines.json"))
                _insert_lines(pid, lines, json.loads(z.read(base + "chapters.json")))
                rep["lines"] += len(lines)
            pid_of[sj["uid"]] = pid
            if sj.get("refs") and ref_root is not None:
                _place_refs(pid, sj["refs"], ref_root)
            if sj.get("transcript"):
                db.set_meta(pid, transcript=sj["transcript"])
            if sj.get("device_refs") and not db.meta(pid).get("refs"):
                db.set_meta(pid, refs=sj["device_refs"])
            if sj.get("library") and not db.meta(pid).get("library"):
                db.set_meta(pid, library=sj["library"])
            spk = json.loads(z.read(base + "speakers.json"))
            dia = project.pdir(pid) / "diarization.json"
            if spk.get("centroids") and not dia.exists():  # voices keep matching in this library
                dia.write_text(json.dumps({"centroids": spk["centroids"], "turns": [], "exclusive": []}), encoding="utf-8")
            for a in spk.get("appearances", []):
                if not db.row("SELECT 1 FROM appearances WHERE source_id=? AND label=?", pid, a["label"]):
                    db.run("INSERT INTO appearances (source_id,label,character_uid,score,status,talk_s,updated) VALUES (?,?,?,?,?,?,?)",
                           pid, a["label"], a["character_uid"], a.get("score"), a.get("status") or "confirmed",
                           a.get("talk_s") or 0, time.time())
            _place_media(z, base, pid, tmp)
            if fetch and not _has_media(pid):
                need_fetch.append(pid)

        for c in people:  # banks, now that the sources exist
            for b in c.get("bank", []):
                src = pid_of.get(b["source_uid"])
                if not src or db.row("SELECT 1 FROM cast_bank WHERE character_uid=? AND source_id=? AND line_id=?",
                                     c["uid"], src, b["line_id"]):
                    continue
                dest = db.DATA / "works" / w["uid"] / "cast" / c["uid"] / Path(b["file"]).name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(b["file"]))
                db.run("INSERT OR IGNORE INTO cast_bank (character_uid,source_id,line_id,start,end,text,role,manual,path,added)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?)", c["uid"], src, b["line_id"], b["start"], b["end"], b["text"],
                       b["role"], b["manual"], str(dest), time.time())

        if need_fetch:
            _fetch_media(sid, need_fetch)
            rep["fetching"] = need_fetch
        _import_library(json.loads(z.read("library.json")), sid, pid_of, rep)
        for lang in wj.get("languages", []):
            _import_language(z, lang, pid_of, rep, ref_root)
    return rep


def _insert_lines(pid: str, lines: list[dict], chapters: list[dict]) -> None:
    db.many("INSERT OR REPLACE INTO sentences (project_id,id,speaker,start,end,text,words,reviewed,mode) VALUES (?,?,?,?,?,?,?,?,?)",
            [(pid, ln["id"], ln["speaker"], ln["start"], ln["end"], ln["text"], json.dumps(ln.get("words") or []),
              ln.get("reviewed", 0), ln.get("mode")) for ln in lines])
    db.run("DELETE FROM chapters WHERE project_id=?", pid)
    db.many("INSERT INTO chapters (project_id,id,start,title,updated) VALUES (?,?,?,?,?)",
            [(pid, c["id"], c["start"], c.get("title") or "", time.time()) for c in chapters])


def _place_refs(pid: str, refs: dict, root: Path) -> None:
    """Media a device left in its folder: point this source at them (nothing copied)."""
    at = lambda rel: os.path.normpath(Path(root) / rel) if rel else None  # noqa: E731
    if refs.get("video") or refs.get("audio"):
        db.run("UPDATE projects SET video=COALESCE(?, video), audio=COALESCE(?, audio) WHERE id=?",
               at(refs.get("video")), at(refs.get("audio")), pid)
    meta = {}
    if refs.get("dir"):
        meta["media_dir"] = at(refs["dir"])
    stems = {n: at(r) for n, r in (refs.get("stems") or {}).items() if r}
    if stems:
        meta["stems"] = stems
    ex = {lang: {**e, "mp4": at(e.get("mp4"))} for lang, e in (refs.get("exports") or {}).items() if e.get("mp4")}
    if ex:
        meta["exports"] = (db.meta(pid).get("exports") or {}) | ex
    if refs.get("subtitles"):
        meta["subtitles"] = at(refs["subtitles"])
    if meta:
        db.set_meta(pid, **meta)


def _new_source(sid: str, sj: dict, targets: list[str]) -> str:
    pid = project.slug(sj["name"])
    meta = {k: sj[k] for k in ("mix", "chapter_seq") if sj.get(k) is not None}
    if len(targets) > 1:
        meta["targets"] = targets[1:]
    db.run("INSERT INTO projects (id,name,source,src_lang,tgt_lang,max_speakers,clip_start,clip_end,duration,created,"
           "series_id,position,origin_id,published,uid,meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           pid, sj["name"], sj.get("source"), sj.get("src_lang") or "en", targets[0], sj.get("max_speakers"),
           sj.get("clip_start"), sj.get("clip_end"), sj.get("duration"), time.time(), sid, sj.get("position"),
           sj.get("origin_id"), sj.get("published"), sj["uid"], json.dumps(meta))
    return pid


def _merge_lines(pid: str, lines: list[dict], rep: dict) -> int:
    """A source already here: a line a person reviewed there fills in one only a machine
    wrote here; a line reviewed on both sides and different is reported, never replaced."""
    n = 0
    for ln in lines:
        cur = db.row("SELECT * FROM sentences WHERE project_id=? AND id=?", pid, ln["id"])
        if not cur or abs(cur["start"] - ln["start"]) > 0.05:
            continue  # the transcripts have diverged here; this library's lines stand
        if ln.get("reviewed") and not cur["reviewed"]:
            db.run("UPDATE sentences SET text=?, speaker=?, reviewed=1 WHERE project_id=? AND id=?",
                   ln["text"], ln["speaker"], pid, ln["id"])
            n += 1
        elif ln.get("reviewed") and cur["reviewed"] and (ln["text"], ln["speaker"]) != (cur["text"], cur["speaker"]):
            rep["notes"].append(f"{pid} line {ln['id']}: reviewed differently in both libraries; kept this one")
    return n


def _place_media(z: zipfile.ZipFile, base: str, pid: str, tmp: str) -> None:
    d = project.pdir(pid)
    for name in STEMS:
        src = next((x for x in z.namelist() if x.startswith(base + f"media/{name}.")), None)
        dest = d / ("clip.flac" if name == "audio" else f"{name}.flac")
        if not src or dest.exists():
            continue
        t = Path(tmp) / Path(src).name
        t.write_bytes(z.read(src))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(t), "-ac", "1" if name == "audio" else "2",
                        "-ar", "44100", "-c:a", "flac", str(dest)], check=True)
        if name == "audio":
            db.run("UPDATE projects SET audio=? WHERE id=?", str(dest), pid)


def _fetch_media(sid: str, pids: list[str]) -> None:
    """Media that did not travel: a Colab worker fetches them into Drive when Colab is
    the active job folder (nothing through this PC); otherwise they are fetched here."""
    from . import bulk

    if settings.root()["kind"] == "colab":
        bulk.queue(sid, settings.root()["id"], steps=["fetch"], ids=pids)
    else:
        for pid in pids:
            project.refetch(pid)


def _has_media(pid: str) -> bool:
    p = project.get(pid)
    d = project.pdir(pid)
    return bool(p["video"] and Path(p["video"]).exists() and (d / "vocals.flac").exists())


def _import_library(lib: dict, sid: str, pid_of: dict[str, str], rep: dict) -> None:
    ids = {}
    for c in lib.get("clips", []):
        cur = db.row("SELECT id FROM clips WHERE uid=?", c["uid"])
        if cur:
            cid = cur["id"]
            rep["clips"]["matched"] += 1
        else:
            conn = db.conn()
            cid = conn.execute("INSERT INTO clips (series_id,source_id,title,kind,note,created,updated,uid) VALUES (?,?,?,?,?,?,?,?)",
                               (sid, pid_of.get(c["source_uid"]), c["title"], c["kind"], c.get("note") or "",
                                c.get("created") or time.time(), time.time(), c["uid"])).lastrowid
            conn.commit()
            for r in c["revisions"]:
                segs = [{"source_id": pid_of.get(s["source_uid"]), "start": s["start"], "end": s["end"]} for s in r["segments"]]
                db.run("INSERT INTO clip_revisions (clip_id,rev,segments,created) VALUES (?,?,?,?)", cid, r["rev"],
                       json.dumps(segs), time.time())
            rep["clips"]["added"] += 1
        ids[c["uid"]] = cid
        for o in c.get("occurrences", []):
            src = pid_of.get(o["source_uid"])
            if src and not db.row("SELECT 1 FROM clip_occurrences WHERE clip_id=? AND source_id=? AND ABS(start-?) < 1",
                                  cid, src, o["start"]):
                db.run("INSERT INTO clip_occurrences (clip_id,source_id,start,end,score,status,updated) VALUES (?,?,?,?,?,?,?)",
                       cid, src, o["start"], o["end"], o.get("score"), o.get("status") or "proposed", time.time())
    for col in lib.get("collections", []):
        cur = db.row("SELECT id FROM collections WHERE uid=?", col["uid"])
        if cur:
            colid = cur["id"]
        else:
            conn = db.conn()
            colid = conn.execute("INSERT INTO collections (name,created,uid) VALUES (?,?,?)",
                                 (col["name"], time.time(), col["uid"])).lastrowid
            conn.commit()
        for u in col["clips"]:
            if u in ids:
                db.run("INSERT OR IGNORE INTO collection_items (collection_id,item_type,item_id,added) VALUES (?,?,?,?)",
                       colid, "clip", ids[u], time.time())


def _import_language(z: zipfile.ZipFile, lang: str, pid_of: dict[str, str], rep: dict, ref_root: Path | None = None) -> None:
    r = rep["translations"].setdefault(lang, {"written": 0, "kept_here": 0, "conflicts": 0})
    tr = json.loads(z.read(f"languages/{lang}/translations.json"))
    for suid, rows in tr.items():
        pid = pid_of.get(suid)
        if not pid:
            continue
        if lang not in project.targets(pid):
            project.add_target(pid, lang)
        for t in rows:
            cur = db.row("SELECT * FROM translations WHERE project_id=? AND sentence_id=? AND lang=?", pid, t["line_id"], lang)
            if cur and cur["text"] == t["text"]:
                continue
            ours_by_person = cur and cur["text"] and (cur["locked"] or cur["provenance"] != "machine")
            theirs_by_person = t["locked"] or t["provenance"] != "machine"
            if cur and cur["text"] and (ours_by_person or not theirs_by_person):
                r["kept_here"] += 1
                r["conflicts"] += int(bool(ours_by_person and theirs_by_person))
                continue
            db.run("INSERT INTO translations (project_id,sentence_id,lang,text,locked,provenance,updated) VALUES (?,?,?,?,?,?,?)"
                   " ON CONFLICT (project_id,sentence_id,lang) DO UPDATE SET text=excluded.text, locked=excluded.locked,"
                   " provenance=excluded.provenance, updated=excluded.updated",
                   pid, t["line_id"], lang, t["text"], t["locked"], t["provenance"], time.time())
            r["written"] += 1
    prof = json.loads(z.read(f"languages/{lang}/profile.json"))
    for suid, rate in (prof.get("rates") or {}).items():
        pid = pid_of.get(suid)
        if pid and rate and not (db.meta(pid).get("rates") or {}).get(lang):
            db.set_meta(pid, rates=(db.meta(pid).get("rates") or {}) | {lang: rate})
    if prof.get("aligner") and not settings.aligner(lang):
        rep["notes"].append(f"the sender aligns {lang} with {prof['aligner']}; add it in Settings to use it here")
    ref = f"languages/{lang}/takes_ref.json"
    if ref in z.namelist() and ref_root is not None:
        for t in json.loads(z.read(ref)):
            pid = pid_of.get(t["source_uid"])
            if not pid or db.row("SELECT 1 FROM takes WHERE project_id=? AND sentence_id=? AND job_id=? AND take=?",
                                 pid, t["line_id"], t["job_id"], t["take"]):
                continue
            if t["chosen"]:  # a choice made there stands unless one was made here
                if db.row("SELECT 1 FROM takes WHERE project_id=? AND sentence_id=? AND lang=? AND chosen=1", pid, t["line_id"], lang):
                    t["chosen"] = 0
            db.run("INSERT INTO takes (project_id,sentence_id,job_id,take,path,text,sim,cer,dur,dur_s,asr,chosen,created,lang)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pid, t["line_id"], t["job_id"], t["take"],
                   os.path.normpath(Path(ref_root) / t["ref"]), t["text"], t.get("sim"), t.get("cer"), t.get("dur"), t.get("dur_s"),
                   t.get("asr"), t["chosen"], time.time(), lang)
    name = f"languages/{lang}/takes.json"
    if name in z.namelist():
        for t in json.loads(z.read(name)):
            pid = pid_of.get(t["source_uid"])
            if not pid or db.row("SELECT 1 FROM takes WHERE project_id=? AND sentence_id=? AND lang=? AND chosen=1",
                                 pid, t["line_id"], lang):
                continue
            dest = project.pdir(pid) / "takes" / f"imported-{lang}-{t['line_id']}{Path(t['file']).suffix}"
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(z.read(t["file"]))
            db.run("INSERT OR REPLACE INTO takes (project_id,sentence_id,job_id,take,path,text,sim,cer,dur,dur_s,asr,chosen,created,lang)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)", pid, t["line_id"], f"import-{lang}", 0, str(dest), t["text"],
                   t.get("sim"), t.get("cer"), t.get("dur"), t.get("dur_s"), t.get("asr"), time.time(), lang)

