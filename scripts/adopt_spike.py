"""Turn the bake-off test clip into a normal app project, reusing its finished
Colab analysis jobs instead of re-running them.

    python scripts/adopt_spike.py
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import db, project  # noqa: E402

DATA = ROOT / "spikes" / "voice_bakeoff" / "data"
PID = "camille-interview"

ids = json.loads((DATA / "jobs.json").read_text())
if not db.row("SELECT id FROM projects WHERE id=?", PID):
    d = project.pdir(PID)
    shutil.copy2(DATA / "clip.mp4", d / "clip.mp4")
    shutil.copy2(DATA / "clip.flac", d / "clip.flac")
    db.run("INSERT INTO projects (id,name,source,src_lang,tgt_lang,max_speakers,clip_start,clip_end,"
           "duration,video,audio,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
           PID, "Camille interview", "https://www.youtube.com/watch?v=Op4cDgKtzC4", "en", "am", 2,
           0, 105, 105.0, str(d / "clip.mp4"), str(d / "clip.flac"), time.time())
    db.set_meta(PID, drive_audio="projects/camille/media/clip.flac")
for stage in project.ANALYSIS:
    project.record_job(PID, ids[stage], stage, role="analysis")
if "tts_bakeoff" in ids:
    project.record_job(PID, ids["tts_bakeoff"], "tts_bakeoff", role="bakeoff")
print(project.ingest(PID))
# The bake-off already established who is who.
for label, name, gender in (("SPEAKER_01", "Camille", "female"), ("SPEAKER_00", "Samuel", "male")):
    db.run("UPDATE characters SET name=?, gender=? WHERE project_id=? AND label=?", name, gender, PID, label)
print(project.summary(PID)["counts"])
