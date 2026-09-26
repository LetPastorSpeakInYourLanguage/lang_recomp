# The work package (`.lbwork`)

A published work — a series, or a standalone video's own work — travels between teams
as one zip file. The receiving team gets everything that does not depend on a target
language, plus the languages the sender chose to include, and adds its own language
without redoing the transcription, the cast or the library. Built by `app/package.py`.

## Rules

- **Three layers.** *Work* (language-neutral), *languages* (one folder per target
  language, only those chosen at export) and *local* state, which never travels: file
  paths, job ids and job folders, workers, tasks, loaded-job bookkeeping, app settings.
- **Identity is the `uid`.** Works, sources, characters, clips and collections keep the
  uid they were born with, in every library. Local ids (slugs, integer clip ids) are
  re-made on import; references inside the package always use uids (and a source's line
  ids, which belong to that source's transcript).
- **Manual truth wins on import.** Importing a work that already exists here (same uid)
  adds what is missing and fills blanks. It never overwrites a reviewed line, a person's
  translation or a confirmed/rejected link; disagreements are listed in the import
  report instead.
- **Settings are suggestions.** A language's aligner is reported, not written into the
  receiver's settings (their machine, their choice).

## Layout

```
work.json                         format, version, exported_at, note, media mode,
                                  languages included, the work: uid, name, kind, src_lang,
                                  targets, feed_url, rights, settings
sources/<source uid>/
  source.json                     uid, name, origin (url, YouTube id, published), clip
                                  range, duration, position, src_lang, max_speakers, mix
                                  settings, chapter_seq
  lines.json                      [{id, start, end, speaker, text, words, reviewed, mode}]
  chapters.json                   [{id, start, title}]
  speakers.json                   {centroids: {label: [256 floats]}, appearances:
                                  [{label, character_uid, status, score, talk_s}]}
  media/                          (media "opus" or "flac") audio, vocals, background
cast.json                         [{uid, name, gender, role, notes, color, important, auto,
                                  names {lang: name} for included languages,
                                  bank [{source_uid, line_id, start, end, text, role, manual, file}]}]
cast/<character uid>/<file>.flac  voice-bank lines (always included: a character keeps
                                  its voice without the media)
library.json                      clips [{uid, source_uid, title, kind, note, created,
                                  revisions [{rev, segments [{source_uid, start, end}]}],
                                  occurrences [{source_uid, start, end, score, status}]}],
                                  collections [{uid, name, clips [clip uids]}]
languages/<lang>/
  translations.json               {source uid: [{line_id, text, locked, provenance}]}
  profile.json                    {aligner, rates {source uid: syllables/s}}
  takes.json + takes/…            (optional) the chosen take of each line, with scores
```

`format` is `"lang-bridge.work"`, `version` 1. A reader refuses a newer major version.

## Media modes

| mode | size (6 min video) | on import |
|---|---|---|
| `none` | kilobytes | video and audio are fetched again from the origin (same clip range); voices are separated again on a worker |
| `opus` (default) | ~6 MB | stems placed as they are; only the video is fetched (for Transcript) |
| `flac` | ~60 MB | lossless stems |

Line timings stay valid on re-fetch because the clip range and the origin are the same.
