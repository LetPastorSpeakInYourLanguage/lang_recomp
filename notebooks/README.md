# Lang-Bridge notebooks: dub videos anywhere

The heavy part of Lang-Bridge (fetching, transcription, speaker detection, voice separation,
cloned voices, mixing) runs in a **notebook you start yourself**. It works with no app at all:
give it a folder of videos or YouTube links, and it writes the dubbed videos. The Lang-Bridge
app can open the results afterwards, to check, fix and listen.

| File | What |
|---|---|
| [`lang_bridge.ipynb`](lang_bridge.ipynb) | the notebook: settings → get the code → set up this machine → run |
| [`e2e_test.ipynb`](e2e_test.ipynb) | a quick test: two short videos, English → Amharic, pushed to your bucket |
| [`bench_gpu_identity.ipynb`](bench_gpu_identity.ipynb) | certification benches (GPU speed, video identity) |
| [`../worker/lb_worker/research.py`](../worker/lb_worker/research.py) | the same pipeline as Python: `run_folder(...)`, `run_manifest(...)` |

The notebooks are written by `scripts/build_notebook.py`; edit the cells there.

## One notebook, three places

The notebook finds out where it runs by itself:

| Where | What it uses | What you do first |
|---|---|---|
| **Kaggle** | both GPUs of **GPU T4 x2** (voicing and scoring are split between them) | 1. Create → New notebook → File → Import notebook → Link: `https://raw.githubusercontent.com/LetPastorSpeakInYourLanguage/lang_recomp/main/notebooks/lang_bridge.ipynb` 2. Settings (right panel) → Accelerator **GPU T4 x2**, Internet **on** (needs a phone-verified account). 3. Set `STORAGE = bucket` so the results outlive the session. |
| **Colab** | its **T4** | 1. Open `https://colab.research.google.com/github/LetPastorSpeakInYourLanguage/lang_recomp/blob/main/notebooks/lang_bridge.ipynb` 2. Runtime → Change runtime type → **T4 GPU**. 3. File → Save a copy in Drive (keeps your settings). Google Drive connects by itself when a setting points into `/content/drive/…`. |
| **Your own machine** | an NVIDIA GPU if there is one, otherwise the CPU | 1. Python 3.10 or newer, and Jupyter (a fresh virtual environment is best: `python -m venv lb-env`, then `lb-env\Scripts\pip install jupyter` on Windows or `lb-env/bin/pip install jupyter` elsewhere). 2. Open the notebook in Jupyter. PyTorch and ffmpeg are installed if missing. On the CPU, transcripts are fine; voices are slow. |

On Colab and Kaggle the notebook downloads the code from GitHub each time (branch
`CODE_BRANCH`, default `main`), so a saved copy stays up to date. On your own machine, a
notebook opened from inside a Lang-Bridge checkout uses that checkout.

## Settings

Everything is typed in the **Settings** cell, including your token. Nothing is read from
Colab's or Kaggle's secret stores.

| Setting | What |
|---|---|
| `STORAGE` | `folder`: results go to `OUTPUT`. `bucket`: results are pushed to `BUCKET` after every stage (and at the end); `VIDEOS` can then be a folder inside the bucket, downloaded first. |
| `VIDEOS` | a folder of videos (subfolders are works, see [docs/LIBRARY_FOLDERS.md](../docs/LIBRARY_FOLDERS.md); `name.srt` beside a video is used instead of transcribing) |
| `YOUTUBE` | video or playlist links, separated by spaces |
| `LANGUAGE`, `TARGETS` | the videos' language and the languages to dub into, any direction |
| `OUTPUT` | `STORAGE = folder`: where results go (on Colab, a Drive folder so they outlive the session). Empty: `lb-out` in `WORK_DIR` |
| `BUCKET` | a [Hugging Face Storage Bucket](https://huggingface.co/docs/hub/en/storage-buckets), `namespace/name`. Needed for `STORAGE = bucket`; with a folder it is a backup |
| `STAGES`, `DUB_LIMIT`, `LIMIT` | which stages; dub only the first N videos; work on only the first N |
| `ASR_MODELS`, `ALIGNERS` | a recogniser / word aligner per language (`lang=repo`) |
| `CAPTIONS`, `ALIGN_CAPTIONS` | YouTube only: compare YouTube's captions with Whisper, in `report.json` |
| `RUN_FOLDER` | continue a run (`…/runs/<run>`; with a bucket, `runs/<run>`) |
| `HF_TOKEN` | a [Hugging Face token](https://huggingface.co/settings/tokens): read access, plus write access to your bucket. First accept the terms of `pyannote/speaker-diarization-community-1` on huggingface.co |
| `DEVICE` | `auto` (every GPU there is), `cpu`, `1 GPU`, `2 GPUs` |
| `WORK_DIR` | code, models and scratch files. Empty: `/kaggle/working`, `/content`, or `~/lang-bridge` |
| `CODE_BRANCH` | the branch of the code to run (default `main`) |

Then **Run all**. The *Set up this machine* cell prints what will be used (runtime, GPUs,
memory, disk, where results go) and warns about anything missing. For example, on Kaggle
with a single GPU it tells you to choose GPU T4 x2. Stop at any time; run again with the
same settings to continue.

**Keep your token private.** Do not share, publish or commit a notebook with `HF_TOKEN`
filled in. If a token was ever pasted into a shared notebook, revoke it on huggingface.co.
To change `DEVICE` after the pipeline has started, restart the session first.

## What it writes

```
OUTPUT (or the bucket)/
  library/<work>/<video>/     transcript files, stems, takes, mix/<lang>/, export/<name>.<lang>.mp4 (+ .srt)
  runs/<run>/manifest.json    what was asked
  runs/<run>/state.json       how far each video got (this is how it resumes)
  runs/<run>/log.txt          what it printed
  runs/<run>/report.json      timings; captions vs Whisper when asked for
  runs/<run>/results/*.lbwork the work, for the app
  cache/                      downloaded models (kept for next time; never pushed)
```

## Look at it in the app

- **Bucket**: Settings → Folders → add one of kind **Hugging Face bucket** (the bucket's name
  and a folder on your PC to sync into). Home → *Runs on …* → **Sync**: progress shows while
  the run goes, and its results open by themselves; the dubs play from the synced folder.
- **A folder your PC can see** (Drive for Desktop, e.g. `G:\My Drive\lb-out`, or a folder on
  your own machine): Settings → Folders → add it as a **results folder**. Its runs show under
  Home → *Runs on …*, and their results open by themselves.
- Or Home → **Open a shared work** → a `.lbwork` file from `runs/<run>/results/`.

## Languages

`LANGUAGE` is the videos' language and `TARGETS` the languages to dub into, in any direction
(English → Amharic, Amharic → English, Turkish → Oromo…). Speech recognition uses Whisper
large-v3 (large-v3-turbo on a CPU), or a Hugging Face model you name in `ASR_MODELS`. Amharic
uses `badrex/Ethio-ASR-amharic` unless you name another. Word alignment has built-in models
for about 27 languages; add others in `ALIGNERS`.
