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
| TEAM | Team hub: shared metadata, media on everyone's devices, distributed compute | [TEAM.md](TEAM.md) | approved, not started |
| LIB | Library folders (Drive + local disks), folder standard | [LIBRARY_FOLDERS.md](LIBRARY_FOLDERS.md), `app/libraries.py` | built, not yet used on real folders |
| RUN | Colab/device runs end to end, captions trial, batching | `app/runs.py`, `worker/lb_worker/stages/run.py` | built + stub-tested, **not run on Colab yet** |
| BULK | Whole channel on Colab (bulk stage) | `app/bulk.py` | superseded by RUN (jobs cancelled) |
| A5 | Characters belong to the work; works travel (.lbwork) | [PLAN.md](PLAN.md#a5-in-detail), [PACKAGE.md](PACKAGE.md) | done, merged |
| A4 | Series, library of clips, recurring parts | [PLAN.md](PLAN.md#a4-in-detail) | done, merged |
| V2 | Original v2 plan: phases A6–A7, B, C, D, E | [PLAN.md](PLAN.md) | A1–A5 done |

## P0 — to hear the first Colab-made dubs

- [x] **RUN** Rewrite the Colab notebook: plain wording (no "polling jobs"): connect Drive → set up → *Run what the app sent* (one cell, readable progress) → release GPU. (`scripts/sync_worker.py`)
- [x] **RUN** Publish `app/` to Drive with the worker (`sync_worker.py`), so the runner can import it on Colab (`root/worker/app`).
- [x] **RUN** Runner installs yt-dlp / faster-whisper / soundfile; JS runtime node→deno fallback. *(still to confirm on Colab: chromaprint/rubberband in its ffmpeg — fallbacks exist)*
- [x] **RUN** Merge `feat/colab-run` into `main` (build pass before/after), then `sync_worker` (worker changed a lot).
- [ ] **RUN** Real run #1 on Colab — **queued** as `runs/20260926-171244-6-minute-english` (6 episodes, end to end, captions 6 / aligned 2); **waiting for the owner to press Run all in Colab**. Fix what breaks. Then the whole series (transcribe all; dub a batch).
- [ ] **RUN** Open results in the app; play a dubbed MP4 from G: (Mix & export) — owner's acceptance.
- [ ] **RUN** Summarise the captions report for the owner (Whisper vs YouTube captions raw vs aligned: WER, timing).
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
