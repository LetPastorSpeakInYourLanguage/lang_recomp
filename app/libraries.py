"""Libraries: folders of videos on a device, catalogued as works you can explore and run.

A library is a folder that uploaders push videos into, on the device that will process
it — in Google Drive (run by Colab; seen here through Drive for Desktop) or on this PC's
disks (run by the local worker). The folder standard is docs/LIBRARY_FOLDERS.md:

    <library>/
      library.json                       optional defaults: language, targets, kind
      <work>/                            a series, teaching series, podcast, course, show…
        work.json                        optional: title, kind, language, speakers, targets
        01 - <episode title>.mp4         episodes, ordered by their leading number
        01 - <episode title>.srt         optional subtitles in the spoken language
        01 - <episode title>.am.srt      optional subtitles in another language
        <Season 2>/ …                    optional groups, any depth
      _Standalone/<title>.mp4            single videos (each its own work)

Scanning reads names only (never the videos) and is lenient with folders that do not
follow the standard: the top folder is the work, deeper folders are groups, files at the
top are standalone. A language in a name — ``[hi]`` / ``.hi`` before the extension, or a
folder named after a language — marks a version in that language. Every video plays at
once from where it is; rescanning adds what is new and keeps what was done.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import db, langs, project, series, settings

MEDIA = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus"}
SUBS = (".srt", ".vtt")
STANDALONE = "_standalone"
SKIP = re.compile(r"^(desktop\.ini|thumbs\.db|\..*)$", re.I)
LANG_TAG = re.compile(r"(?:\[([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)?)\]|\.([a-z]{2,3}))$")


def _natural(s: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def create(name: str, root_id: str, path: str, src_lang: str = "en", targets: list[str] | None = None,
           kind: str = "other") -> dict:
    """Register a folder of videos with the device that will run it. The folder must be
    where that device can read it: in the same Google Drive as a Colab job folder, or on
    this PC for the local worker."""
    r = settings.root(root_id)
    f = Path(path)
    if not f.is_dir():
        raise ValueError(f"not a folder: {path}")
    if r["kind"] == "colab":
        drive = Path(r["path"]).parent  # e.g. G:/My Drive
        try:
            f.resolve().relative_to(drive.resolve())
        except ValueError:
            raise ValueError(f"a Colab library must be in the same Google Drive ({drive})")
    project.check_lang(src_lang)
    lid = series._slug(name) + "-lib"
    while db.row("SELECT 1 FROM libraries WHERE id=?", lid):
        lid += "-2"
    db.run("INSERT INTO libraries (id,uid,name,root_id,path,src_lang,targets,kind,created) VALUES (?,?,?,?,?,?,?,?,?)",
           lid, db.new_uid(), name.strip(), root_id, str(f), src_lang, json.dumps(targets or ["am"]), kind, time.time())
    return get(lid)


def get(lid: str) -> dict:
    lib = db.row("SELECT * FROM libraries WHERE id=?", lid)
    if not lib:
        raise KeyError(lid)
    lib["targets"] = json.loads(lib["targets"] or "[]")
    return lib


def listing() -> list[dict]:
    out = []
    for r in db.rows("SELECT id FROM libraries ORDER BY created"):
        lib = get(r["id"])
        lib["counts"] = {"works": db.row("SELECT COUNT(*) n FROM series WHERE library_id=?", lib["id"])["n"],
                         "videos": db.row("SELECT COUNT(*) n FROM projects p JOIN series s ON s.id=p.series_id"
                                          " WHERE s.library_id=?", lib["id"])["n"]}
        out.append(lib)
    return out


def device_ref(root_id: str, file: Path) -> str:
    """How a device finds a file: Colab, by a path relative to its job folder on the same
    Drive ("root:../My Library/…"); this PC's worker, by its full path ("file:E:/…")."""
    r = settings.root(root_id)
    if r["kind"] == "colab":
        return "root:" + Path(os.path.relpath(Path(file).resolve(), Path(r["path"]).resolve())).as_posix()
    return "file:" + Path(file).resolve().as_posix()


def _lang_of(stem: str) -> tuple[str, str | None]:
    """'01 - Title [hi]' / '01 - Title.hi' → ('01 - Title', 'hi'); else (stem, None)."""
    m = LANG_TAG.search(stem)
    if m:
        code = (m.group(1) or m.group(2)).lower()
        if code in langs.KNOWN or m.group(1):
            return stem[: m.start()].rstrip(" ._-"), code
    return stem, None


def title_of(stem: str) -> str:
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()


def subtitles_for(f: Path) -> dict[str, Path]:
    """Subtitles beside a video: '<name>.srt' (spoken language) and '<name>.<lang>.srt'."""
    out: dict[str, Path] = {}
    for ext in SUBS:
        if f.with_suffix(ext).exists():
            out.setdefault("", f.with_suffix(ext))
        for p in f.parent.glob(f"{glob_escape(f.stem)}.*{ext}"):
            code = p.name[len(f.stem) + 1: -len(ext)].lower()
            if code and (code in langs.KNOWN or re.fullmatch(r"[a-z]{2,3}", code)):
                out.setdefault(code, p)
    return out


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def _work_of(rel: tuple[str, ...]) -> tuple[str, bool]:
    """(work folder name, standalone?) for a file's path inside the library."""
    if len(rel) == 1:
        return Path(rel[0]).stem, True
    if rel[0].lower() == STANDALONE:
        return Path(rel[-1]).stem, True
    return rel[0], False


def scan(lid: str) -> dict:
    """Walk the library folder; add works and videos that are new; refresh subtitles.
    Reads names (and the small work.json / library.json) only."""
    lib = get(lid)
    base = Path(lib["path"])
    defaults = _read_json(base / "library.json")
    found: dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            f = Path(dirpath) / fn
            if SKIP.match(fn) or f.suffix.lower() not in MEDIA:
                continue
            rel = f.relative_to(base).parts
            work, alone = _work_of(rel)
            w = found.setdefault(work, {"standalone": alone, "files": [],
                                        "info": {} if alone else _read_json(base / rel[0] / "work.json")})
            w["files"].append((f, list(rel[1:-1]) if not alone else []))
    added = works_new = 0
    for work in sorted(found, key=_natural):
        spec = found[work]
        info = defaults | spec["info"]
        src_lang = info.get("language") or lib["src_lang"]
        w = db.row("SELECT id FROM series WHERE library_id=? AND library_path=?", lid, work)
        if w:
            sid = w["id"]
        else:
            kind = info.get("kind") or lib["kind"]
            kind = kind if kind in series.KINDS and kind != "single" else "other"
            s = series.create(info.get("title") or work, kind, src_lang, info.get("targets") or lib["targets"])
            sid = s["id"]
            db.run("UPDATE series SET library_id=?, library_path=?, settings=? WHERE id=?", lid, work,
                   json.dumps({"speakers": info.get("speakers") or []} | ({"standalone": True} if spec["standalone"] else {})), sid)
            works_new += 1
        have = {r["source"] for r in db.rows("SELECT source FROM projects WHERE series_id=?", sid)}
        items = []
        for f, middle in spec["files"]:
            stem, tag = _lang_of(f.stem)
            folder_lang = next((c for c in (langs.from_name(m) for m in middle) if c), None)
            groups = [m for m in middle if not langs.from_name(m)]
            items.append((" / ".join(groups), title_of(stem), f, tag or folder_lang or src_lang))
        # groups, then episodes by their numbers; a version in another language after the original
        for group, title, f, lang in sorted(items, key=lambda it: (_natural(it[0]), _natural(it[1]), it[3] != src_lang)):
            ref = device_ref(lib["root_id"], f)
            row = db.row("SELECT id FROM projects WHERE series_id=? AND source=?", sid, ref)
            if row:
                pid = row["id"]
            else:
                pid = series.add_source(sid, title[:120], ref, defer=True)["id"]
                added += 1
                db.run("UPDATE projects SET video=?, audio=?, src_lang=? WHERE id=?", str(f), str(f), lang, pid)
            subs = subtitles_for(f)
            spoken = subs.get("") or subs.get(lang)
            others = {c: p for c, p in subs.items() if c and c != lang}
            try:
                size = f.stat().st_size
            except OSError:
                size = None
            meta = {"library": {"lib": lid, "path": f.relative_to(base).as_posix(), "group": group or None,
                                "lang": lang, "size": size}}
            if spoken:  # the transcript that came with the video (as this PC and as the device see it)
                meta["subtitles"] = str(spoken)
                meta["refs"] = {"subtitles": device_ref(lib["root_id"], spoken)}
            if others:  # subtitles people made in other languages: translations to start from
                meta["subtitles_other"] = {c: str(p) for c, p in others.items()}
            db.set_meta(pid, **meta)
    db.run("UPDATE libraries SET scanned=? WHERE id=?", time.time(), lid)
    return {"works": len(found), "new_works": works_new, "videos": sum(len(v["files"]) for v in found.values()),
            "new_videos": added}


def tree(lid: str) -> list[dict]:
    """The library as it is organised: works → groups → videos (language, subtitles that
    came with it, how far the pipeline got)."""
    out = []
    for w in db.rows("SELECT * FROM series WHERE library_id=? ORDER BY library_path", lid):
        vids = []
        for p in db.rows("SELECT id, name, src_lang, meta, duration FROM projects WHERE series_id=? ORDER BY position", w["id"]):
            m = json.loads(p["meta"] or "{}")
            vids.append({"id": p["id"], "name": p["name"], "lang": p["src_lang"], "group": (m.get("library") or {}).get("group"),
                         "subtitles": bool(m.get("subtitles")), "subtitles_other": sorted(m.get("subtitles_other") or {}),
                         "lines": db.row("SELECT COUNT(*) n FROM sentences WHERE project_id=?", p["id"])["n"],
                         "dubbed": sorted((m.get("exports") or {}).keys()), "duration": p["duration"],
                         "size": (m.get("library") or {}).get("size")})
        st = json.loads(w["settings"] or "{}")
        out.append({"id": w["id"], "name": w["name"], "kind": w["kind"], "standalone": bool(st.get("standalone")),
                    "speakers": st.get("speakers") or [], "videos": vids, "languages": sorted({v["lang"] for v in vids}),
                    "with_subtitles": sum(1 for v in vids if v["subtitles"]),
                    "processed": sum(1 for v in vids if v["lines"]), "dubbed": sum(1 for v in vids if v["dubbed"])})
    return out


def load_subtitles(lid: str, only: list[str] | None = None) -> dict:
    """Lines at once from the subtitles that came with the videos. Speakers are not known
    yet (a run finds them): every line starts as one speaker, the common case for a
    teaching. Videos that already have lines are left alone."""
    from . import captions

    loaded, failed = [], []
    for p in db.rows("SELECT p.id, p.src_lang FROM projects p JOIN series s ON s.id=p.series_id WHERE s.library_id=?", lid):
        if only is not None and p["id"] not in only:
            continue
        m = db.meta(p["id"])
        if not m.get("subtitles") or db.row("SELECT 1 FROM sentences WHERE project_id=?", p["id"]):
            continue
        try:
            doc = captions.load(Path(m["subtitles"]).read_text(encoding="utf-8", errors="replace"), p["src_lang"])
            for seg in doc["segments"]:
                seg["speaker"] = "SPEAKER_00"
                for w in seg["words"]:
                    w["spk"] = "SPEAKER_00"
            end = max([s["end"] for s in doc["segments"]] + [0.0])
            project.ingest_docs(p["id"], doc, {"exclusive": [{"start": 0.0, "end": end, "speaker": "SPEAKER_00"}],
                                               "centroids": {}, "turns": []})
            db.set_meta(p["id"], transcript={"source": "subtitles", "aligned": False, "speakers": "assumed one"})
            loaded.append(p["id"])
        except (OSError, ValueError, KeyError) as e:
            failed.append({"id": p["id"], "error": f"{type(e).__name__}: {e}"})
    return {"loaded": len(loaded), "failed": failed}
