# Lang-Bridge notebooks: dub videos anywhere

The heavy part of Lang-Bridge (fetching, transcription, speaker detection, voice separation,
cloned voices, mixing) runs in a **notebook you start yourself**. It works with no app at all:
point it at a team's **working folder** (the workspace) and it dubs the videos in it and the
links recorded in it. A workspace is always needed, even when it starts empty or every video
comes from a link: it keeps the config (`lang-bridge.json`: language, targets, every link
added), the team's own videos, and all results and progress in `.lb/`. Links let teams share
work without copying media to each other: each workspace downloads them itself. The
Lang-Bridge app opens the same folder to check, fix and listen.

| File | What |
|---|---|
| [`lang_bridge.ipynb`](lang_bridge.ipynb) | the notebook: settings → get the code → set up this machine → run |
| [`e2e_test.ipynb`](e2e_test.ipynb) | a quick test: two short videos, English → Amharic, pushed to your bucket |
| [`bench_gpu_identity.ipynb`](bench_gpu_identity.ipynb) | certification benches (GPU speed, video identity) |
| [`../worker/lb_worker/research.py`](../worker/lb_worker/research.py) | the same pipeline as Python: `run_workspace(...)`, `run_manifest(...)` |

The notebooks are written by `scripts/build_notebook.py`; edit the cells there.

## One notebook, three places

The notebook finds out where it runs by itself:

| Where | What it uses | What you do first |
|---|---|---|
| **Kaggle** | both GPUs of **GPU T4 x2** (voicing and scoring are split between them) | 1. Create → New notebook → File → Import notebook → Link: `https://raw.githubusercontent.com/LetPastorSpeakInYourLanguage/lang_recomp/main/notebooks/lang_bridge.ipynb` 2. Settings (right panel) → Accelerator **GPU T4 x2**, Internet **on** (needs a phone-verified account). 3. Set `STORAGE = bucket`: the bucket is the workspace, so it outlives the session. |
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
| `WORKSPACE` | the team's working folder, **always needed** (it may start empty). Its videos in any nesting are the team's own sources (subfolders are works, see [docs/LIBRARY_FOLDERS.md](../docs/LIBRARY_FOLDERS.md); `name.srt` beside a video is used instead of transcribing). On Colab, a Drive folder such as `/content/drive/MyDrive/LangBridge/Preaching`. With `STORAGE = bucket` leave it empty: the workspace is then the bucket, worked on in a local copy |
| `STORAGE` | `folder`: the workspace is `WORKSPACE`. `bucket`: the workspace is `BUCKET`; it is downloaded first and the results are pushed back after every stage (and at the end) |
| `BUCKET` | a [Hugging Face Storage Bucket](https://huggingface.co/docs/hub/en/storage-buckets), `namespace/name`, for `STORAGE = bucket` |
| `LINKS` | links to add: videos, playlists or channels (YouTube or any site yt-dlp supports), separated by spaces, or a `.txt` file with one link per line. They are recorded in the workspace's `lang-bridge.json` and downloaded into its `.lb/`; links recorded before are always included |
| `LANGUAGE`, `TARGETS` | the videos' language (it must match an existing workspace's; if not, the run stops and says so) and the languages to dub into. Targets not in the workspace's list are done too, with a warning |
| `STAGES`, `DUB_LIMIT`, `LIMIT` | which stages; dub only the first N videos; work on only the first N |
| `ASR_MODELS`, `ALIGNERS` | a recogniser / word aligner per language (`lang=repo`) |
| `VOICE` | `native` (a native speaker's voice, then the character's voice with Seed-VC; decision 46) or `clone` |
| `SHORTEN_WITH_LLM`, `LLM_MODEL` | on (the default): lines whose translation is too long for its place get shorter English from a local Gemma 4, translated again ([docs/SHORTEN.md](../docs/SHORTEN.md)); `auto` = E4B on a GPU, E2B on a CPU |
| `CAPTIONS`, `ALIGN_CAPTIONS` | YouTube only: compare YouTube's captions with Whisper, in `report.json` |
| `RUN_FOLDER` | continue a run: `runs/<run>` (in the workspace's `.lb/`), or a full path |
| `HF_TOKEN` | a [Hugging Face token](https://huggingface.co/settings/tokens): read access, plus write access to your bucket. First accept the terms of `pyannote/speaker-diarization-community-1` on huggingface.co |
| `YT_COOKIES` | only if YouTube refuses the machine (below): a `cookies.txt` file, e.g. on Drive |
| `DEVICE` | `auto` (every GPU there is), `cpu`, `1 GPU`, `2 GPUs` |
| `WORK_DIR` | code, models and scratch files. Empty: `/kaggle/working`, `/content`, or `~/lang-bridge` |
| `CODE_BRANCH` | the branch of the code to run (default `main`) |

### When YouTube says "Sign in to confirm you're not a bot"

YouTube often refuses Colab's and Kaggle's addresses. Either put the videos in the workspace
folder yourself, or give the notebook your browser's YouTube cookies:

1. Use a spare Google account if you can: YouTube may flag an account used from a server.
2. Open a **private/incognito window**, sign in to YouTube there, then open `https://www.youtube.com/robots.txt` in the same tab.
3. Export the cookies with a browser extension such as **Get cookies.txt LOCALLY** (Netscape format) and save the file as `cookies.txt`.
4. **Close the private window** without signing out (signing out or browsing on cancels the cookies).
5. Upload `cookies.txt` to your Drive, e.g. `MyDrive/LangBridge/cookies.txt`, and set
   `YT_COOKIES = "/content/drive/MyDrive/LangBridge/cookies.txt"`.

The file lets anyone use that YouTube session: never share it or put it in a workspace other
people sync. The notebook reads it and never changes it (yt-dlp gets a private copy).

Then **Run all**. The *Set up this machine* cell prints what will be used (runtime, GPUs,
memory, disk, where results go) and warns about anything missing. For example, on Kaggle
with a single GPU it tells you to choose GPU T4 x2. Stop at any time; run again with the
same settings to continue.

**Keep your token private.** Do not share, publish or commit a notebook with `HF_TOKEN`
filled in. If a token was ever pasted into a shared notebook, revoke it on huggingface.co.
To change `DEVICE` after the pipeline has started, restart the session first.

## What it writes

```
WORKSPACE (or the bucket)/
  lang-bridge.json                language, targets, every link added (the app reads and edits it)
  <the team's videos, any nesting>
  .lb/
    library/<work>/<video>/       downloaded link videos, transcript files, stems, takes, mix/<lang>/,
                                  export/<name>.<lang>.mp4 (+ .srt)
    runs/<run>/manifest.json      what was asked
    runs/<run>/state.json         how far each video got (this is how it resumes)
    runs/<run>/log.txt            what it printed
    runs/<run>/report.json        timings; captions vs Whisper when asked for
    runs/<run>/results/*.lbwork   the work, for the app
    cache/                        downloaded models (kept for next time; never pushed)
```

## Look at it in the app

- **Bucket**: Settings → Folders → add one of kind **Hugging Face bucket** (the bucket's name
  and a folder on your PC to sync into). Home → *Runs on …* → **Sync**: progress shows while
  the run goes, and its results open by themselves; the dubs play from the synced folder.
- **A workspace your PC can see** (Drive for Desktop, e.g. `G:\My Drive\LangBridge\Preaching`,
  or a folder on your own machine): Settings → Folders → add it as a **results folder**. Its runs show under
  Home → *Runs on …*, and their results open by themselves.
- Or Home → **Open a shared work** → a `.lbwork` file from `.lb/runs/<run>/results/`.

## Languages

`LANGUAGE` is the videos' language and `TARGETS` the languages to dub into, in any direction
(English → Amharic, Amharic → English, Turkish → Oromo…). Speech recognition uses Whisper
large-v3 (large-v3-turbo on a CPU), or a Hugging Face model you name in `ASR_MODELS`. Amharic
uses `badrex/Ethio-ASR-amharic` unless you name another. Word alignment has built-in models
for about 27 languages; add others in `ALIGNERS`.
