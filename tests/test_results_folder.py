"""A results folder: a folder on this PC that a notebook wrote into (a local Jupyter run,
a downloaded Kaggle output). The app reads its runs; nothing is ever queued there."""
import json

from app import runs, series, settings


def test_results_folder_is_kept_and_only_read(tmp_path):
    s = settings.load()
    s["roots"] = s["roots"] + [{"id": "", "name": "Jupyter results", "kind": "folder", "path": str(tmp_path / "lb-out")}]
    saved = settings.save(s)
    r = next(r for r in saved["roots"] if r["name"] == "Jupyter results")
    assert r["kind"] == "folder" and r["id"] == "jupyter-results"

    w = series.create("Talks", "other", "en", ["am"])
    pid = series.add_source(w["id"], "Talk 1", "https://www.youtube.com/watch?v=xwseWCSXD3Y",
                            origin_id="xwseWCSXD3Y", defer=True)["id"]
    made = runs.create_for([pid], r["id"], ["fetch", "transcribe"], name="Talks")
    assert made["job"] is None and made["dir"]  # prepared for a notebook, never queued
    assert not (tmp_path / "lb-out" / "jobs").exists()

    # the notebook ran it: state and results appear in the folder; the app follows the files
    d = tmp_path / "lb-out" / "runs" / made["run"]
    (d / "state.json").write_text(json.dumps({"sources": {"u": {"fetch": "done"}}, "finished": 1}), encoding="utf-8")
    found = runs.scan(r["id"], auto_open=False)
    assert [x["run"] for x in found] == [made["run"]]
    assert found[0]["state"] == "done" and found[0]["done"]["fetch"] == 1
