# Backlog — every open task across every plan, by priority

The single list of what is left to do. Plans come and go as the owner's ideas grow; their
unfinished parts land here so nothing half-paused is lost. **Update this file in the same
commit as the work** (tick it, or move it to Done with the commit). Newest plan first in
"Plans". Priorities: **P0** blocks the owner's current goal · **P1** next · **P2** planned
phase · **P3** later/hardening.

Current goal (owner, 2026-09-26): *open the app and listen to dubbed videos of a whole
series, produced end to end on Colab from Drive; the same for library folders (Drive and
local disks); then teams working on shared metadata with distributed compute.*

## Plans (where each task comes from)

| Tag | Plan | Doc | State |
|---|---|---|---|
| WS | Notebook = the worker, folder = the contract, app refines (approved 2026-09-30; supersedes SCALE Phase B) | [WORKSPACE_PLAN.md](WORKSPACE_PLAN.md) | **P0: notebooks anywhere (Phase 3 first)** |
| SCALE | Decoupled notebooks ↔ app through a workspace folder, one Supabase, HF buckets, media identity, translation loop (branch `exp/scale`) | [SCALE_DESIGN.md](SCALE_DESIGN.md) (+ [research](SCALE_RESEARCH.md)) | **design; certification experiments E1–E6 next, then the build plan** |
| TEAM | Team hub: shared metadata, media on everyone's devices, distributed compute | [TEAM.md](TEAM.md) | approved, not started | — hub mode on the coordinator's PC may be replaced by SCALE §2
| LIB | Library folders (Drive + local disks), folder standard | [LIBRARY_FOLDERS.md](LIBRARY_FOLDERS.md), `app/libraries.py` | built, not yet used on real folders |
| RES | Research notebook: the worker is a pipeline you run by hand on a GPU, not a job picker | [colab/README.md](../colab/README.md), `worker/lb_worker/research.py` | built + stub-tested; **first real Colab run pending** |
| RUN | Colab/device runs end to end, captions trial, batching | `app/runs.py`, `worker/lb_worker/stages/run.py` | built + stub-tested, **not run on Colab yet** |
| BULK | Whole channel on Colab (bulk stage) | `app/bulk.py` | superseded by RUN (jobs cancelled) |
| A5 | Characters belong to the work; works travel (.lbwork) | [PLAN.md](PLAN.md#a5-in-detail), [PACKAGE.md](PACKAGE.md) | done, merged |
| A4 | Series, library of clips, recurring parts | [PLAN.md](PLAN.md#a4-in-detail) | done, merged |
| V2 | Original v2 plan: phases A6–A7, B, C, D, E | [PLAN.md](PLAN.md) | A1–A5 done |

## P0 — to hear the first Colab-made dubs

- [x] **WS P3a** Notebooks re-created under `notebooks/`, running anywhere: Kaggle (2 × T4 detected), Colab (1 × T4), local Jupyter; `HF_TOKEN`/`BUCKET`/DEVICE/STORAGE in the settings cell (no platform secrets); app opens plain result folders (kind `folder`). `lb_worker/env.py`; tested locally (setup cells in a kernel).
- [x] **WS P3a** A working folder is always needed (decision 45): WORKSPACE replaces VIDEOS/OUTPUT; `lang-bridge.json` (lb_core/workspace/config.py) records language, targets, every link; results in `<workspace>/.lb/`; STORAGE = bucket → the bucket is the workspace; app finds runs in `.lb/`.
- [ ] **WS P3a** Owner runs `notebooks/e2e_test.ipynb` on Kaggle (T4 x2) and `notebooks/lang_bridge.ipynb` on Colab (T4) with the settings-cell token/bucket; fix what breaks.
- [ ] **WS P3b** Intel Arc (XPU) shown in the machine card (today the stages use it when present, the card says CPU).
- [ ] **WS P0** Decisions 35–44, plan in the repo (this commit), SCALE_DESIGN/SCALE_PLAN notes.
- [ ] **WS P1** `lb_core/`: pure logic out of `app/` (no behaviour change).
- [ ] **WS P2** Workspace protocol v1 (`lb_core/workspace/`): schema, identity uids, config conflicts, manual over auto, hashes/staleness, tasks, ownership.
- [ ] **WS P4** Pipeline on the workspace (stale-only, hash-named takes, dubs/ output); retire the job queue and old stages.
- [x] **WS P5a** Lines too long to fit get shorter English from Gemma 4 on llama.cpp, translated again; versions stored and chosen in the Translate screen (decision 47, [SHORTEN.md](SHORTEN.md), branch `feat/shorten`).
- [x] **WS P3a** `YT_COOKIES` in the notebooks: YouTube refused Colab's address on the first shortening test (2026-10-01); every yt-dlp call uses a private copy of the person's cookies.txt; guide in notebooks/README.md.
- [x] **WS P5a** Colab run 1 (2026-10-01, 3 × 6ME, T4, 49 min): prediction confirmed (takes 5.88 syl/s vs 6.0 assumed); 109 tight lines but only 16 shortened (answers cut short at the token limit, 28 tok/s with a JSON grammar) → plain-line answers, retry, raw answers kept (`fix/shorten-answers`).
- [ ] **WS P5a** Owner's Colab run 2: about 3 episodes of 6 Minute English with SHORTEN_WITH_LLM on and off; compare `shorten.json`, `fit.json` overflow, tokens/s; listen; set `MIN_SIM` from the meaning scores.
- [ ] **MIX P0** The dub drifts behind the video: `mix.fit` starts each line after the previous take ends, so one overflow delays every later line (Colab run 2026-10-01, 6 Minute English: 15–33 s late by the end, 77/77 lines "overflow"). Needs a re-sync rule (owner to choose): e.g. never start more than ~0.5 s late, squeeze harder or cross-fade to catch up at pauses.
- [ ] **VOICE** Lines of speakers without a voice bank get no take at all (4 lines in "Who does the housework?"): on the native path, voice them natively (no conversion) instead of leaving silence.
- [ ] **RES** A second workspace in the same Colab session keeps the first one's model cache (`LB_CACHE` set once per session; HF_HOME fixed at import).
- [ ] **WS P5b** A rescue pass after voicing for lines whose real take still overflows (measured, not predicted).
- [ ] **WS P5c** Target-side shortening for chosen languages (built into the plan, off everywhere); Amharic after E3.
- [ ] **WS P5** E3 bench, then Gemma chapters (embeddings + pauses propose, the model adjusts by line number and writes title/summary/key terms) + translation loop options.
- [ ] **WS P6** App on workspaces: ingest cache, write-through `manual/`, board, tasks, preview gate, bucket push of app-owned paths.
- [ ] **WS P7** Supabase central metadata (devices, mounts, media copies, sync by revision, cross-team reuse).
- [ ] **WS P8** Migrate existing works, retire old code, acceptance 1–7, merge.

- [x] **RUN** Rewrite the Colab notebook: plain wording (no "polling jobs"): connect Drive → set up → *Run what the app sent* (one cell, readable progress) → release GPU. (`scripts/sync_worker.py`)
- [x] **RUN** Publish `app/` to Drive with the worker (`sync_worker.py`), so the runner can import it on Colab (`root/worker/app`).
- [x] **RUN** Runner installs yt-dlp / faster-whisper / soundfile; JS runtime node→deno fallback. *(still to confirm on Colab: chromaprint/rubberband in its ffmpeg — fallbacks exist)*
- [x] **RUN** Merge `feat/colab-run` into `main` (build pass before/after), then `sync_worker` (worker changed a lot).
- [x] **RES** Research runner `lb_worker/research.py` (`run_folder` over a folder/YouTube links, `run_manifest` for an app-prepared run), notebook `colab/lang_bridge.ipynb` (built by `scripts/build_notebook.py`, `HF_TOKEN` in settings, code cloned from GitHub, Drive mounted by the person), guide `colab/README.md`; Colab runs from the app are prepare-only; `sync_worker.py` removed.
- [ ] **RES** Real run #1 with the notebook: `RUN_FOLDER = /content/drive/MyDrive/LangBridge/runs/20260926-171244-6-minute-english` (6 episodes, end to end, captions 6 / aligned 2) — **owner runs it**. Fix what breaks. Then the whole series (transcribe all; dub a batch).
- [ ] **RES** Retire the Drive job-queue path for `colab` folders (worker `loop.py` on Colab, heartbeat/online status for Drive roots, "Load N finished"); keep the job folder protocol for the local worker only.
- [ ] **RUN** Open results in the app; play a dubbed MP4 from G: (Mix & export) — owner's acceptance.
- [ ] **RUN** Summarise the captions report for the owner (Whisper vs YouTube captions raw vs aligned: WER, timing). *Raw done 2026-09-26 on 6ME (uploader captions): WER 2.9–6.2 %, word timing median 0.12–0.15 s, p90 0.31–0.40 s. Aligned: not produced in run #1 (restart lost the captions note; fixed) — next run.*
- [ ] ~~**RUN** Stale jobs in a device's queue run before new work~~ (moot for Colab after the RES pivot; still valid for the local worker) (a 01:33 `tts_bakeoff` experiment ran first and downgraded protobuf in the Colab session). Add a "Queue on this device" view in the app with cancel, and have the notebook list what it will do before starting.
- [ ] **RUN** `tts_bakeoff` installs Seed-VC deps into the shared Colab environment (protobuf 3.19.6): isolate it in its own venv or retire the stage.
- [ ] **UI** Check the new screens in the browser (the in-app browser tools were unavailable when they were built): Library, Run panel, Home libraries, Series run panel, Cast, Share, Open a shared work.
- [ ] **BULK** ~~Clean up `meta.remote` markers~~ (done 2026-09-26); still decide to retire `app/bulk.py` + `/api/series/*/bulk` + bulk stage, or keep only `fetch_remote` for package media.

## P1 — next

- [ ] **LIB** Register the owner's real libraries: `G:\My Drive\PCDL 2023` (Colab) and `E:\Preachings\PastorJohnVideos` (this PC); scan; explore; a sample run on each device.
- [ ] **LIB** Link language versions of the same teaching (`[hi]` files / language folders) as versions of one episode, not separate sources; show "available in hi, es".
- [ ] **LIB** Import `name.<lang>.srt` subtitles (stored as `subtitles_other`) as human translations for that language, time-matched to lines.
- [ ] **LIB** Library people: declare/edit the library's speakers in the UI (today only via `work.json`), show one person's appearances across works.
- [ ] **RUN** Mark lines/links that a run confirmed under "checks assumed to pass" so people can find and review them later (provenance `assumed`).
- [ ] **RUN** "Continue from here" for step-by-step runs: suggest the next stage after a checked one.
- [ ] **RUN** Tune batching on a real T4: `GROUP_S`, Whisper `batch_size`, voice/score manifest sizes; measure and record numbers in STATE.
- [ ] **RUN** Local device runs: local worker picks `pipeline` jobs (stage list updated) — test a run on E: with the Arc GPU.
- [ ] **TEAM 1** Media identity: `media` + `media_copies`, quick hash, sources → media uid; resolve this device's copy everywhere.
- [ ] **TEAM 2** Devices + `--mode hub|member`, member proxy, tokens, members/invites (coordinator).
- [ ] **TEAM 3** Locate & copy a file into the working folder (hash check, resumable copy); Fetch from team Drive.
- [ ] **TEAM 4** Device-addressed runs through the hub; members upload results; coordinator's run board.
- [ ] **TEAM 5** Edit safety: row versions (409), op log, "who changed what" in the UI.
- [ ] **SEC** API has no authentication (fine on localhost): required before hub mode listens on the LAN (TEAM 2).

- [x] **SCALE** Owner decisions (2026-09-27): content and code may be public; one Supabase for ~10 teams; local folders as well as links; notebooks decoupled from the app; work on branch `exp/scale`.
- [x] **SCALE** Plan approved 2026-09-27: [SCALE_PLAN.md](SCALE_PLAN.md) (certify E1–E6, then build M1–M8, acceptance, merge).
- [x] **SCALE E1+E2** Run on a Colab T4 2026-09-27 (docs/CERTIFICATION.md): separation fp16 2.7× faster (now default), batching gives nothing (GPU ≥ 88 % busy in every stage), Whisper 27× real time, OmniVoice 53 takes/min; identity: link id / quick hash / fingerprint (8-bit threshold, offsets exact).
- [x] **SCALE merge** 2026-09-27 (owner): exp/scale fast-forwarded into main; old main kept as `main-before-scale`; notebooks download `main`.
- [x] **RES** Notebook for Colab and Kaggle: ASR per source language (Whisper, or a named HF model; Amharic built in), default aligners for ~27 languages, HF_TOKEN from secrets, results pushed to a Hugging Face bucket after every stage; app: bucket devices, Sync, Runs on devices, results opened by themselves (2026-09-28).
- [ ] **RES** End-to-end on Kaggle → bucket → app with two 6 Minute English videos; then a Turkish and an Amharic source.
  - 2026-09-28 run 1: bucket push and app sync worked; failed at speaker detection (pyannote telemetry vs Kaggle's opentelemetry) → fixed (baae72d); only one T4 used → separation on GPU 1 during transcription, voicing/scoring split across GPUs.
- [ ] **SCALE E1 Kaggle** Same notebook on Kaggle 2 × T4 (account needs phone verification for GPU).
- [ ] **SCALE M4a** Chapters made by the LLM after transcription (topic boundaries at lines, title, summary, key terms → translation context + glossary; people adjust; fallback: pauses + LaBSE topic shift). docs/SCALE_DESIGN.md §5.
- [ ] **SCALE E3** Translation bench notebook (Google, rephrase, TranslateGemma, NLLB, Gemma 4; rating page for 2–3 Amharic speakers).
- [ ] **SCALE E4–E6** OmniVoice reference length; Supabase + HF bucket round trip; Drive two-writer test. Then `docs/CERTIFICATION.md` and owner approval of Phase B.
- [ ] **SCALE 1** Media identity: link identity + quick hash + Chromaprint fingerprint with time offset; `media_copies`; "open with my copy" (supersedes the full-SHA-256 idea).
- [ ] **SCALE 2** Supabase team hub: schema, RLS by team, sign-in in the app, device keys for notebooks, local-first sync with row versions (replaces TEAM 2 + TEAM 5 if approved).
- [ ] **SCALE 3** Selective export (videos × layers: work / voicings of a language / mix), voicing packs, inbox auto-detect in the working folder.
- [ ] **SCALE 4** Work board: videos × stages (pending/running/done/checked/stale/failed), recommended order with a cast pass, re-run selected cells.
- [ ] **SCALE 5** Claims with leases so two members never run the same video; notebook takes a team device key; Kaggle (2×T4) notebook.
- [ ] **SCALE 6** Generated audio on Cloudflare R2 behind a storage interface (signed URLs via an edge function); Telegram only as optional "publish to channel".
- [ ] **SCALE 7** Translation bake-off on Colab (llama.cpp): NLLB-3.3B vs TranslateGemma-12B vs Gemma 4, scored by AfriCOMET-QE + people; then the Fit step (timing-aware shortening, manual pick).
- [ ] **SCALE 8** OmniVoice reference 6–10 s (today ~12–20 s, `banks.TARGET_S`), best-of-N reference by held-out score.
- [x] **VOICE** Voice-path test on the camille clip (`spikes/voice_paths`, Colab T4, 2026-09-30): OmniVoice cloning vs native speech + Seed-VC; the owner chose native + Seed-VC Whisper by ear → decision 46, the default for Amharic.
- [ ] **VOICE** First real run with the native path (a 6ME video + a sermon); owner listens; check the takes' loudness after conversion.
- [ ] **VOICE** Native voices for more languages: FLEURS has gender-labelled native speakers for ~100 languages (Oromo, Tigrinya next); pick the native voice nearest the character's pitch.
- [ ] **VOICE** Per-character path (native / clone) in the app; Seed-VC fine-tuned on a recurring speaker (~2 min on a T4) for likeness.
- [ ] **RUN** Colab: overlap CPU and GPU in every phase (voice→mix per video, decode/VAD of the next group during Whisper).
- [ ] **RUN** Mixing is CPU-bound: 136–138 s per 6-min video on Colab (2 vCPUs), one rubberband ffmpeg per line (`app/mix.py render`). Stretch lines in one ffmpeg pass or in-process; run mixing while the next video voices.
- [ ] **RUN** Separation is the biggest fixed cost (~305 s per 6-min video on a T4, run #1): try separator `batch_size`, fp16 autocast, a lighter speech model; never separate a video twice (team-shared stems / cache).
- [ ] **RUN** OmniVoice in batches (`omnivoice-infer-batch` / batched `generate`) instead of one take per call in `tts/omnivoice_gen.py`; measure takes/min on a T4.

## P2 — planned phases

- [ ] **V2 A6** Per-language keep-words (`app/interjections.py`).
- [ ] **V2 A7** Unknown-language path: VAD-only segmentation → empty lines for manual transcription; optional MMS/Omnilingual drafts.
- [ ] **A4** Recurring parts on a real series with an identical intro (6ME's YouTube uploads have none); re-check the synthetic timing constants.
- [ ] **A4** Clips: multi-span clips in the UI (revisions allow them; playback uses the first span); discovery runs synchronously (move to a task for big series).
- [ ] **A5** Oromo machine translation in the sandbox import test (owner stopped that call; do it when wanted).
- [ ] **V2 C** Human voices: chapter-grouped recording sessions, `split_session`, `convert`, consent & licence, dataset export, training stage.
- [ ] **V2 D** Journeys across languages: port recomposer model, moments from clips, editor, language-crossing playback, explained suggestions, stage presets in collections, export.

## P3 — later / hardening

- [ ] **V2 E** Backups, rate limits, audit views, open sign-up, HTTP job queue replacing Drive folders, accessibility, server deployment docs, security review.
- [ ] **TEAM** Move the hub from the coordinator's PC to a server (Postgres).
- [ ] Remove-a-target-language UI/API (only adding exists).
- [ ] Tech debt: old `characters` table (migrated, unused); `scripts/adopt_spike.py` still writes it; `ColabBatch` gone but `app/bulk.py` remains (see P0).

## Done (by plan, newest first)

- **LIB/RUN/TEAM groundwork (feat/colab-run, merged `c94768e`, worker+app published to Drive):** captions/subtitles reader; batched Whisper across videos; packages with media `ref`; per-source media folder; runs (one `pipeline` job, stages, resumable, results per work); library folders + standard; multi-work runs; one teacher across a library's works; brief project lists; Library/Run screens.
- **BULK (merged):** bulk stage, Drive-only fetching, test isolation (`tests/conftest.py`).
- **A5 (merged):** works for every source, uids, cast/appearances/matching (threshold 0.55 from real data), voice banks, Cast screen, `.lbwork` share/import, pivot reference; real run on 6 Minute English.
- **A4 (merged):** series, channel picker, clips & collections, fingerprints, recurring parts, reuse in dubbing, sandbox.
- **A3, A2, A1, v1:** chapters; languages as data; length per script; the v1 pipeline.
