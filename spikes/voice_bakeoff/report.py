"""Build the blind listening report next to the bake-off outputs.

    python spikes/voice_bakeoff/report.py        -> <job>/out/report.html (open it in a browser)

Per sentence: the English source clip, then every system's take under a shuffled
letter. Rate each 1-5; names and objective scores stay hidden until "Reveal".
"Copy ratings" puts JSON on the clipboard to paste back into the chat.
"""
from __future__ import annotations

import html
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.jobs.drive_queue import DriveQueue  # noqa: E402

DATA = Path(__file__).parent / "data"
LABEL = {
    "omni_bank": "OmniVoice · bank prompt",
    "omni_self_dur": "OmniVoice · own-sentence prompt + fixed duration",
    "omniam_bank": "OmniVoice-Amharic finetune · bank prompt",
    "edge_raw": "edge-tts (no cloning) — floor",
    "edge_seedvc": "edge-tts → Seed-VC",
    "fish_bank": "Fish S2 Pro · bank prompt",
}


def main():
    q = DriveQueue()
    job = json.loads((DATA / "jobs.json").read_text())["tts_bakeoff"]
    out = q.out_dir(job)
    bake = json.loads((out / "bakeoff.json").read_text(encoding="utf-8"))
    scores = json.loads((out / "scores.json").read_text(encoding="utf-8")) if (out / "scores.json").exists() else {"items": {}}
    systems = list(bake["systems"])
    rng = random.Random(7)

    rows = []
    for it in bake["items"]:
        present = [s for s in systems if (out / f"{s}_{it['id']}.wav").exists()]
        rng.shuffle(present)
        cells = []
        for k, s in enumerate(present):
            sc = scores["items"].get(f"{s}_{it['id']}", {})
            cells.append(f"""
      <div class="take" data-sys="{s}">
        <div class="tk"><b>{chr(65 + k)}</b><span class="name">{html.escape(LABEL.get(s, s))}</span></div>
        <audio controls preload="none" src="{s}_{it['id']}.wav"></audio>
        <div class="rate" data-key="{it['id']}:{s}">{''.join(f'<button>{n}</button>' for n in range(1, 6))}</div>
        <div class="sc">sim <i>{sc.get('sim', '–')}</i> · CER <i>{sc.get('cer', '–')}</i> ·
          dur <i>{sc.get('dur', '–')}×</i> · emo Δ <i>{sc.get('av_dist', '–')}</i></div>
        <div class="asr">{html.escape(sc.get('asr', ''))}</div>
      </div>""")
        b = it.get("budget", {})
        rows.append(f"""
  <section>
    <header><span class="id">#{it['id']}</span><span class="spk">{it['speaker']} · {it.get('gender', '')}</span>
      <span class="slot">{it['slot_s']:.2f}s slot · Amharic est. {b.get('est_s', '–')}s (×{b.get('ratio', '–')})</span></header>
    <p class="en">{html.escape(it['en'])}</p>
    <p class="am">{html.escape(it['am'])}</p>
    <div class="src"><span>source</span><audio controls preload="none" src="src_{it['id']}.wav"></audio></div>
    <div class="takes">{''.join(cells)}</div>
  </section>""")

    summary = []
    for s in systems:
        vals = [scores["items"].get(f"{s}_{it['id']}", {}) for it in bake["items"]]
        vals = [v for v in vals if "sim" in v]

        def mean(k):
            xs = [v[k] for v in vals if v.get(k) is not None]
            return f"{sum(xs) / len(xs):.3f}" if xs else "–"

        err = bake["systems"][s].get("error", "")
        summary.append(f"<tr><td>{html.escape(LABEL.get(s, s))}</td><td>{len(vals)}</td><td>{mean('sim')}</td>"
                       f"<td>{mean('cer')}</td><td>{mean('dur')}</td><td>{mean('av_dist')}</td>"
                       f"<td>{bake['systems'][s].get('peak_vram_gb', '–')}</td><td>{bake['systems'][s].get('wall_s', '–')}</td>"
                       f"<td class='err'>{html.escape(err[:160])}</td></tr>")
    real = scores.get("real_sim", {})

    page = TEMPLATE.replace("{{ROWS}}", "".join(rows)).replace("{{SUMMARY}}", "".join(summary)) \
        .replace("{{REAL}}", html.escape(", ".join(f"{k}: {v}" for k, v in real.items()) or "–")) \
        .replace("{{JOB}}", job)
    (out / "report.html").write_text(page, encoding="utf-8")
    print(out / "report.html")


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amharic Voice Bake-off</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Noto+Sans+Ethiopic:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#e9eef4;--panel:#fff;--panel2:#f3f6fa;--border:#d2dbe5;--text:#0d1922;--dim:#57697a;--faint:#8496a6;
--accent:#0b69b0;--soft:#e1eefa;--top:#0a4e86;--topfg:#dceaf6;--good:#12735c;--bad:#a83236}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d131a;--panel:#151d25;--panel2:#111820;--border:#26313c;
--text:#dce6ef;--dim:#92a3b3;--faint:#69798a;--accent:#4fa6e8;--soft:#132b3b;--top:#0a1720;--topfg:#cfe0ee;--good:#3eae8e;--bad:#e0696d}}
:root[data-theme=dark]{--bg:#0d131a;--panel:#151d25;--panel2:#111820;--border:#26313c;--text:#dce6ef;--dim:#92a3b3;--faint:#69798a;
--accent:#4fa6e8;--soft:#132b3b;--top:#0a1720;--topfg:#cfe0ee;--good:#3eae8e;--bad:#e0696d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:12.5px/1.45 "IBM Plex Sans",system-ui,sans-serif}
.bar{position:sticky;top:0;z-index:2;background:var(--top);color:var(--topfg);display:flex;gap:10px;align-items:center;padding:8px 16px;flex-wrap:wrap}
.bar h1{font-size:14px;margin:0 auto 0 0;font-weight:600}.bar button{font:inherit;border:1px solid rgba(255,255,255,.2);
background:rgba(255,255,255,.1);color:inherit;padding:4px 10px;border-radius:4px;cursor:pointer}
main{max-width:1180px;margin:0 auto;padding:14px 16px 60px}
section,table{background:var(--panel);border:1px solid var(--border);border-radius:6px;margin-bottom:12px}
section{padding:10px 12px}header{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;color:var(--dim)}
.id{font:600 13px "IBM Plex Mono";color:var(--text)}.slot{margin-left:auto;font-family:"IBM Plex Mono";font-size:11px}
.en{margin:6px 0 2px}.am{margin:0 0 8px;font:500 15px "Noto Sans Ethiopic",sans-serif}
.src{display:flex;gap:8px;align-items:center;color:var(--faint);font-size:11px;margin-bottom:8px}
audio{height:30px;width:100%;max-width:300px}
.takes{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px}
.take{background:var(--panel2);border:1px solid var(--border);border-radius:5px;padding:7px}
.tk{display:flex;gap:6px;align-items:center;margin-bottom:4px}.tk b{font:600 13px "IBM Plex Mono";color:var(--accent)}
.name,.sc,.asr{display:none}.revealed .name,.revealed .sc,.revealed .asr{display:block}
.name{font-size:11px;color:var(--dim)}.sc{font:11px "IBM Plex Mono";color:var(--dim);margin-top:4px}.sc i{font-style:normal;color:var(--text)}
.asr{font:11.5px "Noto Sans Ethiopic";color:var(--faint);margin-top:2px}
.rate{display:flex;gap:3px;margin-top:5px}.rate button{flex:1;font:500 11px "IBM Plex Mono";padding:3px 0;border:1px solid var(--border);
background:var(--panel);color:var(--dim);border-radius:3px;cursor:pointer}.rate button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
table{width:100%;border-collapse:collapse;display:none;overflow-x:auto}.revealed table{display:table}
th,td{padding:5px 8px;border-bottom:1px solid var(--border);text-align:left;font-size:11.5px}
td:not(:first-child):not(.err){font-family:"IBM Plex Mono"}.err{color:var(--bad);font-size:10.5px}
.note{color:var(--dim);font-size:11.5px;margin:0 0 10px}
</style></head><body>
<div class="bar"><h1>Amharic voice bake-off</h1><span id="count"></span>
<button id="reveal">Reveal names &amp; scores</button><button id="copy">Copy ratings</button><button id="theme">Theme</button></div>
<main>
<p class="note">Listen to the source, then rate each take 1–5 on <b>does it sound like this person, saying this, this way</b>.
Letters are shuffled per sentence. Job {{JOB}}.</p>
<table><thead><tr><th>system</th><th>n</th><th>sim ↑</th><th>CER ↓</th><th>dur ×</th><th>emo Δ ↓</th><th>VRAM GB</th><th>wall s</th><th>error</th></tr></thead>
<tbody>{{SUMMARY}}</tbody><tfoot><tr><td colspan="9">real held-out clip vs own centroid (includes itself): {{REAL}}</td></tr></tfoot></table>
{{ROWS}}
</main>
<script>
const KEY="bakeoff-{{JOB}}";let R={};try{R=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(R))}catch(e){};count()};
const count=()=>{document.getElementById("count").textContent=Object.keys(R).length+"/"+document.querySelectorAll(".rate").length+" rated"};
document.querySelectorAll(".rate").forEach(r=>{const k=r.dataset.key;[...r.children].forEach((b,i)=>{if(R[k]===i+1)b.classList.add("on");
b.onclick=()=>{R[k]=i+1;[...r.children].forEach(x=>x.classList.remove("on"));b.classList.add("on");save()}})});
document.getElementById("reveal").onclick=()=>document.body.classList.toggle("revealed");
document.getElementById("copy").onclick=async()=>{const t=JSON.stringify(R);try{await navigator.clipboard.writeText(t);alert("Copied "+Object.keys(R).length+" ratings")}catch(e){prompt("Copy:",t)}};
document.getElementById("theme").onclick=()=>{const r=document.documentElement;r.dataset.theme=r.dataset.theme==="dark"?"light":"dark"};
count();
</script></body></html>"""

if __name__ == "__main__":
    main()
