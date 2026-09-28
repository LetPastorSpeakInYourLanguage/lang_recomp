# Lang-Bridge on Colab (or any GPU machine)

The heavy part of Lang-Bridge — transcription, speaker detection, voice separation,
cloned voices, mixing — runs as a **research notebook** you start yourself, on your own
videos, at your own discretion. It is not a background service of the app: nobody's
machine picks up work on its own. The app only reads what the notebook writes.

| File | What |
|---|---|
| [`lang_bridge.ipynb`](lang_bridge.ipynb) | the notebook: settings → get the code → run |
| [`../worker/lb_worker/research.py`](../worker/lb_worker/research.py) | the same thing as Python: `run_folder(...)`, `run_manifest(...)` (servers, scripts) |

## Put it in your own Google Drive / Colab

Either:

- **Open it from GitHub** (always the latest): in Colab, *File → Open notebook → GitHub*,
  paste `LetPastorSpeakInYourLanguage/lang_recomp`, pick `colab/lang_bridge.ipynb`.
  Or open `https://colab.research.google.com/github/LetPastorSpeakInYourLanguage/lang_recomp/blob/main/colab/lang_bridge.ipynb`.
  Then *File → Save a copy in Drive* to keep your settings.
- **Upload it**: download `lang_bridge.ipynb` from GitHub and upload it to
  `My Drive/Colab Notebooks/` (drag it into drive.google.com), then open it with Colab.

The notebook fetches the code from GitHub each time it runs, so a copy in your Drive
stays up to date; only your settings live in the copy.

## Run it

1. *Runtime → Change runtime type* → a GPU (T4 is enough).
2. Mount Google Drive yourself if your videos are there (folder icon → *Mount Drive*).
3. Fill in **Settings**:
   - `VIDEOS` — a folder of videos (see [docs/LIBRARY_FOLDERS.md](../docs/LIBRARY_FOLDERS.md):
     subfolders are works; `name.srt` beside a video is used instead of transcribing), and/or
     `YOUTUBE` — video or playlist links;
   - `OUTPUT` — where results go (on your Drive, so they outlive the session);
   - `LANGUAGE`, `TARGETS`, `STAGES`, `DUB_LIMIT`, `LIMIT`;
   - `CAPTIONS` / `ALIGN_CAPTIONS` — YouTube only: compare YouTube's captions (raw and
     force-aligned) with Whisper, reported in `report.json`;
   - `HF_TOKEN` — a [Hugging Face token](https://huggingface.co/settings/tokens) (read); first accept the terms of
     `pyannote/speaker-diarization-community-1` on huggingface.co.
4. *Runtime → Run all*. Progress prints as it goes. Stop whenever; run again with the same
   settings to continue.

**Keep your token private**: do not share, publish or commit a notebook with `HF_TOKEN`
filled in. If a token was ever pasted into a shared notebook, revoke it on huggingface.co.

## What it writes

```
OUTPUT/
  library/<work>/<video>/     transcript files, stems, takes, mix/<lang>/, export/<name>.<lang>.mp4 (+ .srt)
  runs/<run>/manifest.json    what was asked
  runs/<run>/state.json       how far each video got (this is how it resumes)
  runs/<run>/report.json      timings; captions vs Whisper when asked
  runs/<run>/results/*.lbwork the work, for the app
  cache/                      downloaded models (kept for next time)
```

## On Kaggle, with a Hugging Face bucket (no Google Drive)

1. Kaggle → Create → New notebook → File → Import notebook → Link:
   `https://raw.githubusercontent.com/LetPastorSpeakInYourLanguage/lang_recomp/main/colab/lang_bridge.ipynb`.
2. Settings → Accelerator **GPU T4 ×2**, Internet **on** (needs a phone-verified account).
3. Add-ons → Secrets → add `HF_TOKEN` (a Hugging Face token that can **write** to your bucket
   and read gated models) and tick it for this notebook. Colab: the key icon, same name.
4. On huggingface.co create a Storage Bucket (e.g. `your-org/lang-bridge-runs`); put its name in
   `BUCKET`. Results are pushed there after every stage and at the end.
5. In the app: Settings → Folders → add one, **HF bucket**, with the bucket name and a folder on
   this PC to sync into. Home → *Runs on …* → **Sync**: the run's progress shows (it pulls every
   minute while the run is going) and its results open by themselves; the dubs play from there.

A run that stops can continue anywhere: set `RUN_FOLDER` to `…/runs/<run>` (the notebook's
output folder) with the same `BUCKET`; it is pulled from the bucket first.

## Languages

`LANGUAGE` is the videos' language, `TARGETS` the languages to dub into — any direction
(English → Amharic, Amharic → English, Turkish → Oromo…). Speech recognition: Whisper
large-v3 for the languages it handles well; name a Hugging Face model for any language in
`ASR_MODELS` (`lang=repo`; CTC models such as wav2vec2/MMS or Whisper fine-tunes). Amharic
uses `badrex/Ethio-ASR-amharic` unless told otherwise. Word alignment has built-in models for
~27 languages (e.g. Turkish `mpoyraz/wav2vec2-xls-r-300m-cv7-turkish`); add others in `ALIGNERS`.

## Look at it in the app

Home → **Open a shared work** → the `.lbwork` path as your PC sees it (for Drive:
`G:\My Drive\LangBridge-output\runs\…\results\….lbwork`). Media stay in `OUTPUT`: the
app plays the videos and the dubs from there. Check and fix speakers, lines and
translations in the app; the next run can start from your corrections (below).

## Starting from the app's work

The app can prepare a run for chosen videos (Run panel, device = a Drive folder): it
writes a run folder with the work as it is in the app, your corrections included. Put
that folder's path in `RUN_FOLDER` and run the notebook.

## Teams

Each member runs the notebook on the videos they have, into their own output folder,
and shares the `.lbwork` results; they import into the team's app (by uid, never
overwriting what people decided). Coordinated metadata across members is the team
hub ([docs/TEAM.md](../docs/TEAM.md)).
