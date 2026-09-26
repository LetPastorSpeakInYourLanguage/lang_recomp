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
    cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    if "root" not in cols:  # jobs predating job-folder settings all went to Drive
        c.execute("ALTER TABLE jobs ADD COLUMN root TEXT DEFAULT 'colab'")
    scols = {r[1] for r in c.execute("PRAGMA table_info(sentences)")}
    if "words" not in scols:  # word timings, for splitting a line at a word
        c.execute("ALTER TABLE sentences ADD COLUMN words TEXT DEFAULT '[]'")
    if "mode" not in scols:  # 'dub' | 'keep' chosen by the person; NULL follows the suggestion
        c.execute("ALTER TABLE sentences ADD COLUMN mode TEXT")
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
