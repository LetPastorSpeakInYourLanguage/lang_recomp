"""Write colab/lang_bridge.ipynb — the research notebook (run the pipeline by hand on a GPU).

    python scripts/build_notebook.py

Edit the cells here, not in the .ipynb, so the notebook stays reviewable in git.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = "https://github.com/LetPastorSpeakInYourLanguage/lang_recomp"
BRANCH = "main"  # the branch the notebooks download
OUT = Path(__file__).resolve().parents[1] / "colab" / "lang_bridge.ipynb"


def cell(kind: str, src: str, form: bool = False) -> dict:
    c = {"cell_type": kind, "metadata": {"cellView": "form"} if form else {},
         "source": src.strip("\n").splitlines(keepends=True)}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


CELLS = [
    cell("markdown", f"""
# Lang-Bridge — dub a folder of videos

Runs the Lang-Bridge pipeline on a GPU: **fetch → transcribe → translate → voice → mix**,
on your own videos (a folder, or YouTube links), and writes everything to an output folder
you choose. Open the results in the Lang-Bridge app to check, fix and listen.

1. **Runtime → Change runtime type → T4 GPU** (or any GPU).
2. If your videos are in Google Drive, mount it yourself (folder icon on the left → *Mount Drive*).
3. Fill in the settings below, then **Runtime → Run all**.

Safe to stop at any time: running it again with the same settings continues where it
stopped. Guide: [{REPO}/tree/main/colab]({REPO}/tree/main/colab)
"""),
    cell("code", """
#@title Settings
VIDEOS = "/content/drive/MyDrive/Libraries/Teachings"  #@param {type:"string"}
#@markdown A folder of videos (subfolders are works; `name.srt` beside a video is used instead of transcribing). Leave empty to use only YouTube links.
YOUTUBE = ""  #@param {type:"string"}
#@markdown YouTube video or playlist links, separated by spaces (optional).
OUTPUT = "/content/drive/MyDrive/LangBridge-output"  #@param {type:"string"}
#@markdown Where results go: the dubbed videos, transcripts, and the package the app opens.
LANGUAGE = "en"  #@param {type:"string"}
TARGETS = "am"  #@param {type:"string"}
#@markdown Languages to dub into, e.g. `am om ti`.
STAGES = "fetch transcribe translate voice mix"  #@param {type:"string"}
#@markdown Which stages: e.g. `fetch transcribe` for transcripts only.
DUB_LIMIT = 3  #@param {type:"integer"}
#@markdown Voice and mix only the first N videos (0 = all). The rest are transcribed and translated.
LIMIT = 0  #@param {type:"integer"}
#@markdown Work on only the first N videos (0 = all).
CAPTIONS = 0  #@param {type:"integer"}
ALIGN_CAPTIONS = 0  #@param {type:"integer"}
#@markdown YouTube only: also take YouTube's captions for the first N videos, force-align the first M, and compare with Whisper.
RUN_FOLDER = ""  #@param {type:"string"}
#@markdown Or: a run folder the Lang-Bridge app prepared (`…/runs/<run>`). When set, the settings above are ignored.
HF_TOKEN = ""  #@param {type:"string"}
#@markdown Your Hugging Face token (speaker detection uses a gated model: accept its terms on huggingface.co first). **Do not share or commit this notebook with your token filled in.**
"""),
    cell("code", f"""
#@title Get Lang-Bridge
import os, subprocess, sys
if not os.path.exists('/content/lang_recomp'):
    subprocess.run(['git', 'clone', '-q', '--depth', '1', '-b', '{BRANCH}', '{REPO}', '/content/lang_recomp'], check=True)
else:
    subprocess.run(['git', '-C', '/content/lang_recomp', 'pull', '-q'], check=False)
sys.path[:0] = ['/content/lang_recomp', '/content/lang_recomp/worker']
print(subprocess.run(['git', '-C', '/content/lang_recomp', 'log', '-1', '--format=Lang-Bridge %h (%cd)'], capture_output=True, text=True).stdout)
# the stages install what they need (Whisper, pyannote, the separator, OmniVoice) the first time they run
""", form=True),
    cell("code", """
#@title Run
from lb_worker.research import run_folder, run_manifest

if RUN_FOLDER.strip():
    result = run_manifest(RUN_FOLDER.strip(), hf_token=HF_TOKEN or None)
else:
    result = run_folder(VIDEOS.strip() or None, OUTPUT, LANGUAGE, TARGETS.split(), STAGES.split(),
                        youtube=YOUTUBE.split() or None, dub_limit=DUB_LIMIT or None, limit=LIMIT or None,
                        captions=CAPTIONS, align_captions=ALIGN_CAPTIONS, hf_token=HF_TOKEN or None)
""", form=True),
    cell("markdown", """
## Look at the results

In the Lang-Bridge app: **Home → Open a shared work**, and give the `.lbwork` path printed
above (as your PC sees it, e.g. `G:\\My Drive\\LangBridge-output\\runs\\…\\results\\….lbwork`).
Nothing is copied: the app plays the videos and dubs from the output folder.

Done with the GPU? **Runtime → Disconnect and delete runtime**.
"""),
]


SIX_MINUTE = ["https://www.youtube.com/watch?v=xwseWCSXD3Y", "https://www.youtube.com/watch?v=SC_opiKLohg",
              "https://www.youtube.com/watch?v=D9jZMLm72a8"]
SIX_MINUTE_OTHERS = ["https://www.youtube.com/watch?v=MSJMJxd1udk", "https://www.youtube.com/watch?v=hb1CBEENiPQ",
                     "https://www.youtube.com/watch?v=vxoPApiNZBU", "https://www.youtube.com/watch?v=-idY8F7LOSE",
                     "https://www.youtube.com/watch?v=m7IlyBEyi3c"]
BENCH_OUT = Path(__file__).resolve().parents[1] / "colab" / "bench_gpu_identity.ipynb"

BENCH = [
    cell("markdown", f"""
# Lang-Bridge bench — GPU speed (E1) and video identity (E2)

Measures, before we build (plan: `docs/SCALE_PLAN.md`, Phase A):

- **E1**: how fast separation, Whisper and OmniVoice run with each setting, how full the
  GPU gets, and whether faster settings change the result; separation from an Opus copy.
- **E2**: whether the same video is recognised across copies, re-downloads, formats,
  trims and added intros, and never confused with other episodes.

Works on **Colab** (Runtime → Change runtime type → T4 GPU) and **Kaggle** (File → Import
notebook → this file's GitHub link; Settings → Accelerator **GPU T4 x2**, Internet **on**).
Then **Run all** (about an hour on a T4). Paste the last cell's output back.
"""),
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
import os
KAGGLE = bool(os.environ.get("KAGGLE_KERNEL_RUN_TYPE"))  # (Colab also has a /kaggle folder)
OUT = "/kaggle/working/lb-bench" if KAGGLE else "/content/lb-bench"
#@markdown Results go to `OUT` (`/content/lb-bench` on Colab, `/kaggle/working/lb-bench` on Kaggle).
"""),
    cell("code", f"""
#@title Get Lang-Bridge (branch {BRANCH})
import os, subprocess, sys
CODE = '/kaggle/working/lang_recomp' if KAGGLE else '/content/lang_recomp'
if not os.path.exists(CODE):
    subprocess.run(['git', 'clone', '-q', '--depth', '1', '-b', '{BRANCH}', '{REPO}', CODE], check=True)
else:
    subprocess.run(['git', '-C', CODE, 'pull', '-q'], check=False)
sys.path[:0] = [CODE, CODE + '/worker']
os.environ.setdefault('LB_CACHE', OUT + '/cache')
print(subprocess.run(['git', '-C', CODE, 'log', '-1', '--format=Lang-Bridge %h (%cd)'], capture_output=True, text=True).stdout)
subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv'])
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


def main() -> None:
    write(OUT, CELLS)
    write(BENCH_OUT, BENCH)


if __name__ == "__main__":
    main()
