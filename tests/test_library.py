import time

import pytest

from app import chapters, db, library, project


@pytest.fixture()
def pid(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db._local.c = None
    db.run("INSERT INTO projects (id,name,created) VALUES ('ep1','Ep 1',?)", time.time())
    for i, (a, b, t) in enumerate([(0.0, 1.0, "Welcome back."), (1.2, 3.0, "Today we talk hope."),
                                   (3.5, 5.0, "Let us begin."), (6.0, 8.0, "Hope is a choice.")], 1):
        db.run("INSERT INTO sentences (project_id,id,speaker,start,end,text) VALUES ('ep1',?,?,?,?,?)", i, "A", a, b, t)
    project.set_translation("ep1", 4, "am", "ተስፋ ምርጫ ነው።")
    yield "ep1"
    db._local.c = None


def test_a_clip_spans_whole_lines_and_carries_their_text(pid):
    a, b = library.span_of_lines(pid, 3, 2)  # either order
    c = library.create_clip(pid, a, b, "  Opening  ", "opener")
    assert (c["title"], c["kind"], c["recurring"], c["rev"]) == ("Opening", "opener", True, 1)
    assert c["segments"] == [{"source_id": "ep1", "start": 1.2, "end": 5.0}] and c["duration"] == 3.8
    got = library.clips(source_id=pid, lang="am")
    assert [ln["id"] for ln in got[0]["lines"]] == [2, 3]


def test_revisions_keep_the_old_span(pid):
    c = library.create_clip(pid, 6.0, 8.0, "Hope")
    library.revise_clip(c["id"], [{"source_id": pid, "start": 3.5, "end": 8.0}])
    assert library.get_clip(c["id"])["rev"] == 2 and library.get_clip(c["id"])["duration"] == 4.5
    assert library.get_clip(c["id"], rev=1)["segments"][0]["start"] == 6.0  # a journey pinned to rev 1 still works
    lines = library.clips(lang="am")[0]["lines"]
    assert lines[-1]["tr"] == "ተስፋ ምርጫ ነው።"


def test_collections_never_delete_their_clips(pid):
    c = library.create_clip(pid, 6.0, 8.0, "Hope")
    faves, memes = library.create_collection("Favourites"), library.create_collection("Memes")
    library.set_memberships("clip", c["id"], [faves["id"], memes["id"]])
    assert library.get_clip(c["id"])["collections"] == [faves["id"], memes["id"]]
    library.archive_collection(faves["id"])
    assert [x["name"] for x in library.collections()] == ["Memes"]
    assert library.get_clip(c["id"])["deleted"] == 0 and library.clips(collection=memes["id"])[0]["id"] == c["id"]
    library.archive_collection(faves["id"], restore=True)
    assert library.get_collection(faves["id"])["items"] == 1
    library.set_memberships("clip", c["id"], [memes["id"]])  # moved out of Favourites, still in Memes
    assert library.get_collection(faves["id"])["items"] == 0 and library.get_collection(memes["id"])["items"] == 1


def test_removed_clips_come_back_and_ids_are_never_reused(pid):
    a = library.create_clip(pid, 0.0, 1.0, "A")
    library.remove_clip(a["id"])
    assert library.clips() == [] and library.clips(deleted=True)[0]["id"] == a["id"]
    library.remove_clip(a["id"], restore=True)
    db.run("DELETE FROM clips WHERE id=?", a["id"])  # even a hard delete leaves the id used
    assert library.create_clip(pid, 0.0, 1.0, "B")["id"] == a["id"] + 1


def test_a_whole_chapter_can_be_a_clip(pid):
    cid = chapters.toggle(pid, 3)["added"]
    assert library.chapter_span(pid, cid) == (3.5, 8.0)
    with pytest.raises(ValueError):
        library.create_clip(pid, 2.0, 1.0, "backwards")
    with pytest.raises(ValueError):
        library.create_clip(pid, 0.0, 1.0, "x", kind="meme")
