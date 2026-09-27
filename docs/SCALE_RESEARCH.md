# Research: many people, many devices, one team's work

Status: research (2026-09-27), background for [SCALE_DESIGN.md](SCALE_DESIGN.md), which
supersedes it where they differ (owner decisions: one Supabase, public content, HF Storage
Buckets instead of R2, notebooks and app decoupled through a workspace folder). It answers the owner's "upgrade thoughts"
of 2026-09-27 and changes parts of [TEAM.md](TEAM.md) (the hub on the coordinator's PC).
Each section ends with a recommendation; the list at the end is what would go into
[BACKLOG.md](BACKLOG.md) once agreed.

## 1. The goal in one picture

```
             ┌─────────── hosted, free tier ───────────┐
             │  Postgres + auth (metadata)              │   works, sources, lines, words*,
             │  object storage (small generated audio)  │   cast, translations, runs, claims,
             └──────▲──────────────▲───────────────▲────┘   who changed what
                    │ user token   │ device key    │ device key
          app on a member's PC   Colab (member A)   Kaggle / a local GPU (member B)
          (local SQLite = cache, media files stay where they are: G:, E:, a folder)
          source media: from the link (yt-dlp) or the person's own copy, never uploaded
```

\* word timings as files in object storage, not rows (see §2).

- **Metadata is central**: every device reads and writes the same team work through one
  API with a token; the local SQLite becomes a cache and the offline copy.
- **Source media are never central**: link sources (YouTube, playlists, channels) are
  downloaded from the link by whoever works on them; local files stay on the person's
  disk or Drive and are recognised by content (§4).
- **Generated audio is small** and can be shared through object storage or a
  `.lbwork` zip (§3, §5). Target-language voicings are a separate, optional layer: a new
  team starts from transcripts, translations and cast without them.

## 2. Central metadata: which hosted database

| | Supabase (free) | Neon (free) | MongoDB Atlas M0 |
|---|---|---|---|
| Database | Postgres, 500 MB | Postgres, 0.5 GB per project, 100 CU-h/month | 512 MB, documents |
| Auth / tokens | **built in** (users, JWT, row-level security) | none: needs our own API server | Atlas app services |
| API without our server | **yes** (PostgREST + realtime) | no | partly |
| File storage | 1 GB | — | — |
| Catch | pauses after 7 days with no requests | scales to zero (no pause) | not relational (our data is) |

Sources: [Supabase limits](https://uibakery.io/blog/supabase-pricing), [Neon limits](https://neon.com/faqs/free-plan-limits-and-quotas),
[Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [API keys](https://supabase.com/docs/guides/getting-started/api-keys).

**Why Supabase fits**: "token and auth" come for free. The app and every notebook talk
to the database directly with the member's token; **row-level security** decides what a
member may read or write (their teams' works only), so no server has to be hosted or kept
running by the owner. The publishable key can ship in the app; the secret (service) key
must never be in the app, the repo or a notebook.

**Size**: a line with its text and one translation is ~0.5 KB; its word timings
~1 KB. A 6-minute video ≈ 120 lines ≈ 200 KB with words, a 1-hour teaching ≈ 2 MB. The
owner's two libraries (~1,300 videos, many an hour long) would pass 500 MB with words in
rows, but fit easily (~10×less) with **word timings as files in object storage** and only
lines in Postgres.

**Sync**: local-first. The local app keeps working offline on SQLite; changes are pushed
as operations (row uid + version + who) and pulled by `updated_at`. This is TEAM.md's
step 5 (row versions, 409 on stale write, op log), now against Postgres instead of the
coordinator's PC. A later move to a paid tier or own server is the same Postgres.

**Tokens for devices**: a member signs in in the app; for a notebook the app issues a
**device key** (like `HF_TOKEN`: pasted into the notebook, revocable, scoped to one
member's teams). A tiny edge function exchanges it for a short-lived token.

A further reason against the hub on the coordinator's PC: a Colab or Kaggle notebook
cannot reach a PC on a home network at all (it would need a tunnel such as Cloudflare
Tunnel, and the PC switched on during every run). A hosted hub is reachable from anywhere.

→ **Recommendation**: Supabase Postgres + Auth + RLS as the team hub; replaces TEAM.md's
"hub mode on the coordinator's PC" (member proxy and LAN tokens no longer needed).

## 3. Where generated audio lives (and Telegram)

Sizes: a take (~5 s, Opus 32 kb/s) ≈ 20 KB; a 6-min episode's takes ≈ 2–3 MB; its mix
(Opus 64 kb/s) ≈ 3 MB; stems (vocals + background, Opus) ≈ 6 MB, FLAC ≈ 60 MB. Stems
can always be rebuilt from the source, so they need not be shared.

| | Free amount | Limits that matter | Fit |
|---|---|---|---|
| **Cloudflare R2** | 10 GB, **free egress**, 1 M writes, 10 M reads/month | S3 API; signed URLs | **best primary** |
| Hugging Face dataset repo | public ~1 TB best effort, private 100 GB | public = anyone can download | good for openly licensed work only |
| Supabase Storage | 1 GB, 5 GB egress | small | fine to start |
| Telegram | "unlimited" | see below | secondary / archive |

Sources: [R2](https://egresscost.com/cloudflare/), [HF storage](https://github.com/huggingface/hub-docs/blob/main/docs/hub/storage-limits.md).

**Telegram as a store**, checked against the [Bot API](https://core.telegram.org/bots/api)
and its [bot terms](https://telegram.org/tos/bot-developers):

- A bot uploads files ≤ **50 MB** and downloads ≤ **20 MB** (a self-hosted Bot API server
  raises both to 2 GB). Takes and mixes of short videos fit; hour-long mixes and FLAC stems
  do not.
- A `file_id` belongs to **one bot**: another bot cannot use it. So shared use needs **one
  system bot**; per-user bots would each only see their own files.
- To download, you need the bot token. A token inside the app or a notebook lets anyone
  who has it control the bot and delete everything. So the token has to sit behind a
  server (the same edge function as §2), which also carries every byte (Supabase edge
  egress 5 GB/month).
- **The bot terms forbid it outright.** §5.2(e): bots must not be used with external
  tools "to develop external services or applications that diverge significantly from the
  intended use cases of Bot Platform (e.g., cloud storage sites)". §6.3: Telegram "may
  delete or make inaccessible whole chats, messages, media and files sent to and from your
  TPA at any time"; §10: breaking the terms can mean a permanent ban. An app that loads its
  audio from a bot is that case: the team could lose its store, and the owner's bot, overnight.
- Group posting limits are ~20 messages/minute: fine for a mix per episode, slow for
  thousands of takes (they would have to be zipped per video).

→ **Recommendation**: R2 as the primary store for generated audio (one bucket per team or
prefix per team; the edge function hands out signed upload/download URLs after checking
the member's token, so no storage keys in clients). Telegram only as an optional "publish
a finished dub to the team channel" action (one system bot owned by the owner), not as the
place the app loads from. Put storage behind one interface (`put`, `get_url`) so either
backend can be added later.

## 4. Recognising "the same video" on another device

A full SHA-256 is the wrong key here:

- On Google Drive for Desktop (streaming mode) hashing a 2 GB file **downloads all of it**.
- Two people downloading the same YouTube video get **different bytes** (format chosen,
  muxing, yt-dlp version), and a local copy may be re-encoded or trimmed.

Three keys, cheapest first:

1. **Link identity** (`youtube:<id>`, or any yt-dlp extractor + id): link sources need no
   file at all; a worker downloads from the link.
2. **Quick hash**: size + SHA-256 of the first and last 4 MB (TEAM.md). The same file copied
   anywhere matches instantly without reading it all.
3. **Audio fingerprint** (Chromaprint, already used for recurring parts in
   `app/fingerprint.py`): the same content in another encoding or with a different start
   matches, and `find_part` gives the **time offset**, so every line's times are shifted
   onto the local copy. Needs only a few minutes of decoded audio.

"Open with my copy": the person picks the file → quick hash → if no match, fingerprint
against the work's sources → confirmed → a `media_copies` row (this device, path, offset).

→ **Recommendation**: link identity + quick hash + fingerprint-with-offset; drop the idea
of full-file SHA-256.

## 5. Sharing progress without a central media store

Already built: `.lbwork` packages (`docs/PACKAGE.md`) with media `none` / `opus` / `flac` /
`ref`, imported by uid, never overwriting manual decisions. Missing:

- **Selective export**: chosen videos of a work, and chosen layers: *work* (transcript,
  cast, translations), *voicings of language X* (takes + chosen take per line), *mix*.
- **Voicing packs** only (no source media): a small zip another member imports onto the
  same work; takes land in their working folder.
- **Auto-detect**: the app scans the working folder's `inbox/` (and the run output folders
  it knows) for `.lbwork` files and offers to import them.
- With §3 in place the same packs go to R2 and appear to the team without passing zips
  around.

## 6. Colab: using it more fully (the image did not arrive; this is from the runner)

Inside one session (already done: downloads on a thread, cross-video batched Whisper,
models loaded once per phase). Still open:

- Overlap CPU work with GPU work in every phase, not only fetch: decode + VAD of the next
  group while Whisper runs; mix/export on a pool while voicing runs (voice → mix per video
  instead of all-voice-then-all-mix).
- Measure on a real T4 (backlog item): Whisper `batch_size`, group size, OmniVoice batch.

Measured in run #1 (6 × ~6 min of 6 Minute English, T4, 2026-09-26):

| Phase | Time | Note |
|---|---|---|
| Whisper large-v3, batched across 5 videos (31 min audio) | 135 s | ~14× real time: not the bottleneck |
| + alignment + speaker detection, same group | 290 s total | |
| Separation (BS-RoFormer), per video | ~305 s | **~0.8× real time: the biggest fixed cost** (31 min for 6 videos) |
| OmniVoice, 439 takes | session cut at 426 | one take per call today |

So the next gains are, in order: (1) **separation** — try a larger `batch_size`, fp16
autocast, or a lighter separator for speech-only content, and cache stems so no video is
separated twice by anyone on the team; (2) **OmniVoice in batches** — the project ships
`omnivoice-infer-batch` and reports RTF ≈ 0.025 (and lower with batch 8 on an H100), while
`worker/lb_worker/tts/omnivoice_gen.py` generates one take at a time; (3) overlap as above.

Across machines, **what is allowed**: Colab's rules forbid **one person using several
accounts to get around usage limits** ([Colab FAQ](https://research.google.com/colaboratory/faq.html);
people have been blocked). Allowed and useful:

- Different **team members** each run their own notebook on different videos (the whole
  point of §2).
- **Kaggle**: ~30 GPU hours/week free, **2 × T4** per session, 12 h sessions
  ([Kaggle](https://www.kaggle.com/docs/efficient-gpu-usage)). The same research runner can
  run there (one worker per GPU, or a 27B LLM split across both).
- Local GPUs through the local worker.

**No two people doing the same video**: with the central DB, a notebook given a team device
key *claims* videos of a run (row with device, lease expiry, heartbeat); a lease that
expires frees the video. The person still starts the notebook by hand; the claim only
stops overlap. Results are written to the central work as each stage finishes.

## 7. LLMs on the free T4: in-context translation, shortening, checking

Facts:

- The T4 has **no bfloat16**. Gemma 3 is unstable in float16 under vLLM on a T4
  ([vLLM forum](https://discuss.vllm.ai/t/gemma3-on-a-t4-gpu/643)); **llama.cpp (GGUF)** or
  transformers + 4-bit (bitsandbytes/Unsloth) are the working routes on Colab
  ([Unsloth 4-bit Gemma 3 12B](https://huggingface.co/unsloth/gemma-3-12b-it-bnb-4bit)).
- A 12B model at 4-bit is ~7–8 GB: **fits a T4** (15 GB) as its own phase (not at the same
  time as OmniVoice). 27B at 4-bit (~16 GB) does not fit one T4; it fits Kaggle's 2 × T4.
- Candidates:
  - **TranslateGemma** 4B / 12B / 27B (Jan 2026), translation-tuned Gemma 3, 55 evaluated
    languages; the 12B beats Gemma 3 27B ([Google](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/),
    [report](https://arxiv.org/pdf/2601.09012)). **Amharic is not among the 55 benchmarked
    languages** (they are WMT24++'s: Swahili and Zulu are the only African ones,
    [WMT24++](https://arxiv.org/abs/2502.12404)). Google staff say the model's template lists
    ~160 more languages as "experimental", with higher hallucination rates
    ([discussion](https://huggingface.co/google/translategemma-27b-it/discussions/1)); the
    template is gated, so whether Amharic is one of them is unchecked. Treat it as a
    candidate to test, not a known-good Amharic translator.
  - **Gemma 4** (Apr 2026: E2B, E4B, 26B MoE, 31B; 140+ languages) — general model for
    rewriting with chapter context; T4 support to be tested.
  - **NLLB-200 3.3B**: covers Amharic, Oromo, Tigrinya; several alternatives per line.
- Checker: **AfriCOMET-QE** ([model](https://huggingface.co/masakhane/africomet-qe-stl))
  scores a translation without a reference for Amharic, Oromo, Somali… The app proposes the
  best candidates; **a person picks** (as the owner asked).

In-context optimisation, per chapter: the LLM sees the chapter's lines (and the
glossary / keep-words), translates or shortens only the lines over their time budget
(from the earlier timing research), and returns 2–4 candidates per line with an estimated
spoken length (Ge'ez characters ≈ syllables). QE + length rank them; the person chooses.

→ **Recommendation**: a translation bake-off like the voice one: NLLB-3.3B vs
TranslateGemma-12B vs Gemma 4 (E4B / 26B MoE) on ~200 already-checked Amharic lines,
scored by AfriCOMET-QE and by ear/eye; run on Colab via llama.cpp. Then the "Fit" step.

## 8. OmniVoice reference length

OmniVoice's guidance: **3–10 s** of reference; longer slows inference and can lower
likeness ([demo](https://k2-fsa-omnivoice.hf.space/), [README](https://github.com/k2-fsa/OmniVoice)).
Today `app/banks.py` gathers ~**12 s** (`TARGET_S`) of lines of up to 12 s each and joins
them, so a bank is often 12–20 s.

Two more points from the README: without `ref_text` OmniVoice transcribes the reference
with Whisper itself (we pass the exact text, which is better, and must stay exact after
trimming); and for standard pronunciation it advises a reference **in the target language**.
So once a character has good Amharic takes, or a person has recorded Amharic lines for it
(§10), an Amharic reference is worth testing against the English one.

→ **Recommendation**: bank = 1–3 clean lines, **6–10 s** total, with the exact
`ref_text`; build 2–3 candidate references per character and keep the one whose takes
score best on the held-out lines (the scoring pass exists). Later: a reference per
emotion or energy level.

## 9. Managing a large piece of work

Import a folder, channel or playlist → pick videos → run stages in a recommended order →
check → re-run stages on some videos. A **work board**: videos × stages, each cell
*pending / running (device) / done / checked / stale / failed*, with:

- a **recommended order**: (1) fetch + transcribe + speakers for all; (2) **cast pass**:
  match voices across all videos, a person confirms the characters once; (3) translate
  (+ Fit), review; (4) voice selected videos; (5) mix and export;
- select cells → run on a device, or prepare for a notebook;
- **stale** when an upstream fix happens (transcript edited → translation and voice of
  those lines marked stale);
- who is working on what (claims, §6).

## 10. Languages with no recogniser, and people registering their own voice

- Unknown language (V2 A7): speech found by VAD, lines created empty with times; people
  type the transcript; translation/voicing continue as usual.
- **Self-registration**: a member records lines in their own voice in the app (V2 C:
  consent + licence), registering as a voice for a character in a target language; their
  recordings are takes like any other and travel as a voicing pack (§5).

## Proposed order

1. **Media identity** (quick hash + fingerprint offset + link identity; `media_copies`).
2. **Supabase team hub**: schema from the local tables, RLS by team, auth in the app,
   device keys, local-first sync with versions. (Replaces TEAM.md steps 2 and 5.)
3. **Selective export / voicing packs / inbox auto-detect** (works without step 2).
4. **Work board** (stages × videos, recommended order, stale, re-run).
5. **Claims + notebook with a team device key** (distributed compute), Kaggle notebook.
6. **R2 media store** behind a storage interface (Telegram publish optional, later).
7. **Translation bake-off on Colab** (NLLB / TranslateGemma / Gemma 4 + AfriCOMET-QE), then
   the Fit step. Can run in parallel with 1–6.
8. **OmniVoice reference 6–10 s** + best-of-N reference choice (small, anytime).

## Open questions for the owner

- Are team works **private to the team**, or may finished works (without source media) be
  public? That decides Hugging Face as a store and the RLS rules.
- One Supabase project for everyone (owner-run), or each team creator makes their own
  (free tier: 2 active projects per account)?
- Rights: dubbed audio of YouTube channels is a derivative work; storing and
  republishing it centrally (R2, Telegram) needs the channel's permission.
