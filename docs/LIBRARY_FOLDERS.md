# Library folders — how to upload videos for Lang-Bridge

A **library** is one folder a team pushes videos into. Put it where the machine that will
process it can read it:

- **Google Drive** (processed on Colab): anywhere in the same Drive as the `LangBridge`
  folder, e.g. `My Drive/Libraries/<team library>/`.
- **This PC / an external disk** (processed by the local worker): any folder, e.g.
  `E:\Libraries\<team library>\`.

Register it once in the app (Library → Add a library folder), then **Scan** after each
upload. Scanning reads only names (never the videos), so it takes seconds; everything is
playable in the app straight away, from where it is. Lang-Bridge never writes into a
library folder — its results go to `LangBridge/library/…` on the same device.

## Layout

```
<team library>/
  library.json                        (optional) defaults for every work below
  <work>/                             one folder = one work: a series, teaching series,
    work.json                         (optional)  podcast, course, show, conference…
    01 - <episode title>.mp4
    01 - <episode title>.srt          (optional) subtitles in the spoken language
    01 - <episode title>.am.srt       (optional) subtitles someone made in another language
    02 - <episode title>.mp4
    Season 2/                         (optional) a group: season, volume, day, part…
      01 - <episode title>.mp4
  _Standalone/                        single videos that belong to no work
    <title>.mp4                       each becomes a work of its own
```

- **Order** comes from the leading number: `01`, `02`, … `10` (use `001` for 100+).
- **Titles** are the file name without the number prefix rules: write them as people should
  read them (`03 - Walking in the Spirit.mp4`). Avoid `? : " / \ | * < >`.
- **Versions in another language** (a dub or interpretation someone already made): add the
  language code in square brackets, `01 - Walking in the Spirit [hi].mp4`.
- **Subtitles**: SRT (UTF-8), same name as the video. `name.srt` is the spoken language and
  is used as the transcript (no speech recognition needed); `name.<code>.srt` (`am`, `om`,
  `hi`, …) is kept as a translation to start from.
- Folders that do not follow this still load: the top folder is the work, deeper folders
  become groups, files at the top are standalone.

## work.json / library.json (optional)

```json
{
  "title": "The Faith Series",
  "kind": "speaker",
  "language": "en",
  "targets": ["am", "om"],
  "speakers": ["Pastor Chris Oyakhilome"]
}
```

`kind`: `speaker` (one person's talks, sermons, teachings), `show`, `channel` (podcast),
`course`, `news`, `other`. `speakers` names the people who are always there: their voice is
learned once and recognised in every video. `library.json` holds the same fields as
defaults for all works.

## Recommended formats (small to push, fast to process, plays from Drive)

| | Recommendation | Why |
|---|---|---|
| Video | **MP4, H.264, ≤ 720p, `+faststart`**, ~CRF 26 (≈ 0.5–0.7 GB per hour) | plays in the app from Drive without downloading it all; 720p is plenty to review and to export the dub |
| Audio | AAC 128 kbps, 44.1/48 kHz, in the MP4 | speech models need 16 kHz; more is not better |
| Audio-only (podcasts) | `.m4a` (AAC 96–128 kbps) or `.mp3` | no video to carry |
| Subtitles | `.srt`, UTF-8 | read directly as the transcript |

One command turns any file into that:

```
ffmpeg -i input.mov -vf "scale=-2:'min(720,ih)'" -c:v libx264 -preset medium -crf 26 -c:a aac -b:a 128k -movflags +faststart "01 - Title.mp4"
```

## What teams then do

1. **The first team** (the work's spoken language) runs the pipeline end to end or stage by
   stage, and checks the forward metadata once: who speaks (usually one teacher, sometimes
   an interpreter or a host), lines, chapters. A speaker named in `work.json` is recognised
   across every video and every work of the library.
2. **Every other team** only runs *translate → voice → mix* for its own language: the
   transcript, speakers, voice banks and chapters are already there.
