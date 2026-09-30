# Plan: test, then build the decoupled system (branch `exp/scale`)

## Context

~10 teams in one organisation dub teachings, series and channels into many languages,
for public release. The owner wants: **notebooks that dub a folder or links end to end
on their own** (Colab with Drive, Kaggle too), writing metadata in files; **an app** that
opens a team's folder, lets people refine, shares metadata through **one Supabase**, and
orders **re-runs** that notebooks pick up; audio in a ~100 GB store; a **translation loop**
(rephrase → Google + LLM → checks → options for people); the GPU actually used (run #1
used 2.5 of 15 GB). Design: `docs/SCALE_DESIGN.md` (branch `exp/scale`). This plan is
how we certify the tools, then build it, with a test gate at every step.

## How work is started (owner's rule of thumb)

- **In the app** (the normal way): a person starts a project from a **local folder** or
  from **links** (channel, playlist, videos). The app lists what is there; the person
  **picks the videos** to work on (for links, only picked videos are ever downloaded) and
  sets **how far the pipeline goes** for them: *end to end* (default), or *stop after*
  fetch / transcribe (+ speakers) / translate / voice. Example: noisy sermons → "stop
  after transcription", people check the transcripts, then release them to continue.
- The app writes this as the workspace **plan** (`.lb/plan.json`: per video `until`
  stage, and `hold` until a person releases it) plus task files; notebooks pick them up.
- **Without instructions** (a notebook pointed at a folder or links, no plan): every
  video runs end to end. A video with a stop point is never taken past it until a
  person releases it in the app (or sets a new stop point).

## Kaggle: how its results reach the app (the owner's question)

Kaggle cannot mount Google Drive, and the app cannot see inside a Kaggle session. Both
can reach a **Hugging Face Storage Bucket** (S3-like, `hf sync` both ways, `HF_TOKEN`
which members already have). The bucket is the meeting point:

```
 app (member's PC) ──hf sync──► bucket team-X/ ◄──hf sync── Kaggle notebook
 workspace folder               .lb/ metadata, audio            downloads links itself
 (local or G:)                  (+ uploaded source audio)       works, syncs results up
```

- **Link sources** (YouTube etc.): Kaggle downloads from the link itself; only `.lb/`
  moves through the bucket. Fully supported.
- **Local-folder videos**: not only links. The app uploads a **compact audio copy** of
  the chosen videos (Opus, ~70 MB per hour) to the bucket, not the video. Kaggle runs
  every stage and produces the dub track (`mix/<lang>.m4a`) + subtitles. The app plays
  the original local video with the dub track; the final MP4 is a stream copy (no
  re-encoding) done by the next Colab run or on demand. E1 checks that separation from
  the Opus copy sounds as good as from the original.
- Colab can use the bucket too, so Drive becomes a convenience, not a requirement.

## Working rules

- All on branch `exp/scale`; each step is a commit checked alone with
  `scripts/check_commit.sh`; nothing merges to `main` until the acceptance runs (Phase C)
  pass. The owner pushes the branch (this session has no GitHub login).
- Nothing heavy runs on the owner's PC: model work is in notebooks the owner starts;
  tests stub the models (as `tests/test_run.py` does).
- No secrets in the repo: `HF_TOKEN`, Supabase keys and Kaggle tokens are typed by the
  owner into the notebook/app settings. The Supabase *secret* key is never used by the app.

## Phase A — certify the tools (before building)

I write two bench notebooks (`colab/bench_gpu_identity.ipynb`, `colab/bench_translation.ipynb`,
generated like `scripts/build_notebook.py`), plus small local scripts; the owner runs them
on Colab / Kaggle and pastes the printed summary. Each experiment has a pass rule.

| # | What is tested | Pass rule → decision |
|---|---|---|
| E1 GPU | separator `batch_size` 1/4/8/16 × autocast × several files per call; OmniVoice batched vs one-by-one; Whisper `batch_size`; separation from Opus copy vs original; on 3 × 6ME and 1 sermon, Colab T4 and Kaggle 2 × T4 | fastest setting whose stems differ from the batch-1 baseline by < −50 dB; GPU memory > 60 % while separating/voicing → stage settings, audio-copy format |
| E2 identity | one video as 720p / 360p / MP3 / trimmed 10 s / extra intro vs 10 other episodes and sermons: quick hash, fingerprint match (reusing `app/fingerprint.py` `find_part`) | every variant matched, offset error ≤ 0.2 s, zero false matches → thresholds |
| E3 translation | 150–200 lines (6ME + a sermon), systems: Google, Google+rephrase, TranslateGemma 4B/12B, NLLB-3.3B, Gemma 4 E4B (T4) / 26B MoE (Kaggle 2 × T4) as translator and as rephrase/judge/revise, full loop on/off; Gemini API only as a reference; 2–3 Amharic speakers rate blind (meaning, fluency, fits the time) in a rating page the notebook writes | highest "acceptable without edits" rate within a T4 time budget; automatic checks (AfriCOMET-QE, back-translation LaBSE, length) must rank systems like people do (Spearman ≥ 0.6) or they are shown as hints only → models, rounds, thresholds |
| E4 voice refs | OmniVoice reference 3 / 6 / 10 / 15 s × 3 characters (scoring from `worker/lb_worker/tts/score.py`) + listening | best likeness with CER not worse → bank length (`app/banks.py` `TARGET_S`) |
| E5 central | Supabase free project: schema + row-level security; ingest one work; bucket sync of a workspace | team A cannot write team B's work (tests); DB bytes per video measured; round trip identical |
| E6 Drive | notebook writing `auto/` while the app writes `manual/` and tasks, through Drive for Desktop, 100 cycles | no conflict copies; a half-synced file is never ingested |

Output: `docs/CERTIFICATION.md` with numbers and decisions; then the owner approves Phase B.

## Phase B — build

> **Superseded (2026-09-30)** by [WORKSPACE_PLAN.md](WORKSPACE_PLAN.md) (notebook runs anywhere,
> app works only with folders, job queue retired, Supabase with devices and folders). (each milestone: code + tests + a demo the owner can run)

**M1 Workspace protocol** — new `app/workspace/` (used by app and notebook):
file formats (versioned JSON schemas) for `media.json`, `auto/*`, `manual/*`, `stage.json`,
`plan.json` (picked videos, per-video `until` stage and `hold`), `tasks/*`; merge "manual over auto" per line; `inputs_hash` per line/stage and staleness;
atomic write-then-rename; scan of any folder nesting + `links.txt`.
Reuse: the export/import logic of `app/package.py` (uids, manual truth, media refs).
Tests: round trip, merge, staleness (edit a speaker → only that speaker's lines stale).

**M2 Media identity** — `app/identity.py`: link id via yt-dlp, quick hash (size + first/last
4 MB), compact fingerprint + match with offset (reusing `app/fingerprint.py`), thresholds
from E2. Tests: fixtures of variants (short synthetic clips as in `tests/test_fingerprint.py`).

**M3 Notebook pipeline on a workspace** — `worker/lb_worker/pipeline/`: scan → identity →
load `.lb` (auto + manual) into the existing engine (the stage code in
`worker/lb_worker/stages/run.py` on a scratch catalogue, as `research.py` does today) →
run only stale/missing work per line → write `.lb/auto` + `dubs/<same nesting>/`.
Order: tasks first; then the plan's picked videos up to their `until` stage (held videos
wait); with no plan, every video end to end. Batching from E1 (separator settings in
`stages/analysis.py` `load_separator`, batched `tts/omnivoice_gen.py`), CPU work on threads,
2 × T4 = two processes splitting the videos. Tests: stubbed models, a folder with nested
videos + an `.srt`, re-run after a manual edit touches only affected lines.

**M4 Translation loop** — `worker/lb_worker/translate_loop/`: per chapter, rephrase →
candidates (Google via `app/translate/google_batch.py`, the certified LLM) → checks
(QE, back-translation, length via `app/translate/length.py` / `ethiopic.py`) → ≤ 2 revise
rounds → ≤ 4 options with scores in `auto/tr.<lang>.json`. Tests: stubbed models, loop
stops, options ranked, a manual choice is never overwritten.

**M5 Notebooks** — `scripts/build_notebook.py` writes `colab/lang_bridge.ipynb` (SOURCE =
folder/workspace on Drive, LINKS, TARGETS, HF_TOKEN, optional BUCKET) and
`kaggle/lang_bridge.ipynb` (LINKS and/or BUCKET, HF_TOKEN from Kaggle secrets); guides in
`colab/README.md`, `kaggle/README.md`. Demo: the owner runs a preaching folder with no app.

**M6 App on a workspace** — **new project** from a local folder or links (channel/playlist
expanded with `app/feeds.py`): list items, pick videos, set "run until" per video or for
the selection (default end to end), release held videos after checking; open a team
folder; list videos (any nesting) with stage state;
incremental ingest of `.lb` into SQLite (cache); every edit written to `manual/`; stale
counts; "update these videos" writes a task; work board (videos × stages); bucket sync
button and upload of compact audio for Kaggle. Reuse: Library/RunPanel screens
(`web/src/screens/Library.tsx`, `web/src/shell/RunPanel.tsx`), `app/libraries.py` scanning.

**M7 Supabase** — `supabase/migrations/*.sql` (schema + RLS), sign-in in the app, push/pull
by revision with 409 on stale writes, identity match → pull another team's transcript /
speakers / cast so the notebook skips to the missing languages; weekly export to the bucket.

**M8 Move over and tidy** — export existing works (the 6ME series) into a workspace;
retire run manifests, `app/bulk.py` and the Drive job queue; update README, STATE, BACKLOG.

## Phase C — acceptance (the owner runs; then merge to `main`)

1. A preaching folder on Drive (10 videos, nested) → Colab notebook, **no app** → dubs +
   `.lb` metadata, all end to end.
2. In the app: new project from a playlist, pick 5 of its videos, 2 of them "stop after
   transcription" → notebook run → 3 dubbed, 2 held at transcripts → a person fixes
   those transcripts and releases them → next run finishes them.
3. The app opens the folder from 1, a person fixes a speaker, a line and a translation
   choice → "update" → the next notebook run redoes **only** those lines; dub improves.
4. Kaggle: a playlist through the bucket → the app ingests; and one local-folder video
   via uploaded audio.
5. A second member (another team, another language) signs in, sees the work via
   Supabase, starts their language without re-transcribing.
6. GPU use during separation/voicing at the E1 level.

## What the owner provides

An HF organisation + bucket(s) · a Supabase free project (URL + publishable key) ·
a Kaggle account with phone verification · 2–3 Amharic raters for E3 · a test folder
(~10 preaching videos) · a second member for acceptance 4.

## Verification (every milestone)

`python -m pytest -q tests` (new tests per milestone, models stubbed), `cd web && npx tsc
--noEmit && npm run build` when the UI changes, `bash scripts/check_commit.sh [web]` per
commit, and the milestone's demo run by the owner on Colab/Kaggle with its printed summary.
