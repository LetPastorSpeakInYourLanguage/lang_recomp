import json
import time
from pathlib import Path

from app import feeds, tasks

FIXTURE = Path(__file__).parent / "fixtures" / "channel_flat.json"  # the shape `yt-dlp --flat-playlist -J` gives


def test_channel_tabs_flatten_into_one_list_with_sections():
    got = feeds.parse(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert got["title"] == "Example Teachings"
    assert [(e["id"], e["section"]) for e in got["entries"]] == [
        ("vid00000001", "Videos"), ("vid00000002", "Videos"), ("vid00000003", "Live"),
        ("vid00000004", "Live"), ("sho00000001", "Shorts")]  # the repeat in Live is listed once
    assert [e["live"] for e in got["entries"]] == [False, False, False, True, False]


def test_a_plain_playlist_has_one_section():
    got = feeds.parse({"_type": "playlist", "title": "Lessons", "entries": [{"_type": "url", "id": "a1", "title": "L1"}]})
    assert got["entries"] == [{"id": "a1", "title": "L1", "url": "https://www.youtube.com/watch?v=a1",
                               "duration": None, "section": "Videos", "live": False}]


def test_serial_tasks_run_one_at_a_time_in_order():
    order = []

    def job(n, update):
        time.sleep(0.03)
        order.append(n)

    for n in range(4):
        tasks.start("feeds-test", "import", job, n, serial="feeds-test")
    assert sum(t["state"] == "queued" for t in tasks.list_for("feeds-test")) >= 2
    deadline = time.time() + 3
    while len(order) < 4 and time.time() < deadline:
        time.sleep(0.02)
    assert order == [0, 1, 2, 3]


def test_picked_videos_join_the_series_once(tmp_path, monkeypatch):
    from app import api, db, series
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tasks, "start", lambda *a, **k: "task")  # no downloads
    db._local.c = None
    try:
        s = series.create("Teachings", "speaker", targets=["am"], feed_url="https://www.youtube.com/@x")
        pick = [{"id": "vid00000002", "title": "Sermon: Patience", "url": "https://www.youtube.com/watch?v=vid00000002"},
                {"id": "vid00000001", "title": "Sermon: Hope", "url": "https://www.youtube.com/watch?v=vid00000001"}]
        r = api.add_from_feed(s["id"], api.FeedPick(items=pick, clip_start=0, clip_end=600))
        assert len(r["added"]) == 2 and r["skipped"] == []
        srcs = series.sources(s["id"])
        assert [(p["origin_id"], p["clip_end"]) for p in srcs] == [("vid00000002", 600), ("vid00000001", 600)]
        again = api.add_from_feed(s["id"], api.FeedPick(items=pick[:1]))
        assert again["added"] == [] and again["skipped"][0]["id"] == "vid00000002"
    finally:
        db._local.c = None
