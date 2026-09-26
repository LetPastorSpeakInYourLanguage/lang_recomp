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
