# STATE — where the build is right now

The working memory of this project. Read this first when picking the work up.
**Every open task, across all plans, with priorities: [BACKLOG.md](BACKLOG.md)** — keep it updated in the same commit as the work.
Plan: [PLAN.md](PLAN.md). Decisions and why: [DECISIONS.md](DECISIONS.md).
Hard-won lessons: [LESSONS.md](LESSONS.md).

**Last updated:** 2026-09-30 — **new plan approved: [WORKSPACE_PLAN.md](WORKSPACE_PLAN.md)** (branch `feat/workspace`); first step: notebooks under `notebooks/` that run anywhere.

---

## Where we are

| | |
|---|---|
| **Repo** | `D:\py_self\lang_bridge_test` → GitHub `LetPastorSpeakInYourLanguage/lang_recomp` (public, MIT) |
| **`main`** | A1–A5 + bulk Colab runs merged locally; worker published to Drive; `origin/main` is still `d6d5e7c` — **not pushed** |
| **Current branch** | `feat/keep-words` (A6) |
| **Plan phase** | A1–A5 **done**; next A6 (per-language keep-words), A7 (unknown-language path), then Phase B |
| **Tests** | 82 pass (`python -m pytest -q tests`); web typecheck + build pass |

### Next steps, in order

1. Real run done: "6 Minute English" (3 episodes) — Neil linked across 3, Georgie across 2
   (proposals at 0.93/0.77/0.72, false one at 0.45 → threshold 0.55); banks mix episodes;
   exported (22 MB, Opus stems) and imported into the sandbox as team B with Oromo added.
   Not done: machine translation into Oromo in the sandbox (owner stopped that call).
2. Recurring parts still need a real series with an identical intro (6 Minute English's
   YouTube uploads have varying stings: no shared audio ≥ 3 s, correctly nothing proposed).
0. **Pivot (2026-09-26): the Colab worker is a research notebook, not a job picker.**
   `notebooks/lang_bridge.ipynb` (was `colab/`) + `worker/lb_worker/research.py` (`run_folder`, `run_manifest`)
   clone the code from GitHub, take a folder/links + `HF_TOKEN` in the settings, and write
   `.lbwork` results the app opens. Drive is mounted by the person. The app only *prepares*
   runs for Colab folders. `scripts/sync_worker.py` is gone. Guide: `notebooks/README.md`.
3. ~~**Whole-channel Colab run in progress**~~ (superseded by the pivot above; jobs cancelled) (owner request): all 458 other "6 Minute English"
   videos (~48 h of audio) queued as 23 `bulk` batches of 20 on the Colab job folder; the
   owner runs `lb_worker.ipynb` (Run all) as often as needed — batches resume. Then press
   "Load N finished" on the series page. **Owner rule: nothing runs or downloads on this
   PC** — active job folder is Colab again, the local worker was stopped.
4. **In flight on `feat/colab-run`** (not merged): runs (`app/runs.py`, worker stage
   `pipeline` in `worker/lb_worker/stages/run.py`), library folders (`app/libraries.py`,
   standard in `docs/LIBRARY_FOLDERS.md`), captions/subtitles (`app/captions.py`), batched
   Whisper across videos (`worker/lb_worker/batch_asr.py`), packages with media `ref`,
   brief project lists. Still to do on it: App must fetch the open project's full summary
   (lists are brief now); Libraries screen + Runs panel; notebook wording + publish `app/`
   to Drive; first real Colab run (6 Minute English + a PCDL sample).
5. **Then the team hub** — design approved in `docs/TEAM.md` (media identity by content,
   devices, hub/member modes, locate/copy, device-addressed runs, edit safety).
6. Then A6, A7 — see PLAN.md.

### Working method the owner asked for

- **Work in branches, commit step by step, merge when a phase is done.**
- **Check every commit on its own**: `bash scripts/check_commit.sh` (add `web` when the
  frontend changed) stashes uncommitted work, runs compile + pytest (+ tsc + vite build),
  restores. A commit that fails is fixed before the next one.
- **"Main builds" pass** before/after merging, one at a time:
  1. `python -m pytest -q tests`
  2. `cd web && npx tsc --noEmit && npm run build`
  3. worker imports: `python -c "import sys; sys.path.insert(0,'worker'); import lb_worker.stages"`
  4. start the app (`.claude/launch.json` → `api` + `web`, or `python -m app --serve`) and
     check screens in the browser pane (Translate, Voice, Mix with real data)
  5. `python scripts/build_notebook.py` when the notebook cells changed (then commit
     `notebooks/*.ipynb`); notebooks get new worker code from GitHub on its next run
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## What exists (v1, on main)

Desktop app (FastAPI `app/` + React/Vite/Tailwind `web/`, SQLite `data/langbridge.db`), GPU
work through **job folders** watched by workers (`worker/lb_worker/`):

| Step | Where | Status |
|---|---|---|
| Import (yt-dlp / file, clip range) | local | done |
| Separate (audio-separator BS-RoFormer, overlap 2) | Colab / Arc | done |
| ASR (faster-whisper, Silero VAD, ≤30 s chunks) | Colab (large-v3) / PC (large-v3-turbo) | done |
| Align (any HF CTC model per language, vendored whisperX DP) | Arc / Colab | done |
| Diarize (pyannote community-1, waveform in memory) | CPU / Colab | done |
| Characters, Transcript (merge/split, chapters, keys), Translate | app | done |
| Voice (OmniVoice 16 steps 1.4×, 2 takes, scored) | Arc / Colab | done |
| Mix (fit, rubberband, ducking, keep-original lines) + MP4 export | local | done |
| Folders/workers settings, aligner search/check, keep-words list | app | done |

Test clip project: `camille-interview` (105 s, 28 lines, 2 speakers, all reviewed, 24 dubbed
+ 4 kept original). Export: `data/projects/camille-interview/export/`.

## Bulk Colab runs (app/bulk.py, worker stage `bulk`)

- A series' videos are added without importing (`defer`), queued in batches; the worker
  downloads each video (≤720p, clip range) into `library/<work uid>/<source uid>/video.mp4`
  on Drive, then Whisper large-v3 + aligner + pyannote (loaded once per batch); per-video
  results in the job's `out/<source uid>/` with `done.json`/`error.json`. No separation.
- The app loads finished videos (`ingest_docs`), pointing `video`/`audio` at the G: file;
  fingerprints computed on the worker are copied (tiny). `project.stem()` finds stems on
  Drive (`meta.stems`) or locally; `put_media` references files already under the root.
- Series page: channel picker "fetch on Colab" + "all"; Colab batch panel (send, load
  finished, retry failed). Sidebar shows 8 videos per series + "N more".
- Tests always run against throwaway settings/job folders (`tests/conftest.py`) — one test
  once queued a job into the real Drive before this existed (removed at once).

## What A5 added (cast, banks, packages)

- `app/cast.py` (characters, appearances, matching, merge/link/detach, move between works),
  `app/banks.py` (voice banks), `app/package.py` (export/import), `docs/PACKAGE.md`.
- Migration: standalone projects → single works; uids everywhere; old `characters` rows →
  cast + confirmed appearances (camille: Samuel, Camille — unchanged downstream).
- Web: Cast screen (`#/cast/<work>`), Share screen (`#/share/<work>`), Characters screen
  proposals ("Sounds like Neil · 0.84 — Yes / Not them"), Home "Open a shared work",
  Overview "Try again" for failed imports, Translate reference language.
- Fixes found by the real run: downloads retry (ffmpeg reconnect, 3 attempts); the worker's
  cached separator wrote every later job's stems into the first job's folder.
- Real library now has series "6 Minute English" (course; 3 episodes clipped 0:00–2:30).
  Active job folder switched to This PC; local worker started from the session.

## What A4 added (series, library, recurring parts)

- **Series** (`app/series.py`): kinds show/channel/speaker/course/news/other; new sources take
  `src_lang`, targets and `settings.max_speakers`; attach/detach existing projects; reorder;
  remove (videos stay). Projects gained `series_id, position, origin_id, published`.
- **Channel/playlist** (`app/feeds.py`): flat listing, tabs → sections, "already added" by
  `origin_id`; picked videos added oldest first; `tasks.start(..., serial="import")` makes
  imports one FIFO queue.
- **Library** (`app/library.py`): `clips` + `clip_revisions` (segments `[{source_id,start,end}]`),
  `collections` + `collection_items`; AUTOINCREMENT ids; soft delete/archive.
- **Recurring parts** (`app/fingerprint.py`, `app/recurring.py`): fingerprints cached as
  `projects/<id>/fingerprint.npy` (computed at import); `search` → proposed
  `clip_occurrences`; people confirm/reject; `discover(series)` → candidates (not stored).
- **Reuse in dubbing**: `recurring.link` marks lines fully inside a confirmed occurrence
  (`linked`, origin translation, provenance `linked`); translate/voice skip them;
  `mix.render` uses `recurring.origin_takes`; fit report says "reused from …".
- **Web**: Library home (series cards, single video with language fields, standalone list
  with "Move to…"), Series page (settings, from-channel picker, repeating parts, sources),
  Clips & collections, Transcript Shift+J/K + S, linked tags in Transcript/Translate/Mix,
  sidebar grouped by series.
- **Sandbox**: `python scripts/make_sandbox.py` then launch config `sandbox`
  (`python -m app --serve --port 8766 --data data/sandbox`; serves `web/dist`, so
  `npm run build` first).

## What A3 added (chapters)

- `chapters(project_id, id, start, title, updated)` in `app/chapters.py`: `ensure`, `assign`
  (sets `chapter` + `chapter_head` on lines), `listing` (index, end, line count), `toggle`
  (the C key), `rename`, `normalize` (after merge/split/ingest), `group` (translation
  context). Ids come from `meta.chapter_seq` and are never reused.
- API: `GET /api/projects/{pid}/chapters`, `POST …/chapters/toggle {at}`,
  `PATCH …/chapters/{cid} {title}`; translate takes a chapter **id**. `chapter_break` is gone
  from the API; the column stays in SQLite, cleared by the one-shot migration.
- Web: Transcript headers show "Chapter N" + editable title; Translate groups by chapter id.
- Transcript layout (owner request): video + keys across the top (band locked to the video's
  height, keys scroll inside), lines full width below.
- Real DB migrated (camille: one chapter). Backup `data/backups/langbridge-20260926-111244.db`.

## What A1/A2 added (languages)

- `translations(project_id, sentence_id, lang, text, locked, provenance, updated)`;
  `provenance ∈ machine|human|reviewed`; machine never overwrites a person unless `force`.
- Projects: primary `tgt_lang` + extra targets in `meta.targets`; `/api/languages`,
  `POST /api/projects/{pid}/languages`.
- `lang` on sentences/translate/voice/mix/export APIs (default primary). Takes have `lang`.
  Rates per language in `meta.rates`. Mix in `mix/<lang>/`, export `<pid>.<lang>.mp4`.
- Migration (in `app/db.py::_migrate`) moved `sentences.am` → translations **once**, blanked
  the old column. Real DB migrated OK; backup at `data/backups/langbridge-20260926-104442.db`.
- `app/langs.py` (names, ISO 639-3, script), `app/translate/length.py` (syllables per script).
- Web: `web/src/shell/LangBar.tsx` on Translate/Voice/Mix.

---

## Environment (verified)

| Thing | Value |
|---|---|
| OS / Python / Node | Windows 11, Python 3.13.2 (global), Node 24.18, ffmpeg 8.1.2 full (has rubberband) |
| CPU / GPU / NPU | Core Ultra 7 165H 16C, **Intel Arc iGPU** (PyTorch XPU works, ~2 TFLOPS fp16, 7.8 GB shared), Intel AI Boost NPU (unused; OpenVINO only) |
| RAM / link | 15.4 GB; internet ~0.8–1 MB/s (downloads must resume) |
| Google Drive | Drive for Desktop at **`G:\My Drive`**; job folder `G:\My Drive\LangBridge` (Colab: `/content/drive/MyDrive/LangBridge`), model cache `…/LangBridge/cache` |
| Local worker | folder **`D:\LangBridgeLocal`**: `.venv` (CPU torch), **`.venv-xpu`** (torch 2.14+xpu, used when present), `cache/`, `jobs/`; start with `Local-Worker.cmd` |
| HF login | done on this PC (`hf auth login`); Colab secret `HF_TOKEN` set by owner |
| Dev servers | `.claude/launch.json`: `api` (8765), `web` (Vite 5173 on 127.0.0.1, proxies /api) |
| Owner's other projects | `D:\py_self\recomposer_v2` (journeys; source for Phase D), `D:\recomposer` (read-only donor), `D:\py_yaddessa\lab_resource_v2` (UI design reference) |

## Measured numbers (camille clip, 105 s)

- Arc: separation 3.6 min (overlap 2; CPU 36 min), align 53 s, voicing 12–19 s/line.
- CPU: ASR turbo 50 s, diarization 60 s. Colab T4: separation ~3 min, ASR+diarize ~2 min.
- Voice quality (chosen takes): likeness median 0.90 (real speaker 0.93–0.97), Amharic CER 11.5 %,
  fit 1.06×; OmniVoice Amharic ~4 fidel/s at 1.0×, 5.15 syl/s at 1.4×.
- Bake-off (Colab): OmniVoice bank 0.89 sim / 10.5 % CER; Amharic finetune 0.88 / 9.4 %;
  own-sentence + fixed duration 0.85 / 22 %; edge-tts floor 0.66 / 12.4 %.

## Open items / known gaps

- Remove-a-target-language UI/API does not exist yet (adding does).
- Clips play only their first span; multi-span clips (revisions allow them) need UI.
- Recurring-part timing constants are calibrated on synthetic audio only.
- Discovery is synchronous (fine for a handful of hour-long sources; first run
  fingerprints any source not yet printed).
- Human voices, series, cross-source characters, community server, journeys: not started (PLAN.md).
- Colab passive notebook + Seed-VC fixes published but Seed-VC conversion never completed a
  full run on Colab (session limits); local Arc path is the proven one.
- Translation engine is Google's unofficial endpoint (clients5) — no LLM engine yet.
