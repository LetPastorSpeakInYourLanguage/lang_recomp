"""The certification bench (E1, E2) on this PC: Intel Arc (XPU) for separation and
voicing, CPU for Whisper. Run with the Arc environment the local worker uses:

    D:/LangBridgeLocal/.venv-xpu/Scripts/python.exe scripts/bench_local.py [e1] [e2] [--out D:/LangBridgeLocal/bench]

Smaller than the Colab run (2 × 60 s excerpts): an integrated GPU separates at about
half real time. Results: <out>/e1_*.json, e2_identity.json, and a printed summary.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "worker")]

SOURCES = ["https://www.youtube.com/watch?v=xwseWCSXD3Y", "https://www.youtube.com/watch?v=SC_opiKLohg"]
OTHERS = ["https://www.youtube.com/watch?v=MSJMJxd1udk", "https://www.youtube.com/watch?v=hb1CBEENiPQ",
          "https://www.youtube.com/watch?v=vxoPApiNZBU"]
SEP_GRID = [(1, False, False), (4, False, False), (8, False, False), (8, True, False), (8, False, True)]


def main() -> None:
    args = sys.argv[1:]
    out = Path(args[args.index("--out") + 1]) if "--out" in args else Path("D:/LangBridgeLocal/bench")
    which = {a for a in args if a in ("e1", "e2")} or {"e1", "e2"}
    os.environ.setdefault("LB_CACHE", str(out.parent / "cache"))
    os.environ.setdefault("HF_HOME", str(Path(os.environ["LB_CACHE"]) / "hf"))
    from lb_worker.bench import gpu, identity
    from lb_worker.deps import ensure

    ensure("yt-dlp", probe="yt_dlp")
    summary = {}
    if "e1" in which:
        items = gpu.prepare(SOURCES, out, seconds=60)
        sep = gpu.bench_separation(items, out, grid=SEP_GRID)
        summary["e1_separation"] = sep
        summary["e1_audio_copy"] = gpu.bench_audio_copy(items, out, sep)
        summary["e1_whisper"] = gpu.bench_whisper(items, out, batches=(8, 16), size="large-v3-turbo")
        base = next(r["dir"] for r in sep["rows"] if r.get("dir"))
        ref, ref_text = gpu.reference(items, Path(base), out, at=15.0)
        summary["e1_omnivoice"] = gpu.bench_omnivoice(ref, ref_text, out, batches=(1, 4, 8), n=16)
    if "e2" in which:
        from lb_worker.stages.bulk import fetch

        d = out / "identity"
        get = lambda url, name, h: fetch({"id": name, "url": url}, d / f"{name}_{h}", h)  # noqa: E731
        others = [get(u, f"o{k}", 360) for k, u in enumerate(OTHERS)]
        mains = [{"name": f"m{k}", "video": get(u, f"m{k}", 720), "redownload": get(u, f"m{k}", 360),
                  "other": others[0], "links": identity.link_forms(u.split("v=")[-1][:11])}
                 for k, u in enumerate(SOURCES)]
        summary["e2_identity"] = identity.run(mains, others, out)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("\nsummary:", out / "summary.json")


if __name__ == "__main__":
    main()
