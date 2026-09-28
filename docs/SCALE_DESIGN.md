# Design: notebooks that dub on their own, an app that refines, a team that shares

Status: **design for certification** (2026-09-27, branch `exp/scale`). Nothing here is
built yet. Section 9 lists the experiments that decide the open tool choices; the build
plan is written after they have run. Background research: [SCALE_RESEARCH.md](SCALE_RESEARCH.md).

## 0. Context the owner set (2026-09-27)

- An organisation of **~10 teams**, each with its own sources (series and films,
  YouTube education channels, preaching by different preachers) and target languages.
  The goal is public release: **code and content may be public**.
- Sources are **links** (anything yt-dlp can fetch) **and local folders**: a folder with
  any nesting of videos must run end to end, on Colab (Drive) and if possible Kaggle.
- **One Supabase** for all teams. A ~100 GB audio store is welcome.
- **Execution and metadata management are decoupled.** A notebook is a self-contained
  dubbing machine that reads a folder or links and writes files; the app reads those
  files, lets people refine them, shares them through the cloud, and can ask for re-runs.
  No chatty API between notebook and app.
- Translation: rephrase the source where it helps, translate with **Google Translate and
  an LLM**, check in cycles, and give people **a short list of good options** to choose from.
- The GPU must be used: in run #1 separation used **2.5 of 15 GB** GPU memory and 2.9 of
  12.7 GB RAM (Colab screenshot, 18:27–18:57), one 3.2 s chunk at a time.

## 1. The shape

```
                    ┌──────────── Supabase (one project) ────────────┐
                    │ teams, members, works, media identities,        │
                    │ lines, speakers, characters, translations,      │
                    │ choices, tasks/claims, who-changed-what         │
                    └───────────────▲───────────────────────────▲────┘
                                    │ app only (sign-in)         │
   ┌────────── app (each member's PC) ──────────┐               │
   │ opens a team WORKSPACE folder              │               │
   │ ingests notebook files → local SQLite      │               │
   │ people refine (transcript, cast, timing,   │               │
   │ translation choice, voices) → manual layer │               │
   │ writes TASK files, pushes/pulls Supabase   │               │
   └──────────────▲─────────────────────────────┘               │
                  │ files only (Drive for Desktop / hf sync)     │
   ┌──────────────┴──────── WORKSPACE (a folder) ───────────────┴──────┐
   │ videos in any nesting · links.txt · .lb/ (all machine data)       │
   │ lives on Google Drive, a local disk, and/or an HF Storage Bucket  │
   └──────────────▲────────────────────────────────────────────────────┘
                  │ files only
   notebooks: Colab (mounts Drive) · Kaggle (syncs an HF bucket) · a local GPU
   run with no app at all: folder/links in → dubs + .lb metadata out
```

Rules that make it work:

1. **The workspace folder is the contract.** Notebooks and the app never call each other.
2. **Notebooks never need Supabase.** Only the app talks to the central database, so a
   notebook needs no team credentials (just `HF_TOKEN`, as today).
3. **Single writer per file.** Notebooks write the *auto* layer; the app writes the
   *manual* layer and task files. Google Drive never sees two writers on one file, so no
   "file (1)" conflict copies.
4. **Every derived result records the hash of what it was made from.** Staleness, re-runs
   after edits and "skip what is done" all follow from comparing hashes, not from bookkeeping.

## 2. The workspace protocol

```
<workspace>/
  workspace.json              team, source language, target languages, defaults (app writes; notebook reads)
  links.txt                   optional: channel / playlist / video links, one per line
  <any folders of videos>/    the team's own organisation, untouched
  dubs/<same nesting>/<name>.<lang>.mp4 (+ .srt)   finished dubs, mirroring the source tree
  .lb/
    media/<media-uid>/
      media.json              identity (§3): links, quick hash, duration, fingerprint, known paths
      auto/                   written by notebooks only
        transcript.json       lines + words + speaker labels, per-line id and hash
        speakers.json         diarization, voice embeddings per label
        tr.<lang>.json        per line: candidates, checks, rounds, recommended option (§5)
        voice.<lang>.json     per line: takes, scores, best take
        stems/ takes/<lang>/ mix/<lang>.m4a
        stage.json            per stage: state, input hash, tool versions, device, time
      manual/                 written by the app only (people's decisions)
        transcript.json       edited text/timing/speaker per line (only lines people touched)
        tr.<lang>.json        chosen or typed translation per line
        voice.<lang>.json     chosen take / recorded take per line
    cast/                     characters of the work, their voice references (app: manual, notebook: proposals)
    tasks/                    task files from the app: <id>.json → notebook writes <id>.done.json
    runs/<run>/log.txt        what each notebook run did
```

**Effective data = manual over auto**, line by line. A notebook reading a video first
merges `manual/` over `auto/`, so corrections feed every later stage.

**Staleness.** Each stage output stores `inputs_hash` = hash of exactly what it used
(e.g. a line's translation: the effective source text + speaker + slot length + glossary
version; a take: the chosen translation text + voice reference hash + engine settings).
A notebook recomputes the hash; different → that line is stale → redo just that line.
So correcting a speaker re-voices only that speaker's lines; fixing a line's timing
re-fits and re-voices that line; nothing else moves.

**Tasks** add scope and priority, not correctness:
`{"id", "videos": [...] | "all", "stages": [...], "langs": [...], "device": "any" | name,
"note"}`. A notebook started on a workspace does pending tasks first; with none, it
brings **every video** to "dubbed and up to date". The app assigns tasks to devices, so
two notebooks on one workspace do not take the same video (a notebook writes
`<id>.claimed.json` with its session and an expiry, best effort on Drive).

**Kaggle and other runtimes without Drive**: the workspace is mirrored in an **HF
Storage Bucket** (`hf sync`, only changed files move). The notebook syncs down the
`.lb/` data and the videos it needs, works, syncs up. For link sources, nothing but
`.lb/` needs to move at all. The app can keep a workspace on Drive and mirror it to a
bucket, or use the bucket as the team's cloud copy.

## 3. Recognising the same video anywhere

Certified approach (to be confirmed by experiment E2):

| Key | How | Catches |
|---|---|---|
| Link identity | yt-dlp `extractor_key:id` (e.g. `Youtube:dQw4w9WgXcQ`) | the same online video, before any download |
| Quick hash | SHA-256 of size + first 4 MB + last 4 MB | the same file copied anywhere; reads 8 MB even on a streamed Drive file |
| Fingerprint | Chromaprint of the audio (head + a middle window), matched with time offset (`app/fingerprint.py` `find_part`) | the same content re-encoded, re-downloaded in another format, trimmed or with a different intro |

A full-file SHA-256 is not used: re-downloads differ in bytes, and hashing a Drive file
downloads all of it. Centrally, `media` rows hold link ids, quick hashes and a compact
fingerprint (~4 KB); a new file is matched by quick hash, else by duration ± a few
seconds then fingerprint. A match carries its **offset**, so every line's times are
shifted onto the local copy.

This is also the **non-duplication check**: when the app finds a workspace video that
another team already processed, it pulls that work's transcript, speakers and cast into
`manual/`-equivalent "imported" data, so the notebook skips transcription and goes
straight to the missing languages.

## 4. Central store: Supabase + Hugging Face

**Supabase (metadata, one project, all teams).** Tables mirror the effective data:
`teams, members, works, media, media_links, lines, speakers, characters, appearances,
translations (candidates jsonb, chosen, status), voice_choices, tasks, events`.
Word timings, candidates' check details and anything bulky go to the bucket as files and
are referenced by path, keeping the database well inside the free 500 MB.

- **Row-level security**: every team can *read* all works (the goal is public anyway);
  a team *writes* its own works and its own target languages; a language team may add
  translations to another team's work. Edits carry `rev` and member; a stale write is
  refused (409) and shown for merging.
- **Only the app talks to Supabase**, with the member's sign-in. Sync is by revision:
  push changed rows since last sync, pull rows newer than the local copy.
- Free-tier caveats: no backups (→ a weekly export of the database into the bucket),
  project pauses after 7 days without requests (not a risk with 10 active teams).

**Hugging Face Storage Buckets (audio and bulky files)**: S3-like, mutable, not git
(no commit limits, deletions free the space), `sync` in both directions, public or
private, owned by an organisation, reached with the `HF_TOKEN` members already need.
One org, a bucket per team (or per work): `stems/` (Opus), `takes/`, `mix/`, word files.
Source videos are **not** stored centrally: links are re-fetched, local files stay with
their owners (a team may choose to share a public copy later). Free private storage is
100 GB per free account/org; public storage is best-effort free for useful content.

## 5. Translation: cycles of rephrase, translate, check → options for people

Per **chapter** (so the model sees the context), per target language:

```
1 prepare     source lines + speakers + time slot per line + glossary/keep-words + chapter summary
2 rephrase    LLM rewrites source lines that are hard to translate (idioms, fillers, ASR slips,
              ellipsis) into plain source-language sentences; original kept; changes flagged
3 candidates  a) Google(original)  b) Google(rephrased)  c) LLM(chapter context, slot budget)
4 check       back-translation (Google target→source) + sentence-embedding similarity (LaBSE)
              · reference-free quality (AfriCOMET-QE: covers am, om, so, sw …)
              · length fit: estimated spoken duration vs slot (rate learned from our own takes)
              · LLM judge: names concrete problems (meaning lost, wrong term, register)
5 revise      candidates failing a check go back to the LLM with the specific findings
              ("22 % too long", "back-translation lost 'forgiveness'") — at most 2 rounds
6 options     keep the ≤4 best distinct candidates with their scores and flags;
              the best one is used for a first dub, people choose in the app
```

**Chapters made by the model (step 0, owner's idea 2026-09-28).** Chapters are already the
unit of translation context in the app (`app/chapters.py`), but today a video starts as one
chapter unless a person splits it. After transcription the instruction model reads the
transcript and proposes chapters at line boundaries where the topic changes, each with a
title, a two-line summary and its key terms (names, scripture references, technical words).
They are written as *auto* chapters; people adjust them in the app (manual wins). The
summary and key terms go into every translation prompt of that chapter and seed the
glossary, and chapter size is kept to what the translator handles well (a few minutes).
Without an LLM, a fallback splits at long pauses and topic shifts in sentence embeddings
(LaBSE), so every run gets chapters.

All steps are logged per line (`tr.<lang>.json`: rounds, candidates, checks), so people
see *why* an option is recommended and a better model later can re-run only step 3–6.

**All models run inside the notebook** on its GPU (no API keys, no per-call cost); they
run one after another, each loaded once per phase. Two roles, not certified yet (E3):

| Role | Steps | Candidates (4-bit on a free T4, or Kaggle's 2 × T4) |
|---|---|---|
| Translator | 3c | **TranslateGemma** 4B / 12B (Amharic is not among its 55 benchmarked languages: test it, do not assume it), NLLB-200 3.3B |
| Instruction model | 2, 4 (judge), 5 | **Gemma 4** E4B (one T4) or 26B MoE (2 × T4), Gemma 3 12B |

TranslateGemma is tuned to translate, not to follow editing instructions, so it cannot
do the rephrase / judge / revise steps; a general Gemma does those. Google Translate
stays in the loop as a baseline translator and as the back-translator. A hosted model
(Gemini API, strongest on Amharic in AfroBench) is only a **reference point in E3**; if it
wins clearly it could become an opt-in step with a team's own key, never a requirement.

## 6. The notebook

One notebook, three ways in, same pipeline:

```
SOURCE = "/content/drive/MyDrive/Teams/Preaching"   # a workspace or any folder of videos
LINKS  = ""                                          # and/or links (channel, playlist, videos)
TARGETS = "am"          HF_TOKEN = ""                # BUCKET = "" (Kaggle / no Drive)
```

- A plain folder becomes a workspace on first run (`.lb/` created beside the videos;
  `workspace.json` with defaults). Nothing else in the folder is touched.
- Order: tasks first; otherwise every video, stage by stage, skipping what is up to date.
- **GPU use**: each stage runs over *all* ready videos with the model loaded once and
  inputs batched (Whisper already is); separation and voicing get batching (E1);
  CPU work (download, decode, mix, upload) runs on threads alongside. On 2 × T4
  (Kaggle) two processes each take half the videos.
- Resumable anywhere: every stage output is written atomically with its input hash.
- Output a person can use without the app: `dubs/…/<name>.<lang>.mp4` + `.srt`.

Code: the pipeline becomes a package with **no dependency on the app** (today the runner
loads the app headless on a scratch database). Shared between both: one schema module
(the file formats above, versioned). The app gets an ingest/export layer for `.lb/`.

## 7. The app

- **Workspaces**: a team member opens the team's folder (local, or on Drive for Desktop).
  The app lists the videos (any nesting), their stage status from `stage.json`, and new
  notebook results; ingest is incremental (by file revision).
- **Refine**: everything people do today (lines, speakers → characters, timing,
  translation choice from the options, takes) is written to `manual/` and pushed to
  Supabase. Staleness is shown ("7 lines need re-voicing after your edits").
- **Re-run**: "update these videos" writes a task file; the next notebook run (by
  anyone on the team) picks it up. The work board (videos × stages) shows state,
  device and stale counts.
- **Shared progress**: pull other teams' work on matching media (§3); languages advance
  in parallel on one transcript and cast.
- **Languages without a recogniser** (V2 A7): VAD-made empty lines, typed by people.
  **Self-registration**: a member records lines for a character in their own voice
  (consent), stored as takes and as that character's reference for the language.
- `.lbwork` stays as the **zip for sharing** selected videos/layers by hand.

## 8. What changes from today's code

| Today | Becomes |
|---|---|
| runner loads app code on a scratch SQLite, writes `.lbwork` results | stand-alone pipeline package writing `.lb/` files |
| app prepares `runs/<id>/manifest.json` | app writes `tasks/*.json` in the workspace |
| `libraries.py` scan + device refs | workspace scan + media identity (§3) |
| `.lbwork` import as the way results arrive | incremental `.lb/` ingest; `.lbwork` for manual sharing |
| local SQLite is the truth | local SQLite is a cache of workspace + Supabase |

Kept: the stages themselves (batched Whisper, alignment, pyannote, cast matching,
banks, OmniVoice, scoring, mix/export), fingerprints, captions, the web UI screens.

## 9. Certification experiments (run before the build plan)

| # | Question | How | Decides |
|---|---|---|---|
| E1 | How fast can one T4 (and 2 × T4) go per stage? | bench notebook: separator `batch_size` 1/4/8/16 × autocast; OmniVoice batch 1/8/16; Whisper `batch_size` 16/32; on 3 videos | stage settings; hours of video per GPU-hour |
| E2 | Does identity hold? | same 6ME video as 720p/360p/MP3/trimmed/+intro vs 5 other episodes: quick hash, fingerprint match + offset | the §3 thresholds |
| E3 | Which translation loop and LLM? | 150–200 lines (6ME + a sermon), systems: Google, Google+rephrase, each LLM, full loop; 2–3 Amharic speakers rate blind (meaning, fluency, dubbable length); correlate with QE/back-translation | LLM, rounds, check thresholds |
| E4 | OmniVoice reference length | 3 / 6 / 10 / 15 s refs × 3 characters: likeness, CER, by ear | bank length |
| E5 | Supabase + bucket round trip | schema + RLS on a free project; ingest one work; measure DB bytes per video; bucket sync of `.lb/` | schema, sizes, sync |
| E6 | Workspace on Drive under two writers | notebook writing `auto/` while the app writes `manual/` and tasks, both through Drive | the single-writer rules |

## 10. Risks

- **yt-dlp on Colab/Kaggle IPs**: YouTube can ask datacenter IPs to sign in; allow a
  cookies file, and prefer the uploader's own copies for big libraries.
- **Google Translate** is used through an unofficial endpoint; it may throttle Colab
  IPs. The loop must work with the LLM alone (E3 covers it).
- **Kaggle** needs a phone-verified account for GPU and internet; sessions are 12 h and
  the GPU quota ~30 h a week.
- **Drive for Desktop** syncs in seconds to minutes: the app must treat half-synced files
  as not there yet (write-then-rename, and checksums in `stage.json`).
- **Supabase free tier**: 500 MB, no backups (weekly export), pause after 7 idle days.

## Sources

[HF Storage Buckets](https://huggingface.co/docs/hub/en/storage-buckets) ·
[HF storage limits](https://huggingface.co/docs/hub/en/storage-limits) ·
[Supabase free tier](https://uibakery.io/blog/supabase-pricing) ·
[audio-separator options](https://github.com/nomadkaraoke/python-audio-separator/blob/main/README.md) ·
[OmniVoice](https://github.com/k2-fsa/OmniVoice/blob/master/README.md) ·
[Kaggle GPU](https://www.kaggle.com/docs/efficient-gpu-usage) ·
[AfriCOMET-QE](https://huggingface.co/masakhane/africomet-qe-stl) ·
[WMT24++ languages](https://arxiv.org/html/2502.12404v1) ·
[TranslateGemma languages](https://huggingface.co/google/translategemma-27b-it/discussions/1) ·
[AfroBench](https://arxiv.org/html/2311.07978)
