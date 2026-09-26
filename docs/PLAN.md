# Lang-Bridge v2 — build plan (approved 2026-09-26)

Status markers: ✅ done · 🔜 next · ⬜ not started. Current state: [STATE.md](STATE.md).

## Context

Lang-Bridge v1 is a single-person, single-video dubbing desktop tool (EN→Amharic tested):
separate → transcribe → align → diarize → review → translate → voice (cloned, scored takes) →
fit/mix → MP4, with GPU work on job-folder workers (Colab via Drive, or the PC's Intel Arc).

The owner's original brief always had a second half: a **community** that works chapter by
chapter, **transcribes unknown source languages, translates into low-resource languages, lends
its own voices** to characters, and eventually trains models for those languages. And the
sibling project **recomposer_v2** (`D:\py_self\recomposer_v2`) has authored **journeys**
(stages with roles/intent → ordered slots of moments, alternates, per-slot advance; suggestions
offered with reasons, never auto-selected — its ADR-13) that should work on this dubbed,
multi-language material.

**Owner decisions:**
- Backbone: **self-hosted community server** (FastAPI + Postgres, accounts, teams, roles,
  browser UI for contributors). The desktop stays the power tool and syncs to it.
- **Invited teams first** (role-based review); open sign-up later.
- Journeys **built inside Lang-Bridge** (port recomposer_v2's model), in any language.
- Human voices, all three uses: recording **as the dub**, recording **driving the cloned voice**
  (keep delivery, swap timbre), and **consented open training data**. Recorded
  **chapter-grouped**: all of a character's lines in a chapter in one guided session.

## Architecture

```
 browser contributors ──► community server (server/): FastAPI · Postgres · object store · Caddy
                           teams · roles · series · sources · chapters · lines · languages
                           tasks/leases · comments · reviews · recordings · consents · op log
                                  ▲ sync (push/pull ops)          ▲ HTTP job queue (later)
 desktop app (app/, web/) ── GPU workers (Colab / Arc) via job folders
```

Server is the source of truth for shared projects; the desktop keeps a local SQLite mirror
and works offline. One React codebase (`web/`) in desktop and community modes. **Manual truth
wins in storage**: every row has `provenance ∈ machine|human|reviewed`; machine writes never
overwrite human/reviewed ones (generalises `keep_reviewed`/`carry_over` in `app/project.py`
and `set_translation`).

## Phase A — multi-language & multi-source foundations (desktop)

1. ✅ **Languages as data** — `translations` table, many targets per project, lang on every API,
   per-language takes/rates/mix/export, one-shot migration of `sentences.am`.
2. ✅ **Length per script** — `app/translate/length.py`, rates calibrated per language.
3. ✅ **Chapters as entities** — `chapters(project_id, id, start, title, updated)` replacing
   the `chapter_break` flag (`app/chapters.py`); a line belongs to the chapter containing its
   start; index/end are derived; ids never reused. Chapters are the unit of assignment,
   translation context, recording sessions and coarse journey moments. Migrated from flags;
   `C` key kept; titles editable in Transcript. `source_id` arrives with A4. No chapter
   `status` column: per-language task status lives on chapter tasks (Phase B).
4. ✅ **Series, the team library and reusable parts** (approved 2026-09-26) — see
   [A4 in detail](#a4-in-detail) below. Still to do: a real series whose videos share an
   identical intro (6 Minute English's YouTube uploads turned out not to — their stings vary).
5. ✅ **Characters belong to the work; works travel** (approved 2026-09-26) — see
   [A5 in detail](#a5-in-detail).
6. ⬜ **Per-language keep-words** (`app/interjections.py`).
7. ⬜ **Unknown-language path** — VAD-only segmentation (`asr` stage `params.transcribe=false`)
   → empty lines for manual transcription; optional MMS/Omnilingual drafts (provenance machine).

### A4 in detail

Material comes in families: TV series, podcast/YouTube **channels**, one **speaker's**
talks/teachings, **education** channels, **news** with recurring anchors. Families repeat
themselves (a sermon's 30 s opener, a show's 15 s intro, a sign-off), and teams keep
reusable resources. Resources:

| Resource | What | Used by |
|---|---|---|
| **Clip** | saved span of a source (snapped to lines), title, note, tags | library, collections, journeys |
| **Recurring part** | clip of kind intro/opener/outro/jingle/recurring + its occurrences in other sources | dubbing: transcribed, translated, voiced **once**, reused everywhere it occurs |
| **Collection** | flat, multi-membership folder of clips (later stage presets, journeys) | team library |
| **Stage preset** | recomposer's reusable revisioned stage (copy-on-insert) | Phase D; collections can already hold it |

Model:
```
series(id, name, kind, feed_url, src_lang, targets JSON, settings JSON, created)
  kind ∈ show | channel | speaker | course | news | other   (wording + defaults only)
projects  + series_id NULL, position REAL, origin_id TEXT (YouTube id), published TEXT
clips(id, series_id, source_id, title, kind, note, created, deleted)
clip_revisions(clip_id, rev, segments JSON [{source_id,start,end}], created)  ← recomposer cut_revision
clip_occurrences(clip_id, source_id, start, end, offset, score, status proposed|confirmed|rejected, updated)
collections(id, name, created, deleted)
collection_items(collection_id, item_type clip|stage_preset, item_id, added)
```
Rules: occurrences are **proposals until a person confirms** (nothing auto-applied); ids never
reused; archiving a collection never deletes clips; clip edits add a revision.

As built: `app/series.py`, `app/feeds.py`, `app/library.py`, `app/fingerprint.py`,
`app/recurring.py`; screens Library (Home), Series, Clips & collections; Transcript range
select + **S**. Occurrence rows got their own id (`clip_occurrences.id`); a clip's `offset`
is derived (occurrence start − origin start). `python -m app --data <dir>` +
`scripts/make_sandbox.py` give a throwaway library with a synthetic three-episode show.

Steps (branch `feat/series`): (1) series + sources, Library home, series defaults for new
sources; (2) follow a channel/playlist — `yt-dlp --flat-playlist -J`, tick videos, import one
at a time, dedupe by `origin_id`, no background polling; (3) clips (Transcript range → **S**)
and collections; (4) `app/fingerprint.py` — ffmpeg Chromaprint (`-f chromaprint -fp_format
raw`), sliding Hamming match, pairwise "find repeating parts" (Jellyfin Intro Skipper method)
→ proposed occurrences, confirm UI; (5) reuse in dubbing — lines inside a confirmed occurrence
are **linked**, skipped by Translate/Voice, and `mix.render` places the origin source's chosen
takes shifted by the offset; (6) docs.

### A5 in detail

Three layers: **work** (language-neutral, travels), **language** (per target, travels when
chosen), **local** (paths, jobs, workers, settings — never travels). Every portable row has a
`uid`. Built:
- Every source belongs to a work; a standalone video has a hidden `series(kind='single')`.
- `cast` (work-level characters: name, gender, role, notes, important, per-language names in
  `cast_names`), `appearances(source_id, label, character_uid, status proposed|confirmed,
  score, talk_s)`. Voice matching by pyannote centroids (`MATCH = 0.45`; different voices
  ≈0.1): proposals only. `auto` characters (never edited) disappear when unused.
- `cast_bank`: a character's voice bank cut from all its confirmed appearances into
  `data/works/<work uid>/cast/<char uid>/`; voice jobs ship it as files (worker accepts
  `bank_file`/`heldout_files`, spans still work).
- Cast screen, Characters screen proposals, Share screen, "Open a shared work" on Home.
- `.lbwork` packages (`app/package.py`, format in [PACKAGE.md](PACKAGE.md)); import by uid,
  manual truth, re-fetch of missing media (separation only, never re-transcription).
- Translate shows another language as a reference (pivot).

## Phase B — community server MVP (invited teams) ⬜

`server/`: FastAPI, SQLAlchemy 2 + Alembic, Postgres 16, argon2, httpOnly session cookie +
CSRF, object store (disk default, S3/R2 option), proxies (Opus 32 kbps, 360p), docker compose
with Caddy TLS. Users, teams, multi-role memberships
`owner · lead · transcriber · translator · voice · reviewer`, single-use expiring **invite
links**, team-private series. Model: series, sources, chapters, lines (+revisions),
translations per language, characters/appearances, **chapter tasks** `(chapter, lang, kind ∈
transcribe|translate|voice(character)|review, assignee, status todo→doing→review→done, lease)`,
comments on lines, reviews, **operation log** (event_time + ingest_time), per-row `version`
(409 on stale write). Desktop "Share to team" push + pull through manual-truth rules. Browser
UI: dashboard, **chapter board** (language × task), Transcribe/Translate reused from
`web/src/screens/` with an API-base switch, presence, comments, review queue. Finishing a
source transcript unlocks translation into any language a team adds.

## Phase C — human voices, chapter-grouped ⬜

Browser **recording session** (MediaRecorder 48 kHz): chapter + character + language;
teleprompter through all that character's lines in one continuous take (original audition,
slot timing bar, `Space` = next line, retake marks). Worker stage **`split_session`**: VAD +
the language's forced aligner (`stages/align.py`) → one clip per line, fallback to Space marks;
narrator reviews cuts. Takes gain `kind ∈ tts | human | human→clone`; stage **`convert`**
(Seed-VC / OmniVoice VC) keeps narrator delivery, applies the character's timbre; same scores
for all kinds. **Consent & licence** per recording (dub-only or dub + dataset CC-BY-4.0/CC0,
revocable for future exports). **Dataset export** (HF datasets style, consenting + reviewed
only). Later: Colab training stage per language when enough hours exist.

## Phase D — journeys across languages (recomposer inside Lang-Bridge) ⬜

Port from recomposer_v2 (model and rules, not the app): `app/journeys/contract.py` (Slot,
Stage, StageIntent role `priming|triggering|immersion|return|other`, StagePresentation),
`app/journeys/store.py`, `app/session/plan.py` (append-only plan revisions),
`app/study/emotions.py` (56-term vocabulary), `app/cuts/boundaries.py` (snapping). Moments =
spans snapped to lines or whole chapters, resolving per language to the dub mix slice,
original audio and captions. Journey editor (stages → slots → moments, alternates, advance,
presentation). **Language-crossing playback** (play language; fallback to original + subtitles,
marked). "Maximise journeys" = **explained suggestions** (role/emotion intent, labels,
continuity, length) over bounded authored choices; nothing auto-placed. Export journey MP4 per
language; share within team.

## Phase E — hardening & scale ⬜

Backups, rate limits, audit views, open sign-up with review-gated first contributions, HTTP
job queue replacing Drive folders, accessibility, server deployment docs, security review.

## First vertical slice (target)

Two episodes of one series; team of three (lead, translator, voice); one extra language added
manually; characters linked across episodes; one chapter recorded by a person and used both
directly and converted; one journey from moments of both episodes exported in two languages.

## Verification

Per phase tests (pytest suite stays green) — migrations round-trip the camille project;
cross-source matching; server permissions matrix, invites, 409s, leases, manual-truth
rejection; sync convergence; `split_session` on a synthetic recording; consent revocation in
exports; ported journey contract tests; two-language journey render with fallback marking.
End to end in the browser pane + ffprobe on outputs. Security review before public deploy.
