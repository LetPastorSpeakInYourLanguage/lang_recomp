# Lang-Bridge

A desktop dubbing tool: take a video in one language, get it back dubbed in another,
**in each speaker's own cloned voice**, with a person checking every step.
Built and tested for **English → Amharic**; the pipeline is language-agnostic wherever
models exist (transcription, alignment and voice models are chosen per language).

```
video ─► separate voice / background ─► transcribe ─► align words ─► who speaks when
      ─► you confirm characters, fix the transcript, set chapters
      ─► translate (chapter by chapter) ─► you edit the translation
      ─► voice every line in its speaker's cloned voice (2 takes, auto-scored) ─► you pick
      ─► fit to the original timing, mix over the background ─► MP4 with dub + subtitles
```

The heavy steps (separation, transcription, alignment, speaker detection, voicing)
run on a **worker**. You can use either or both:

| Worker | Hardware | Good for |
|---|---|---|
| **Google Colab** (free T4 GPU) via **Google Drive** | Google's GPU | everything, fastest; no local GPU needed |
| **This PC** (`Local-Worker.cmd`) | CPU, or an **Intel Arc** GPU via PyTorch XPU | working offline / without Colab limits |

The app and a worker never talk directly: the app drops **job folders** into a folder
the worker watches (your Google Drive for Colab, a local folder for your PC), and the
worker writes results back next to them.

---

## 1. Install the app

Tested on Windows 11 with Python 3.13 and Node 20+.

1. Install **Python 3.11+**, **Node.js 20+**, **Git** and **FFmpeg** (a "full" build, e.g.
   `winget install --id Gyan.FFmpeg -e`; it must be on `PATH`).
2. Get the code and install:
   ```bash
   git clone <this repository> lang-bridge
   cd lang-bridge
   pip install -r requirements.txt
   cd web && npm install && npm run build && cd ..
   ```
3. Start it: double-click **`Lang-Bridge.cmd`**, or run `python -m app`
   (`python -m app --browser` opens it in your browser instead of its own window).

Your projects, settings and exports are stored in `data/` inside the app folder
(ignored by git).

## 2. Accounts you need (once)

- **Hugging Face** account and a **read token** (<https://huggingface.co/settings/tokens>).
- Accept the terms of the gated speaker-detection model:
  <https://huggingface.co/pyannote/speaker-diarization-community-1> (log in, click *Agree*).
  Without this, speaker detection fails; everything else still works.

---

## 3. The heavy pipeline: one notebook, anywhere

Transcription, speaker detection, separation, cloned voices and mixing run in a notebook you
start yourself: **[`notebooks/lang_bridge.ipynb`](notebooks/lang_bridge.ipynb)**. It dubs a
list of links (videos, playlists, channels; no folder needed) and/or a folder of videos
end to end with no app, and finds out where it runs
by itself:

- **Kaggle**: uses both GPUs of *GPU T4 x2*; keep results with `STORAGE = bucket`.
- **Colab**: uses its T4; Drive is connected when a setting points into it.
- **Your own machine** (Jupyter, Python ≥ 3.10): an NVIDIA GPU if there is one, otherwise the
  CPU; PyTorch and ffmpeg are installed if missing.

Everything is typed in its **Settings** cell: `STORAGE` (folder or bucket), `LINKS`,
`VIDEOS`, `LANGUAGE`, `TARGETS`, `OUTPUT`, `BUCKET`, `HF_TOKEN`, `DEVICE` (auto / cpu /
1 GPU / 2 GPUs). **Never share or commit the notebook with your token filled in.** Full
guide: **[notebooks/README.md](notebooks/README.md)**.

The app reads what the notebook wrote. With a bucket, add it under Settings → Folders
(*HF bucket*) and press Sync. With a folder your PC can see (Drive for Desktop, or this PC),
add it as a *Results folder*. Its runs show on Home, and their results open by themselves.
The app's Run panel can also *prepare* a run for chosen videos: put the printed folder in
the notebook's `RUN_FOLDER`.

On a server: `from lb_worker.research import run_folder` (see `worker/lb_worker/research.py`).

---

## 4. Set up the local worker (this PC)

The second folder in **Folders** is *This PC*, default **`D:\LangBridgeLocal`** (change the
path if you like). Everything the worker installs or downloads stays inside it.

1. Log in to Hugging Face once on this PC (for speaker detection):
   ```bash
   hf auth login
   ```
2. **Optional, Intel Arc / Core Ultra graphics:** create the GPU environment once
   (downloads about 2 GB; needs a recent Intel graphics driver):
   ```bash
   python scripts/local_worker.py --setup-xpu
   ```
   With it, separation, alignment and voicing run on the Arc GPU (about 6× faster than the
   CPU); without it everything runs on the CPU, and voicing is then slow (prefer Colab).
3. Double-click **`Local-Worker.cmd`** and keep its window open while jobs run.
   The first run builds its own Python environment and downloads models one at a time,
   with resume and retries, so a slow or dropping connection is fine.

Measured on a Core Ultra 7 165H with Arc graphics, 105 s test clip: separation 3.6 min
(Arc), transcription 50 s, speaker detection 60 s (CPU), voicing ~12–19 s per line (Arc,
16 diffusion steps).

---

## 5. Using the app

1. **Home → New dubbing project**: paste a video link or a file path, optionally a clip
   range and the number of speakers. It downloads, extracts audio and queues analysis.
2. **Analysis & jobs**: when separation, transcription, alignment and speaker detection are
   done, press **Load results**.
3. **Characters**: name each voice, set gender, star who needs dubbing, merge cards that are
   the same person. Tone samples run from each person's quietest to most animated line.
4. **Transcript**: keyboard-driven review. `J`/`K` move, `Space` plays, `Enter` edits,
   `1–9` sets the speaker, `R` marks reviewed, `C` starts a chapter, `M` merges with the next
   line, `Ctrl+Enter` (while editing) splits at the cursor. Reviewed lines are never changed
   by a later reload.
5. **Translate**: chapter by chapter; a meter shows whether each line fits its time slot.
   Editing a line locks it against re-translation.
6. **Voice**: voice all lines (2 takes each, scored for likeness, clarity and fit; the best
   is picked), listen, swap takes, regenerate lines. Worst-first sorting helps.
7. **Mix & export**: render, preview (Amharic mix / dub only / original), check the fit
   table, then **Export MP4**: video + Amharic dub (default audio) + original audio +
   Amharic and English subtitle tracks, plus `.srt` files.

### Words that stay in the original language
Short interjections ("wow", "ehm", "yeah", "oh nice", "okay") often sound better in the
speaker's own voice. Such lines default to **Keep original** (the original voice plays and
the subtitles show the original words); switch any line between **Dub** and **Keep original**
in Translate or Voice, and edit the word list in **Folders**.

### Word aligners for any language
After transcription, each word is pinned to the audio by a CTC model of that language.
In **Folders → Word aligners** set one per language code: search the Hugging Face Hub from
the app and press **Check** to confirm a model can align (CTC architecture with a character
vocabulary covering the language). Defaults: `en` → `facebook/wav2vec2-base-960h`,
`am` → `badrex/Ethio-ASR-amharic`.

### Translation
Translation currently uses Google Translate's public web endpoint, batched with context and
verified line by line. It is unofficial and may change or rate-limit; every line is editable.

---

## 6. Models and licences

Workers download these on first use. **Check each model card before any commercial use.**

| Step | Model | Licence (as published) |
|---|---|---|
| Separation | BS-RoFormer via `audio-separator` (UVR models) | see the model's source |
| Transcription | Whisper large-v3 / large-v3-turbo via `faster-whisper` | MIT |
| Alignment | `facebook/wav2vec2-base-960h` (en), `badrex/Ethio-ASR-amharic` (am) | Apache-2.0 / CC-BY-4.0 |
| Speaker detection | `pyannote/speaker-diarization-community-1` | gated: accept its terms |
| Voicing | `k2-fsa/OmniVoice` | weights **CC-BY-NC (non-commercial)** |
| Voicing (alternative) | `african-low-resource/omnivoice-amharic` | Apache-2.0 |
| Scoring | `microsoft/wavlm-base-plus-sv`, Ethio-ASR | see model cards |

The research comparison in `spikes/voice_bakeoff` can also try Fish Audio S2 Pro
(research / non-commercial licence) and Seed-VC.

## 7. Licence

The code is released under the [MIT licence](LICENSE). It includes
`worker/lb_worker/align_core.py`, whisperX's forced-alignment functions
(BSD-2-Clause, © Max Bain), vendored with attribution. Models are downloaded separately
and keep their own licences (section 6).

## 8. Responsible use

Voice cloning copies a real person's voice. Dub only material you have the right to use,
and clone voices only with the speakers' consent or where the law and the platform allow
it. Label dubbed output as AI-generated.

---

## 9. Development

- Dev servers: `python -m app --serve` (API on port 8765) and `npm --prefix web run dev`
  (UI on <http://127.0.0.1:5173>, hot reload, `/api` proxied). Both are defined in
  `.claude/launch.json`.
- Tests: `python -m pytest -q`; frontend types: `cd web && npx tsc --noEmit`.

```
app/        FastAPI backend: projects, jobs, translation, voice, mix/export (SQLite in data/)
web/        React + Vite + Tailwind UI
worker/     lb_worker: the job-folder protocol, the worker loop, and the stages
            (separate, asr, align, diarize, voice, prefetch, tts_bakeoff)
notebooks/  lang_bridge.ipynb (Colab, Kaggle, local), e2e_test.ipynb, bench_gpu_identity.ipynb
scripts/    build_notebook.py (writes notebooks/*.ipynb), local_worker.py, watch.py, ...
spikes/     research experiments (voice bake-off)
tests/      unit tests
```

**Job-folder protocol.** A job is a folder `jobs/<id>/` with one writer per file: the app
writes `job.json` and `in/`, the worker writes `status.json`, `out/` and `log.txt`. Workers
announce themselves with a heartbeat in `workers/`. Jobs can depend on other jobs
(`after`), long stages save progress as they go, and a job whose worker vanished is taken
over by the next worker.
