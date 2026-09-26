"""SQLite store. One file for the app; rows are keyed by project.

Only the desktop touches this database. Colab sees job bundles, never the DB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

DATA = Path(os.environ.get("LANGBRIDGE_DATA", Path(__file__).resolve().parents[1] / "data"))
DB_PATH = DATA / "langbridge.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT, src_lang TEXT DEFAULT 'en',
  tgt_lang TEXT DEFAULT 'am', max_speakers INTEGER, clip_start REAL, clip_end REAL,
  duration REAL, video TEXT, audio TEXT, created REAL, meta TEXT DEFAULT '{}'
);
-- A family of sources: a show's episodes, a channel, one speaker's talks, a course, a
-- news programme. New sources inherit its languages and settings (app/series.py).
CREATE TABLE IF NOT EXISTS series (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT DEFAULT 'other', feed_url TEXT,
  src_lang TEXT DEFAULT 'en', targets TEXT DEFAULT '["am"]', settings TEXT DEFAULT '{}', created REAL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT, stage TEXT, created REAL, role TEXT
);
CREATE TABLE IF NOT EXISTS characters (
  project_id TEXT, label TEXT, name TEXT, gender TEXT, important INTEGER DEFAULT 1,
  color INTEGER, bank TEXT DEFAULT '[]', talk_s REAL DEFAULT 0, PRIMARY KEY (project_id, label)
);
CREATE TABLE IF NOT EXISTS sentences (
  project_id TEXT, id INTEGER, speaker TEXT, start REAL, end REAL, text TEXT,
  am TEXT DEFAULT '', am_locked INTEGER DEFAULT 0, chapter_break INTEGER DEFAULT 0,
  reviewed INTEGER DEFAULT 0, PRIMARY KEY (project_id, id)
);
-- One row per line per target language. `provenance` says who wrote it: 'machine'
-- (translation engine) may be overwritten by the engine; 'human' and 'reviewed' never.
CREATE TABLE IF NOT EXISTS translations (
  project_id TEXT, sentence_id INTEGER, lang TEXT, text TEXT DEFAULT '',
  locked INTEGER DEFAULT 0, provenance TEXT DEFAULT 'machine', updated REAL,
  PRIMARY KEY (project_id, sentence_id, lang)
);
-- A chapter runs from `start` to the next chapter's start; a line belongs to the
-- chapter containing its start (app/chapters.py). Index and end are derived.
CREATE TABLE IF NOT EXISTS chapters (
  project_id TEXT, id INTEGER, start REAL, title TEXT DEFAULT '', updated REAL,
  PRIMARY KEY (project_id, id)
);
-- The team library (app/library.py). A clip is a saved span of a source; its spans are
-- revisioned like recomposer's cut_revision, so a journey can pin what it used. Ids are
-- AUTOINCREMENT: never reused. Removing is a soft delete; archiving a collection never
-- touches its clips.
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT, series_id TEXT, source_id TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT DEFAULT 'clip', note TEXT DEFAULT '', created REAL, updated REAL, deleted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS clip_revisions (
  clip_id INTEGER, rev INTEGER, segments TEXT NOT NULL, created REAL, PRIMARY KEY (clip_id, rev)
);
CREATE TABLE IF NOT EXISTS collections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, created REAL, deleted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS collection_items (
  collection_id INTEGER, item_type TEXT, item_id INTEGER, added REAL,
  PRIMARY KEY (collection_id, item_type, item_id)
);
CREATE TABLE IF NOT EXISTS takes (
  project_id TEXT, sentence_id INTEGER, job_id TEXT, take INTEGER, path TEXT, text TEXT,
  sim REAL, cer REAL, dur REAL, dur_s REAL, asr TEXT, chosen INTEGER DEFAULT 0, created REAL,
  lang TEXT, PRIMARY KEY (project_id, sentence_id, job_id, take)
);
"""

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _migrate(c)
        _local.c = c
    return c


def _migrate(c: sqlite3.Connection) -> None:
    pcols = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
    # a project is a source; standalone ones have no series
    for col, decl in (("series_id", "TEXT"), ("position", "REAL"), ("origin_id", "TEXT"), ("published", "TEXT")):
        if col not in pcols:
            c.execute(f"ALTER TABLE projects ADD COLUMN {col} {decl}")
    cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    if "root" not in cols:  # jobs predating job-folder settings all went to Drive
        c.execute("ALTER TABLE jobs ADD COLUMN root TEXT DEFAULT 'colab'")
    scols = {r[1] for r in c.execute("PRAGMA table_info(sentences)")}
    if "words" not in scols:  # word timings, for splitting a line at a word
        c.execute("ALTER TABLE sentences ADD COLUMN words TEXT DEFAULT '[]'")
    if "mode" not in scols:  # 'dub' | 'keep' chosen by the person; NULL follows the suggestion
        c.execute("ALTER TABLE sentences ADD COLUMN mode TEXT")
    if "lang" not in {r[1] for r in c.execute("PRAGMA table_info(takes)")}:
        c.execute("ALTER TABLE takes ADD COLUMN lang TEXT")
    # Takes and translations from before languages were data belong to the project's
    # target language. Both statements only touch rows that lack a language row, so
    # running them again is a no-op.
    c.execute("UPDATE takes SET lang=(SELECT tgt_lang FROM projects p WHERE p.id=takes.project_id)"
              " WHERE lang IS NULL")
    if "am" in scols:
        c.execute("INSERT OR IGNORE INTO translations (project_id,sentence_id,lang,text,locked,provenance,updated)"
                  " SELECT s.project_id, s.id, p.tgt_lang, s.am, s.am_locked,"
                  " CASE WHEN s.am_locked THEN 'human' ELSE 'machine' END, strftime('%s','now')"
                  " FROM sentences s JOIN projects p ON p.id=s.project_id WHERE s.am<>''")
        # The copy is the record now; blanking the old column makes the move one-shot,
        # so a translation cleared later can never be resurrected from it.
        c.execute("UPDATE sentences SET am='', am_locked=0 WHERE am<>'' AND EXISTS (SELECT 1 FROM translations t"
                  " WHERE t.project_id=sentences.project_id AND t.sentence_id=sentences.id)")
    # Chapters used to be a flag on the first line of each chapter. Projects without
    # chapter rows get them from the flags once; the flags are then cleared.
    if "chapter_break" in scols:
        have = {r[0] for r in c.execute("SELECT DISTINCT project_id FROM chapters")}
        for (pid,) in c.execute("SELECT id FROM projects").fetchall():
            if pid in have:
                continue
            first = c.execute("SELECT MIN(start) FROM sentences WHERE project_id=?", (pid,)).fetchone()[0] or 0.0
            # a flag on the opening line meant nothing (the first chapter starts there anyway)
            starts = [r[0] for r in c.execute("SELECT start FROM sentences WHERE project_id=? AND chapter_break=1"
                                              " AND start>? ORDER BY start", (pid, first + 1e-3))]
            c.executemany("INSERT INTO chapters (project_id,id,start,title,updated) VALUES (?,?,?,'',strftime('%s','now'))",
                          [(pid, i, st) for i, st in enumerate([0.0, *starts], 1)])
        c.execute("UPDATE sentences SET chapter_break=0 WHERE chapter_break<>0")
    c.commit()


def rows(sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def row(sql: str, *args) -> dict | None:
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def run(sql: str, *args) -> None:
    c = conn()
    c.execute(sql, args)
    c.commit()


def many(sql: str, seq) -> None:
    c = conn()
    c.executemany(sql, seq)
    c.commit()


def meta(project_id: str) -> dict:
    p = row("SELECT meta FROM projects WHERE id=?", project_id)
    return json.loads(p["meta"]) if p else {}


def set_meta(project_id: str, **kv) -> None:
    m = meta(project_id) | kv
    run("UPDATE projects SET meta=? WHERE id=?", json.dumps(m), project_id)
