# Decisions (owner-approved unless marked)

| # | Decision | Why / note |
|---|---|---|
| 1 | Target language first: **Amharic**; any language must work | Owner's community is Ethiopian; low-resource languages are the point |
| 2 | Desktop = pywebview + FastAPI + React/Vite/Tailwind; UI styled after `D:\py_yaddessa\lab_resource_v2` (IBM Plex, CSS-var tokens, dense, lucide, no emoji) | Compact, reuses Python for media/ML |
| 3 | GPU work via **job folders** (one writer per file); workers: Colab (Drive) and this PC (CPU + Intel Arc XPU) | No always-on server needed; resumable |
| 4 | Colab notebook is **passive**: drain the queue, release the GPU; never poll | Google terminated a polling session |
| 5 | Owner leans **local**: Arc GPU for separation/alignment/voicing, CPU for ASR/diarization | Colab limits; measured speeds acceptable |
| 6 | ASR: faster-whisper + Silero VAD ≤30 s chunks (whisperX method), plus a separate **align** stage with **any HF CTC model per language** (not whisperX's fixed list) | whisperX pins old pyannote; owner wants open aligners for low-resource languages |
| 7 | Speaker boundary words: aligned times + rule "a stray short word joins the sentence it grammatically belongs to; one-word replies keep their speaker" | Fixed every boundary on the test clip |
| 8 | Voice engine: **OmniVoice**, 16 diffusion steps, **1.4× speed**, 2 takes/line, auto-scored (likeness, back-transcription CER, fit) | Owner approved 16/1.4× by ear; bake-off winner |
| 9 | Short interjections ("wow", "ehm", "yeah", "oh nice", "ok") **keep the original voice** by default; per-line Dub/Keep switch; editable word list | Owner request |
| 10 | **Reviewed lines are locked**: reloads never change them; unreviewed lines carry work over by time overlap | Owner reviews/merges lines; reloads must not undo that |
| 11 | Translation: Google's public endpoint, batched with context and ID markers; LLM engine later | No API key yet |
| 12 | Languages are data (`translations` table); machine never overwrites people unless forced | Foundation for community + multi-language |
| 13 | Community: **self-hosted server**, **invited teams first**, chapter-level collaboration | See PLAN.md |
| 14 | Journeys built **inside Lang-Bridge** from recomposer_v2's authored model; suggestions offered, never applied | Owner decision; recomposer ADR-13 |
| 15 | Human voices: as dub, as driver for cloned voice, and as consented open data; recorded **chapter-grouped** | Owner decision |
| 16 | Workflow: feature branches, step-by-step commits each verified alone, merge per phase, full build pass | Owner request |
| 17 | Repo public, MIT; `data/`, test media and private notes never committed | Owner request |
| 18 | Never spawn subagents (owner's global rule) | `~/.claude/CLAUDE.md` |
| 19 | Chapters are **time spans** with stable, never-reused ids; a line belongs to the chapter containing its start; index/end derived, not stored | Merge/split/reload never rewrite membership; community tasks can point at chapter ids |
| 20 | Merging across a chapter start moves the chapter to the next line; a chapter left with no lines is dropped | The old flag silently joined two whole chapters |
| 21 | **Series** group sources (show, channel, speaker, course, news, other); kind changes wording and defaults only; new sources take the series' languages and settings; removing a series keeps its videos | One model for every family of material the owner named |
| 22 | Channels/playlists are **listed, never polled**: `yt-dlp --flat-playlist`, a person ticks videos; imports run **one at a time** (FIFO) | Slow link; YouTube etiquette; control stays with people |
| 23 | **Clips** (saved spans, revisioned like recomposer cuts) and **collections** (flat, multi-membership, archive never deletes) are the team library; collections can later hold stage presets | Recomposer's accepted model, reused so Phase D ports cleanly |
| 24 | A **recurring part** (intro, opener, outro, jingle, recurring) is a clip kind; it is **dubbed once at its origin** and reused where an occurrence is **confirmed** | Owner: "saved once"; fingerprint hits are proposals, people confirm (ADR-13 spirit) |
| 25 | Occurrences found by **Chromaprint** (ffmpeg built-in) — sliding match for a known part, exact-value shift votes + frame check for discovery (Jellyfin Intro Skipper method) | No new dependency; fast (~8 s per hour of audio); proven method |
| 26 | Lines only **fully inside** a confirmed occurrence are linked; partial ones are dubbed normally | Never drop words at a boundary |
| 27 | **Characters belong to the work**, not a video; a video's diarizer labels are *appearances* of them; voice matches across videos are **proposals** a person confirms | Owner: characters independent of media; manual truth |
| 28 | **Three layers**: work (language-neutral), language (per target), local (never shared); every portable row has a permanent **uid** | Owner: a published work must transfer to another team for another language |
| 29 | A standalone video has its own hidden single-source work (`kind='single'`) | One model for cast, clips and sharing; the UI still says "standalone" |
| 30 | A **voice bank belongs to the character**: lines cut from all its confirmed appearances into files kept with the work; shipped to voice jobs as files | Better clones across episodes; the voice survives without the media and travels |
| 31 | Works travel as **`.lbwork`** zips; import matches by uid and never overwrites people's decisions; missing media are re-fetched from the origin and only separated, never re-transcribed | Portable, idempotent, safe |
| 33 | **Nothing runs or downloads on the owner's PC** for batch work: Colab fetches videos into Drive, the app reads/plays them from G: | Owner rule (2026-09-26) |
| 34 | Whole channels run as **`bulk` batches** (~20 videos/job, models loaded once, per-video checkpoints); **no separation** in batches — only for videos being dubbed | Drive overhead, T4 time, resumability |
| 32 | Package media default: voice stems as Opus (none / FLAC optional); settings (aligners) are reported, never written on import | Size vs. re-separation cost; the receiver's machine is theirs |
