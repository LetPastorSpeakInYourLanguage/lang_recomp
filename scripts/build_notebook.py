"""Write the notebooks in notebooks/ — they run anywhere: Colab (one T4), Kaggle (two T4s),
a local Jupyter or a server (CPU or NVIDIA GPU).

    python scripts/build_notebook.py

Edit the cells here, not in the .ipynb files, so the notebooks stay reviewable in git.
Every notebook takes its token and bucket from its settings cell (never from platform
secrets) and finds the code with the same first cell (GET_CODE).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = "https://github.com/LetPastorSpeakInYourLanguage/lang_recomp"
BRANCH = "main"  # the branch the notebooks download
DIR = Path(__file__).resolve().parents[1] / "notebooks"
OUT = DIR / "lang_bridge.ipynb"
E2E_OUT = DIR / "e2e_test.ipynb"
BENCH_OUT = DIR / "bench_gpu_identity.ipynb"
RAW = "https://raw.githubusercontent.com/LetPastorSpeakInYourLanguage/lang_recomp/main/notebooks"


def cell(kind: str, src: str, form: bool = False) -> dict:
    c = {"cell_type": kind, "metadata": {"cellView": "form"} if form else {},
         "source": src.strip("\n").splitlines(keepends=True)}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


# The machine settings every notebook shares (appended to its settings cell).
MACHINE = """
HF_TOKEN = ""  #@param {type:"string"}
#@markdown Your [Hugging Face token](https://huggingface.co/settings/tokens) (write access if you use a bucket). **Never share or commit this notebook with a token filled in.**
DEVICE = "auto"  #@param ["auto", "cpu", "1 GPU", "2 GPUs"]
#@markdown `auto`: every GPU there is (Kaggle T4 x2 → 2, Colab T4 → 1), else the CPU.
WORK_DIR = ""  #@param {type:"string"}
#@markdown Code, models and scratch files. Empty: `/kaggle/working`, `/content`, or `~/lang-bridge` on your own machine.
CODE_BRANCH = "%s"  #@param {type:"string"}
""" % BRANCH

# Finds the runtime and the code. It cannot import Lang-Bridge yet, so it detects the
# runtime with the same rules as lb_worker.env.runtime().
GET_CODE = f"""
#@title Get Lang-Bridge
import importlib.util, io, os, shutil, subprocess, sys, urllib.request, zipfile
from pathlib import Path

def _runtime():
    if os.environ.get('KAGGLE_KERNEL_RUN_TYPE'):
        return 'kaggle'
    try:
        if importlib.util.find_spec('google.colab'):
            return 'colab'
    except (ImportError, ValueError):
        pass
    return 'local'

RUNTIME = _runtime()
ROOT = Path(WORK_DIR).expanduser() if WORK_DIR.strip() else Path({{'kaggle': '/kaggle/working', 'colab': '/content'}}.get(RUNTIME) or Path.home() / 'lang-bridge')
ROOT.mkdir(parents=True, exist_ok=True)
BRANCH = CODE_BRANCH.strip() or '{BRANCH}'
# On your own machine, a notebook opened from inside a Lang-Bridge checkout uses that checkout.
_here = next((p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker' / 'lb_worker').is_dir() and (p / 'app').is_dir()), None)
if RUNTIME == 'local' and _here:
    CODE = _here  # as it is, on whatever branch it has checked out (CODE_BRANCH is not used)
    BRANCH = subprocess.run(['git', '-C', str(CODE), 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip() or 'checkout'
else:
    CODE = ROOT / 'lang_recomp'
    if shutil.which('git'):
        if not (CODE / '.git').exists():
            shutil.rmtree(CODE, ignore_errors=True)
            subprocess.run(['git', 'clone', '-q', '--depth', '1', '-b', BRANCH, '{REPO}', str(CODE)], check=True)
        else:
            subprocess.run(['git', '-C', str(CODE), 'fetch', '-q', '--depth', '1', 'origin', BRANCH], check=True)
            subprocess.run(['git', '-C', str(CODE), 'checkout', '-q', '-f', '-B', BRANCH, 'FETCH_HEAD'], check=True)
    else:  # no git on this machine: the branch as a zip
        shutil.rmtree(CODE, ignore_errors=True)
        with urllib.request.urlopen('{REPO}/archive/refs/heads/' + BRANCH + '.zip') as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(ROOT)
        next(p for p in ROOT.glob('lang_recomp-*') if p.is_dir()).rename(CODE)
sys.path[:0] = [str(CODE), str(CODE / 'worker')]
_v = subprocess.run(['git', '-C', str(CODE), 'log', '-1', '--format=%h (%cd)'], capture_output=True, text=True).stdout.strip() if (CODE / '.git').exists() else 'zip'
print(f'Lang-Bridge {{BRANCH}} {{_v}} in {{CODE}} · running on {{RUNTIME}}')
"""

INTRO = f"""
## Where it runs

| | Before **Run all** |
|---|---|
| **Kaggle** | Import this notebook (File → Import notebook → Link: `{RAW}/lang_bridge.ipynb`); Settings → Accelerator **GPU T4 x2** (both are used), Internet **on** (phone-verified account). Use `STORAGE = bucket` to keep results. |
| **Colab** | Runtime → Change runtime type → **T4 GPU**. Drive is connected by itself when a setting points into `/content/drive/…`. |
| **Your own machine** | Jupyter with Python ≥ 3.10 (a fresh virtual environment is best). An NVIDIA GPU is used if there is one, otherwise the CPU (fine for transcripts, slow for voices). PyTorch and ffmpeg are installed if missing. |

Everything is set in the **Settings** cell, the token and bucket included.
"""

CELLS = [
    cell("markdown", f"""
# Lang-Bridge — dub a team's videos and links

Runs the whole pipeline — **fetch → transcribe → translate → voice → mix** — on a team's
working folder: its own videos and/or links (videos, playlists, channels), from any language into any languages, with no app needed.
The Lang-Bridge app can open the results to check, fix and listen.
{INTRO}
Safe to stop at any time: run again with the same settings to continue (or see RUN_FOLDER).
Guide: [{REPO}/tree/main/notebooks]({REPO}/tree/main/notebooks)
"""),
    cell("code", """
#@title Settings
WORKSPACE = ""  #@param {type:"string"}
#@markdown The team's working folder — always needed, even if it starts empty or all videos come from links. It holds the team's videos (any nesting; `name.srt` beside a video is used instead of transcribing), `lang-bridge.json` (language, targets, every link added) and all results in `.lb/`. Colab: a Drive folder, e.g. `/content/drive/MyDrive/LangBridge/Preaching`; your machine: any folder. With STORAGE = bucket: leave empty (a local copy in WORK_DIR).
STORAGE = "folder"  #@param ["folder", "bucket"]
#@markdown `folder`: the workspace is WORKSPACE. `bucket`: the workspace is BUCKET — downloaded first, results pushed back after every stage (the app syncs it). On Kaggle use `bucket`.
BUCKET = ""  #@param {type:"string"}
#@markdown A Hugging Face bucket, `namespace/name`. Needed for STORAGE = bucket; with a folder it is left alone.
LINKS = ""  #@param {type:"string"}
#@markdown Links to add: videos, playlists or channels (YouTube or any site yt-dlp supports), separated by spaces, or a `.txt` file with one link per line. They are recorded in the workspace and downloaded into it; links added before are always included.
LANGUAGE = "en"  #@param {type:"string"}
#@markdown The videos' language (e.g. `en`, `tr`, `am`). Must match an existing workspace's.
TARGETS = "am"  #@param {type:"string"}
#@markdown Languages to dub into, e.g. `am om ti`. Added to the workspace's own (both are done).
STAGES = "fetch transcribe translate voice mix"  #@param {type:"string"}
#@markdown Which stages: e.g. `fetch transcribe` for transcripts only.
DUB_LIMIT = 0  #@param {type:"integer"}
#@markdown Voice and mix only the first N videos (0 = all). The rest are transcribed and translated.
LIMIT = 0  #@param {type:"integer"}
#@markdown Work on only the first N videos (0 = all).
ASR_MODELS = "am=badrex/Ethio-ASR-amharic"  #@param {type:"string"}
#@markdown A speech recogniser per source language from Hugging Face (`lang=repo`, space separated). Languages not named use Whisper large-v3.
ALIGNERS = ""  #@param {type:"string"}
#@markdown Word aligners per language (`lang=repo`), over the built-in ones for ~27 languages.
TRANSLATOR = "google"  #@param ["google", "yeha"]
#@markdown `yeha`: [YehaTranslate](https://huggingface.co/hasab-ai/YehaTranslate) (Hasab AI) on this GPU, for English to or from Amharic, Afaan Oromo and Tigrinya; other languages still use Google. Accept its terms once on that page with the account of your HF_TOKEN. Licence: non-commercial (CC BY-NC 4.0).
CAPTIONS = 0  #@param {type:"integer"}
ALIGN_CAPTIONS = 0  #@param {type:"integer"}
#@markdown YouTube only: also take YouTube's captions for the first N videos, force-align the first M, and compare with Whisper.
RUN_FOLDER = ""  #@param {type:"string"}
#@markdown Continue a run: `runs/<run>` (in the workspace's `.lb/`), or a full path. Settings above are then ignored.
""" + MACHINE),
    cell("code", GET_CODE, form=True),
    cell("code", """
#@title Set up this machine
from lb_worker import env
M = env.setup(RUNTIME, ROOT, DEVICE, STORAGE, WORKSPACE, BUCKET, HF_TOKEN)
""", form=True),
    cell("code", """
#@title Run
from lb_worker.research import run_manifest, run_workspace

pairs = lambda text: dict(p.split('=', 1) for p in text.split() if '=' in p)
if RUN_FOLDER.strip():
    folder = RUN_FOLDER.strip() if os.path.isabs(RUN_FOLDER.strip()) else M['workspace'] / '.lb' / RUN_FOLDER.strip()
    result = run_manifest(folder, hf_token=M['token'], bucket=M['bucket'] and M['bucket'] + '/.lb')
else:
    result = run_workspace(M['workspace'], LANGUAGE, TARGETS.split(), LINKS, STAGES.split(),
                           bucket=M['bucket'] if M['storage'] == 'bucket' else None, hf_token=M['token'],
                           dub_limit=DUB_LIMIT or None, limit=LIMIT or None, captions=CAPTIONS,
                           align_captions=ALIGN_CAPTIONS, asr_models=pairs(ASR_MODELS), aligners=pairs(ALIGNERS),
                           options=M['options'])
""", form=True),
    cell("markdown", """
## Look at the results

- **Without the app**: the dubbed videos are in `.lb/library/<work>/<video>/export/` in the
  workspace (the folder, or the bucket).
- **With a bucket**: in the Lang-Bridge app, Settings → Folders → add one of kind
  **Hugging Face bucket**, then **Sync**; the run's progress shows as it goes and its results
  open by themselves.
- **With a workspace folder the app can see** (Drive for Desktop, or this PC): Settings →
  Folders → add it as a **results folder**; its runs appear under Home → Runs.

Done with the GPU? Colab: **Runtime → Disconnect and delete runtime**; Kaggle: **Stop session**.
"""),
]


SIX_MINUTE = ["https://www.youtube.com/watch?v=xwseWCSXD3Y", "https://www.youtube.com/watch?v=SC_opiKLohg",
              "https://www.youtube.com/watch?v=D9jZMLm72a8"]
SIX_MINUTE_OTHERS = ["https://www.youtube.com/watch?v=MSJMJxd1udk", "https://www.youtube.com/watch?v=hb1CBEENiPQ",
                     "https://www.youtube.com/watch?v=vxoPApiNZBU", "https://www.youtube.com/watch?v=-idY8F7LOSE",
                     "https://www.youtube.com/watch?v=m7IlyBEyi3c"]

E2E = [
    cell("markdown", f"""
# Lang-Bridge end-to-end test: two videos → Hugging Face bucket → the app

Two 6 Minute English episodes (Neil and a co-host), English → Amharic, every stage, results
pushed to your bucket after each stage. The bucket is the test's workspace (its links are
recorded in its `lang-bridge.json`). Fill in `HF_TOKEN` (can write to the bucket) and
`BUCKET` (e.g. `you/lang-bridge-test`) below, then **Run all**, and follow it in the app
(Home → Runs on …).
{INTRO}"""),
    cell("code", """
#@title Settings
BUCKET = ""  #@param {type:"string"}
#@markdown Your Hugging Face bucket, `namespace/name`.
""" + MACHINE),
    cell("code", GET_CODE, form=True),
    cell("code", f"""
#@title Run the test
from lb_worker import env
from lb_worker.research import run_workspace
M = env.setup(RUNTIME, ROOT, DEVICE, 'bucket', '', BUCKET, HF_TOKEN)
result = run_workspace(M['workspace'], 'en', ['am'], {json.dumps(SIX_MINUTE[:2])}, bucket=M['bucket'],
                       hf_token=M['token'], options=M['options'])
""", form=True),
]

BENCH = [
    cell("markdown", f"""
# Lang-Bridge bench — GPU speed (E1) and video identity (E2)

Measures, before we build (plan: `docs/SCALE_PLAN.md`, Phase A):

- **E1**: how fast separation, Whisper and OmniVoice run with each setting, how full the
  GPU gets, and whether faster settings change the result; separation from an Opus copy.
- **E2**: whether the same video is recognised across copies, re-downloads, formats,
  trims and added intros, and never confused with other episodes.

Runs on Colab, Kaggle or your own GPU machine (see below). **Run all** (about an hour on a
T4). Paste the last cell's output back.
{INTRO}"""),
    cell("code", f"""
#@title Settings
SOURCES = {json.dumps(" ".join(SIX_MINUTE))}  #@param {{type:"string"}}
#@markdown E1 videos: links or file paths, separated by spaces (add a sermon from your Drive if you like).
SECONDS = 120  #@param {{type:"integer"}}
#@markdown Length of each excerpt for E1.
E2_MAIN = {json.dumps(" ".join(SIX_MINUTE[:2]))}  #@param {{type:"string"}}
E2_OTHERS = {json.dumps(" ".join(SIX_MINUTE_OTHERS))}  #@param {{type:"string"}}
#@markdown E2: videos to recognise, and other videos that must never match them.
RUN_SEPARATION = True  #@param {{type:"boolean"}}
RUN_WHISPER = True  #@param {{type:"boolean"}}
RUN_OMNIVOICE = True  #@param {{type:"boolean"}}
RUN_IDENTITY = True  #@param {{type:"boolean"}}
""" + MACHINE),
    cell("code", GET_CODE, form=True),
    cell("code", """
#@title Set up this machine
from lb_worker import env
M = env.setup(RUNTIME, ROOT, DEVICE, 'folder', str(ROOT / 'lb-bench'), '', HF_TOKEN)
OUT = str(M['workspace'])  # results: lb-bench in WORK_DIR
os.environ.setdefault('LB_CACHE', OUT + '/cache')
""", form=True),
    cell("code", """
#@title E1 · separation settings and the Opus copy
from pathlib import Path
from lb_worker.bench import gpu
out = Path(OUT)
items = gpu.prepare(SOURCES.split(), out, seconds=SECONDS)
if RUN_SEPARATION:
    sep = gpu.bench_separation(items, out)
    copy = gpu.bench_audio_copy(items, out, sep)
""", form=True),
    cell("code", """
#@title E1 · Whisper batch size
if RUN_WHISPER:
    whisper = gpu.bench_whisper(items, out)
""", form=True),
    cell("code", """
#@title E1 · OmniVoice takes per call
import json
if RUN_OMNIVOICE:
    sep_dir = Path(next(r['dir'] for r in json.loads((out / 'e1_separation.json').read_text())['rows'] if r.get('dir')))
    ref, ref_text = gpu.reference(items, sep_dir, out)
    omni = gpu.bench_omnivoice(ref, ref_text, out)
""", form=True),
    cell("code", """
#@title E2 · video identity
from lb_worker.bench import identity
from lb_worker.deps import ensure
from lb_worker.stages.bulk import fetch
if RUN_IDENTITY:
    ensure('yt-dlp', probe='yt_dlp')
    d = out / 'identity'
    get = lambda url, name, h: fetch({'id': name, 'url': url}, d / f'{name}_{h}', h)
    others = [get(u, f'o{k}', 360) for k, u in enumerate(E2_OTHERS.split())]
    mains = []
    for k, u in enumerate(E2_MAIN.split()):
        vid = u.split('v=')[-1][:11]
        mains.append({'name': f'm{k}', 'video': get(u, f'm{k}', 720), 'redownload': get(u, f'm{k}', 360),
                      'other': others[0], 'links': identity.link_forms(vid) if 'youtube' in u else []})
    ident = identity.run(mains, others, out)
""", form=True),
    cell("code", """
#@title Summary (paste this back)
import json
summary = {}
for name in ('e1_separation', 'e1_audio_copy', 'e1_whisper', 'e1_omnivoice', 'e2_identity'):
    f = out / f'{name}.json'
    if f.exists():
        r = json.loads(f.read_text())
        rows = [{k: v for k, v in x.items() if k != 'dir'} for x in r.get('rows', [])]
        summary[name] = {k: v for k, v in r.items() if k not in ('rows', 'links')} | {'rows': rows}
print(json.dumps(summary, ensure_ascii=False))
""", form=True),
]


def write(path: Path, cells: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    nb = {"nbformat": 4, "nbformat_minor": 0, "cells": cells,
          "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                       "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}}}
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", path)


NOTEBOOKS = {OUT: CELLS, E2E_OUT: E2E, BENCH_OUT: BENCH}


def main() -> None:
    for path, cells in NOTEBOOKS.items():
        write(path, cells)


if __name__ == "__main__":
    main()
