"""Write colab/lang_bridge.ipynb — the research notebook (run the pipeline by hand on a GPU).

    python scripts/build_notebook.py

Edit the cells here, not in the .ipynb, so the notebook stays reviewable in git.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = "https://github.com/LetPastorSpeakInYourLanguage/lang_recomp"
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
    subprocess.run(['git', 'clone', '-q', '--depth', '1', '{REPO}', '/content/lang_recomp'], check=True)
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


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    nb = {"nbformat": 4, "nbformat_minor": 0, "cells": CELLS,
          "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                       "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}}}
    OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
