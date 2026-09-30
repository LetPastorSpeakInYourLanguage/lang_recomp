# Plan: the notebook is the worker, the folder is the contract, the app refines (approved 2026-09-30)

**Order set by the owner (2026-09-30, after approval):** the notebooks first. They are
re-created under `notebooks/` to run anywhere on today's engine: Kaggle with both T4s, Colab with
one T4, local Jupyter. `HF_TOKEN` and `BUCKET` are typed in the settings cell, not taken from
platform secrets. The app stays as it is, except that it can open plain folders of results.
That is Phase 3 brought forward. The rest follows in order.

## Context

Today the notebook works but depends on others. It guesses Colab vs Kaggle from one
environment variable, and it has no local mode. It takes secrets from platform secret
stores. It writes per-run `.lbwork` files. The app queues jobs on "devices" and imports run
results. An edit made in the app only reaches the notebook if the app prepares a new run.
Voicing skips any line that already has a take file (`{line}_t{k}.wav`), so a corrected
translation is never re-voiced.

The owner wants (2026-09-30):

1. **The notebook is the authority and the only worker**: one self-contained deliverable
   that dubs a folder end to end with no app. It runs anywhere: Colab, Kaggle, local
   Jupyter, a server. Everything is set in its settings: secrets, **DEVICE** (CPU / 1 × T4 /
   2 × T4) and **STORAGE** (a folder, or a Hugging Face bucket that it downloads from and
   pushes to).
2. **The app is separate.** It adjusts what the notebook does (choosing media, tasks,
   corrections) and only ever works with folders. A team member connects a folder on their
   PC, or a bucket synced into a folder. The media come from the folder's config, which the
   app reads, or creates for a new project.
3. **Corrections made in the app are picked up by the next notebook run**, which redoes
   only what they made stale.
4. **Central metadata** (one Supabase) holds every source, the PC and folder where it lives,
   and who works on which media. Everyone sees the metadata; a video is only previewed when
   it is in the member's connected folder. Generated voices live in the local folders, with
   the team's HF bucket as backup and for sharing within the team.
5. **LLM step (Gemma)**: chapters made by the model as translation context, and a cyclic
   loop that tests and produces good translation options, in the source (rephrasing) or the
   target, for meaning transfer.

Owner decisions in this round:
- Retire the app's job queue (Local-Worker.cmd, Drive job folders, jobs started from
  screens).
- The folder config wins. A different source language is an **error**. Targets and links
  are a **union**: the notebook does both the folder's languages and its own, and warns.
- On Run all: **tasks first, then bring everything up to date.**
- **The full SCALE_DESIGN rewrite**: a pipeline independent of the app, with per-video
  `auto/` and `manual/` files and input hashes.

This plan replaces Phase B of `docs/SCALE_PLAN.md`. E1 and E2 are already certified. E3
(translation) becomes the gate inside Phase 5. E4–E6 are covered by acceptance checks.

## Rules that hold everywhere

- **The workspace folder is the contract.** The notebook and the app never call each other.
- **The notebook never talks to Supabase.** It only needs an `HF_TOKEN`.
- **Single writer per file** (table below). Sync is two-way with `sync_bucket(delete=False)`,
  so each side pushes only the paths it owns.
- **Effective data = manual over auto.** Every derived item stores the `inputs_hash` of
  what it was made from, so staleness, "skip what is done" and re-runs after edits all come
  from comparing hashes.
- **Identity by content**: media uid = uuid5 of the link id (`Youtube:<id>`) or of the quick
  hash (size + first/last 4 MB, certified in E2). The app and the notebook compute the same
  uid without talking to each other, and a moved or renamed file keeps its uid.
- Owner's method: branch `feat/workspace` from `main`. Every commit is checked with
  `bash scripts/check_commit.sh [web]`. STATE, BACKLOG and DECISIONS are updated in the same
  commits. Merge after acceptance.

## The workspace (format v1)

```
<workspace>/
  lang-bridge.json              config (the "project"): uid, team, name, language, targets, links,
                                asr_models, aligners, keep_words, glossary, translation, voice, mix,
                                bucket, exclude globs.                              [app; notebook only creates it if absent]
  <videos in any nesting>       untouched; docs/LIBRARY_FOLDERS.md rules (work.json, NN - title, .srt)
  dubs/<same nesting>/<name>.<lang>.mp4 + .srt   finished dubs, usable with no app       [notebook]
  .lb/
    status.json                 per media × stage: done/stale/failed/held + counts (for the board)  [notebook]
    works/<work uid>/work.json  title, kind, order, declared speakers                          [notebook]
    works/<work uid>/manual.json people's work-level edits (title, order, kind)                [app]
    cast/<work uid>/auto.json   speakers → character proposals, voice-bank refs, bank/ audio   [notebook]
    cast/<work uid>/manual.json confirmed/linked/named characters, chosen references           [app]
    media/<media uid>/
      media.json                identity: link id, quick hash, duration, fingerprint, paths    [notebook]
      source/                   link downloads (≤720p) or uploaded compact audio (Opus 160)    [notebook / app upload]
      auto/  stage.json, transcript.json, speakers.json, chapters.json,
             tr.<lang>.json (options, checks, rounds), voice.<lang>.json, mix.<lang>.json,
             stems/, takes/<lang>/<line>_<hash8>_t<k>.wav, mix/<lang>.m4a                      [notebook]
      manual/ media.json (skip, hold, until, priority, title), transcript.json (full snapshot
             when touched, with base hash), chapters.json, tr.<lang>.json (chosen/typed/locked),
             voice.<lang>.json (chosen take), mix.<lang>.json (per-line gain/offset)           [app]
    tasks/<id>.json             {media: [uids]|"all", until, redo: [stages], langs, options, by, note, cancelled} [app]
    tasks/<id>.state.json       claimed by (session, runtime, device), lease, progress, done/error    [notebook]
    runs/<run>/log.txt, summary.json, report.json                                             [notebook]
    cache/                      models (never synced)
```

**Staleness chain** (per line, hashed in `lb_core/hashing.py`):
- **Transcript** → **chapters**: auto chapters are redone only if there are no manual
  chapters and the transcript hash changed.
- **Translation**: the effective source text, speaker, slot length, chapter summary,
  glossary version and engine config. A manual choice is kept even when stale; the app
  shows it as "source changed after your choice".
- **Take**: the effective translation, the character's reference hash and the engine
  settings. The hash is in the file name, so old takes are never reused.
- **Mix**: the chosen takes, timings, dub/keep modes and mix tweaks.

**Config conflicts** (`lb_core/workspace.py`):
- A different LANGUAGE is an error, with the fix in the message.
- TARGETS and links are a union, with a warning. Languages added only by a notebook appear
  in the auto data, and the app offers to adopt them.
- ASR/aligner maps: the folder's entries win; the notebook adds missing languages and warns
  when an entry differs.

## Phase 0: record the decisions (docs only)

- DECISIONS.md: new rows 35+.
  - The notebook is the only worker and runs anywhere.
  - Folder or bucket storage.
  - The app works only with folders.
  - Job queue retired.
  - Config conflict rules.
  - Tasks, then everything.
  - Content-derived uids.
  - Voices stored locally with the bucket as backup.
  - The full workspace rewrite.
- SCALE_DESIGN.md: §2 updated to the layout above, §6 to "notebook anywhere", §8 to reflect
  retirements.
- SCALE_PLAN.md: Phase B marked as superseded by this plan.
- BACKLOG.md: every task of this plan by priority, and old tasks this plan replaces marked
  as superseded (RUN/BULK/TEAM hub, local worker).
- STATE.md: new "where we are".

## Phase 1: `lb_core`, shared logic with no app or database

Move the pure logic out of `app/` into a new top-level package `lb_core/`, importable from
the notebook with `CODE` on the path. `app/` re-imports it. **Behaviour does not change,
and all 82+ tests stay green.**

- `lb_core/lines.py`: `regroup`, `keep_reviewed`, `carry_over` (from `app/project.py`).
- `lb_core/translate/`: `google_batch`, `length`, `ethiopic`, `sentences` (from
  `app/translate/`).
- `lb_core/langs.py`, `interjections.py`, `captions.py` (parsing), `chapters.py` (span
  rules).
- `lb_core/fingerprint.py` (from `app/fingerprint.py`).
- `lb_core/mixing.py`: render/fit/rubberband (from `app/mix.py`).
- `lb_core/banks.py`: cutting and choosing reference audio (from `app/banks.py`).
- `lb_core/cast_match.py`: embedding matching and the 0.55 threshold (from `app/cast.py`).

Only the database glue stays in `app/`.

## Phase 2: the workspace protocol (`lb_core/workspace/`)

- `schema.py`: versioned JSON formats with validation.
- `layout.py`: paths.
- `io.py`: atomic write-then-rename; readers treat unreadable or half-synced JSON as "not
  there yet".
- `identity.py`: link id, quick hash, uid, fingerprint matching with offset.
- `scan.py`: any nesting, LIBRARY_FOLDERS rules, `work.json`, `.srt` sidecars, config links.
- `config.py`: load, create, the conflict rules above.
- `effective.py`: manual over auto per line. Transcript snapshots are rebased onto a newer
  auto transcript with `keep_reviewed`/`carry_over`.
- `hashing.py` and `stale.py`.
- `tasks.py`: claims with leases, cancel, progress.
- `ownership.py`: the owner of every path, and the include patterns each side pushes.

Tests (new):
- A round trip through the format.
- Manual over auto, including merged/split lines.
- **Editing a speaker makes only that speaker's lines stale.** Editing a translation makes
  only that line's take and its video's mix stale.
- Identical uids from app and notebook; a renamed file keeps its uid.
- Config conflicts: language error, target union.
- Task lease expiry.
- Notebook-owned and app-owned path sets never overlap.

## Phase 3: a notebook that runs anywhere (runtime, no models yet)

`worker/lb_worker/env.py`:
- **Runtime**: Kaggle (`KAGGLE_KERNEL_RUN_TYPE`), Colab (`google.colab` importable),
  otherwise local.
- **WORK_DIR**: `/kaggle/working`, `/content`, or `~/lang-bridge` locally, unless set.
- **DEVICE** is applied before torch is imported:
  - `cpu`: `CUDA_VISIBLE_DEVICES=""`.
  - `1 GPU`: `CUDA_VISIBLE_DEVICES=0`.
  - `2 GPUs`: all GPUs.
  - `auto`: CUDA, then Intel XPU, then CPU.
  - If torch is already loaded, the notebook tells the person to restart.
- **CPU profile**: Whisper large-v3-turbo int8, LLM steps off (Google plus fallback
  chapters), and a warning with estimated times for separation and voicing.
- **Code**: the checkout the notebook sits in (local development), otherwise clone/pull into
  WORK_DIR from `CODE_BRANCH`.
- **Dependencies**: Python version check, torch (CPU, CUDA or XPU index; `setup_xpu` from
  `scripts/local_worker.py`), ffmpeg check with a plain-words fix and the existing fallbacks.
- **Colab**: Drive is mounted automatically when WORKSPACE is under `/content/drive`.

`worker/lb_worker/store.py`:
- **folder**: work in place. Optional `BACKUP_BUCKET` pushes voicings.
- **bucket**: pull the workspace, including sources, into WORK_DIR, and push the
  notebook-owned paths after every stage and at the end. This reuses `research.Bucket`
  (background push, collapsing).
- **Kaggle**: a folder under read-only `/kaggle/input` is refused with advice to use a
  bucket.

`worker/lb_worker/secrets.py`: settings value, then Kaggle/Colab secret, then environment.
Secrets are masked in every print and log, and never written to the workspace.

`scripts/build_notebook.py` → `colab/lang_bridge.ipynb`. One notebook for every runtime;
Colab form syntax is plain Python elsewhere.

- **① Settings**:
  - Where: `WORKSPACE`, `STORAGE` [folder, bucket].
  - What: `LANGUAGE`, `TARGETS`, `YOUTUBE`.
  - Machine: `DEVICE` [auto, cpu, 1 GPU, 2 GPUs], `WORK_DIR`.
  - Secrets: `HF_TOKEN`, `BACKUP_BUCKET`, `YT_COOKIES`.
  - Do: `MODE` [tasks then everything, tasks only, everything], `UNTIL`, `LIMIT`,
    `DUB_LIMIT`.
  - Advanced: `CODE_BRANCH`, `ASR_MODELS`, `ALIGNERS`.
- **② Set up**: prints a machine card: runtime, GPUs and memory, RAM, disk, storage mode,
  config, and any conflict warnings.
- **③ Plan**: prints tasks, then media × stages to do, stale counts and held media.
- **④ Run**.
- **⑤ Release the GPU**.

Retired: `research.py`, `colab/e2e_test.ipynb` (folded in); the bench notebook is kept.

Tests: runtime detection (patched env and modules), device environment, secrets order and
masking, store include sets, every notebook code cell compiles, the committed notebook has
no token in it.

**Demo**: run it on this PC with `DEVICE=cpu` against a folder. It scans, writes
`media.json`/`status.json` and prints the plan. No models are downloaded.

## Phase 4: the pipeline on the workspace (`worker/lb_worker/pipeline/`)

`plan.py` does the tasks first (leases), then every media not skipped or held, up to its
`until`, redoing only missing or stale items. Each stage runs over all ready media with its
model loaded once. CPU work (downloads, decoding, mixing, pushing) runs on threads. On 2
GPUs the work is split, reusing `_split`/`_side_by_side` and the GPU-1 separation from
`stages/run.py`.

| Stage | Reads (effective) | Writes | Reuses |
|---|---|---|---|
| fetch | config links, `YOUTUBE` | `source/`, `media.json` | yt-dlp code in `stages/run.py`, `feeds.listing` |
| transcribe | source, `.srt` | `transcript.json`, `speakers.json` | `batch_asr.py`, `asr.py` (per-language models), `align_core.py`, pyannote in `stages/analysis.py` |
| cast | transcripts, `work.json` speakers, `cast/manual` | `cast/auto.json`, banks | `lb_core/cast_match.py`, `lb_core/banks.py` |
| chapters | transcript | `chapters.json` | Phase 5 (the fallback ships here) |
| translate | lines, chapters, glossary | `tr.<lang>.json` | Google batch first; the loop arrives in Phase 5 |
| voice | chosen translations, refs | stems, takes (hash-named), `voice.<lang>.json` | `load_separator` fp16, `tts/omnivoice_gen.py`, `tts/score.py` |
| mix | chosen takes, tweaks | `mix/<lang>.m4a`, `dubs/…mp4 + .srt` | `lb_core/mixing.py` |

`stage.json` and `status.json` are written after every item. A stopped run resumes from the
hashes. Summary and log go in `runs/<run>/`.

Retired once this is ported: `stages/run.py`, `bulk.py`, `prefetch.py`, `ping.py`,
`bakeoff.py`, `voice.py`, `align.py`, `loop.py`, `protocol.py`, `registry.py`.

Tests use stubbed models, following the `tests/test_run.py` pattern:
- A nested folder plus an `.srt` goes end to end.
- A re-run after a manual edit redoes only the affected lines, takes and mixes.
- Held and until are respected.
- A task beats "everything".
- A 2-GPU split with stubs.

**Demo (owner)**: a Colab 1 × T4 run on a Drive folder, and a Kaggle 2 × T4 run on a
bucket, with no app. Dubs appear in `dubs/`.

## Phase 5: Gemma chapters and the translation loop

1. **E3 gate** (as in SCALE_PLAN): `colab/bench_translation.ipynb` on 150–200 lines (6ME
   and a sermon).
   - Systems: Google, Google + rephrase, TranslateGemma 4B/12B, NLLB-3.3B, and Gemma 4 E4B
     (T4) / 26B MoE (2 × T4).
   - It writes a blind rating page for 2–3 Amharic speakers.
   - Decides: models, rounds, and whether QE, back-translation and LLM-judge checks are
     trusted or only shown as hints (Spearman ≥ 0.6).
   - Results go in `docs/CERTIFICATION.md`.
2. `worker/lb_worker/llm.py`: one interface (`generate(prompt, schema)`) over
   transformers/llama.cpp, 4-bit on a T4, loaded once per phase. The model comes from
   config.
3. **Chapters** (`pipeline/chapters.py`): per media, the LLM splits at line boundaries on
   topic changes and writes a title, a two-line summary and key terms. Chapters are kept to
   a few minutes. Key terms seed the work glossary. Fallback: long pauses plus a LaBSE
   topic shift.
4. **Loop** (`pipeline/translate_loop.py`), per chapter and language:
   - Rephrase hard source lines. These become **source options**, shown to people.
   - Candidates: Google on the original, Google on the rephrased text, and the LLM with the
     chapter context and the time budget.
   - Checks: back-translation + LaBSE, AfriCOMET-QE where the language is covered, length
     fit (`lb_core/translate/length.py`), and the LLM judge's concrete findings.
   - At most 2 revise rounds with those findings.
   - At most 4 distinct **target options**, with scores, flags and the reason for each.
   - The recommended option is dubbed until a person chooses.

Tests with a stubbed LLM:
- The loop stops.
- Options are ranked and distinct.
- A manual choice is never overwritten.
- The fallback chapters always exist.

## Phase 6: the app on workspaces (files only; Supabase in Phase 7)

- **Settings**: "Workspaces" replace devices and job folders.
  - Add a folder on this PC (local disk or Drive for Desktop), or connect a bucket (name +
    local folder to sync into).
  - The app makes this PC's **device id and name** on first start.
- **New workspace**: from a folder (videos already there) or from links. Writes
  `lang-bridge.json`, then pushes it for a bucket.
- **Ingest** (`app/ingest.py`): workspace files into SQLite, which is now a **cache**.
  - Incremental by file size and mtime.
  - The existing screens keep working on the cache.
  - Migrations add the media uid and hash columns.
- **Write-through** (`app/writeback.py`): every edit is written to the matching `manual/`
  file, debounced and atomic. Covered: lines (merge/split/text/speaker/timing/keep),
  chapters, cast decisions, translation choice or typed text, take choice, mix tweaks,
  skip/hold/until.
- **Board**: works → media × stages with states (done/stale/failed/held/missing). "Not on
  this PC" is marked. Tick media → "do these / redo X / until Y" writes a task, and task
  progress shows from `.state.json`.
- **Translate screen**: pick from the source and target options, with scores and reasons;
  a stale manual choice is flagged.
- **Preview gate**: the video plays only when the media resolves in this PC's folder.
  Otherwise it shows where it exists, and "get voicings from the team bucket" pulls only
  that media's takes and mixes.
- **Bucket**: Sync pulls; a push of app-owned paths runs after edits and tasks. "Upload
  compact audio" (Opus 160) makes local-only videos runnable on Kaggle.
- **Retired**: `app/runs.py`, `app/bulk.py`, `app/jobs/drive_queue.py`, the job parts of
  `project.py`/`voice.py`, the Run panel's device runs, `Local-Worker.cmd`,
  `scripts/local_worker.py` (its XPU setup moves to `env.py`). `.lbwork` stays for sharing
  by hand (`package.py`).
- Web: `screens/Workspaces.tsx` (Home), `screens/Board.tsx`, the Settings workspaces
  section, the options chooser in `Translate.tsx`, and player gating in `player.ts`.

Tests: ingest round trip, write-through makes the right items stale, task create/cancel,
the preview gate, bucket push includes only app-owned paths.

## Phase 7: central metadata (one Supabase)

`supabase/migrations/*.sql`: teams, members, **devices**, workspaces, **workspace_mounts**
(workspace × device → path, kind, last seen), media, **media_copies** (media × device → path
present; this drives the preview gate for others), media_links (same content, with an
offset), works, lines, chapters, characters/appearances, translations (options jsonb,
chosen, locked, rev), voice_choices, tasks mirror, status summary, events.

- RLS: every team reads everything; a team writes its own works and languages; a language
  team may add its translations to another team's work.
- `app/central/`:
  - Sign-in with the publishable key.
  - Push and pull by revision; a stale write gets a 409 and is shown for merging.
  - Mounts and copies are registered on every scan.
  - Cross-team reuse: a media matching another team's by identity pulls its transcript,
    speakers and cast into `manual/`, so the notebook skips to the missing languages.
  - A weekly export to the bucket.
- Bulky data (word timings, check details) stays in files and the bucket, referenced by
  path.

Tests: against a local fake by default; a live marker runs against the owner's free
project (E5: team A cannot write team B's work; bytes per video measured).

## Phase 8: move over, clean up, acceptance, merge

- `scripts/migrate_to_workspace.py`: exports today's works (camille, 6 Minute English) into
  workspaces, with reviewed lines, locked translations and confirmed cast going to
  `manual/`. The database is backed up first to `data/backups/`.
- README, `colab/README.md` (Colab / Kaggle / local in plain numbered clicks), STATE and
  BACKLOG are updated.

## Verification

- **Every commit**: `bash scripts/check_commit.sh` (add `web` when the UI changes). This
  covers compile, `python -m pytest -q tests` with stubbed models, and tsc + vite build.
- **Every phase's demo**:
  - P3 on this PC (CPU, scan and plan only).
  - P4/P5 run by the owner on Colab 1 × T4 and Kaggle 2 × T4, with the printed summary
    pasted back.
  - P6 checked in the browser pane (board, edit → `manual/` file written, task written,
    preview gate).
- **Acceptance (owner), then merge to `main`**:
  1. A nested preaching folder of about 10 videos on Drive → the Colab notebook with **no
     app** → dubs in `dubs/` plus `.lb` metadata.
  2. The same notebook on **Kaggle 2 × T4** with STORAGE=bucket, and **locally** in
     Jupyter with DEVICE=cpu on a 30 s clip (a local run only on the owner's go).
  3. In the app, fix a speaker, a line and a translation choice → the next notebook run
     redoes **only** those lines, takes and mixes (compare the `runs/<run>/summary.json`
     counts).
  4. Held media and "until transcribe" are respected; releasing a held media finishes it
     on the next run.
  5. Targets conflict: the folder says `am` and the notebook `om` → both are done, with a
     warning. A different LANGUAGE stops the run with the fix.
  6. Drive two writers (E6): the notebook writes `auto/` while the app writes `manual/` and
     tasks → no conflict copies, and no half-synced file is ingested.
  7. A second member on another PC signs in: sees the metadata of media they don't have
     (no player), pulls voicings from the bucket, and starts their language without
     re-transcribing.

## What the owner provides

- An HF organisation and team bucket(s).
- A Supabase free project (URL + publishable key).
- A phone-verified Kaggle account.
- 2–3 Amharic raters for E3.
- A test folder of about 10 preaching videos.
- A second member and PC for acceptance 7.
