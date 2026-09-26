"""Desktop half of the bake-off: after separate/asr/diarize are done, pick test
sentences, translate them, build prompts, make edge-tts takes, queue tts_bakeoff.

    python spikes/voice_bakeoff/prepare.py [--per-speaker 6]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.jobs.drive_queue import DriveQueue  # noqa: E402
from app.translate.ethiopic import budget  # noqa: E402
from app.translate.google_batch import GoogleBatchTranslator  # noqa: E402
from app.translate.sentences import sentences  # noqa: E402

DATA = Path(__file__).parent / "data"
EDGE_VOICE = {"female": "am-ET-MekdesNeural", "male": "am-ET-AmehaNeural"}


def pick(sents: list[dict], per_speaker: int):
    """Per speaker: a ~10 s bank of the longest clean sentences, test sentences of
    1.5-8 s from the rest, and the remainder held out for the similarity centroid."""
    by = {}
    for s in sents:
        # Clean = starts capitalised and ends a sentence. Unpunctuated stretches are
        # where word timing drifted and a boundary word may belong to the other
        # speaker, which would poison a voice prompt.
        clean = s["text"][:1].isupper() and s["text"].rstrip()[-1:] in ".?!"
        if s["speaker"] and clean:
            by.setdefault(s["speaker"], []).append(s)
    bank, bank_text, heldout, tests = {}, {}, {}, []
    for spk, ss in by.items():
        ranked = sorted(ss, key=lambda s: -s["slot_s"])
        b, dur = [], 0.0
        for s in ranked:
            if dur >= 10 or s["slot_s"] > 12:
                continue
            b.append(s)
            dur += s["slot_s"]
        rest = [s for s in ss if s not in b]
        t = [s for s in rest if 1.5 <= s["slot_s"] <= 8][:per_speaker]
        h = [s for s in rest if s not in t and s["slot_s"] >= 1.0] or t  # tiny speaker: reuse tests
        bank[spk] = [[s["start"], s["end"]] for s in sorted(b, key=lambda s: s["start"])]
        bank_text[spk] = " ".join(s["text"] for s in sorted(b, key=lambda s: s["start"]))
        heldout[spk] = [[s["start"], s["end"]] for s in h]
        tests += t
    return bank, bank_text, heldout, sorted(tests, key=lambda s: s["start"])


async def edge(text: str, voice: str, out: Path):
    import edge_tts

    await edge_tts.Communicate(text, voice).save(str(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-speaker", type=int, default=6)
    ap.add_argument("--gender", action="append", default=[],
                    help="SPEAKER_00=female; asked interactively when missing")
    a = ap.parse_args()
    q = DriveQueue()
    ids = json.loads((DATA / "jobs.json").read_text())
    for k in ("separate", "asr", "diarize"):
        st = q.status(ids[k])
        if st["state"] != "done":
            sys.exit(f"{k} is {st['state']}: {st.get('error', '')}")
    asr = json.loads((q.out_dir(ids["diarize"]) / "asr_spk.json").read_text(encoding="utf-8"))
    sents = sentences(asr)
    (DATA / "sentences.json").write_text(json.dumps(sents, indent=1), encoding="utf-8")

    # Translate every sentence (the whole clip is the context), then keep the test ones.
    tr = GoogleBatchTranslator("en", "am", context=2)
    am = tr.translate([{"id": s["id"], "text": s["text"]} for s in sents])
    print(f"translated {len(am)} sentences in {tr.calls} requests")
    for s in sents:
        s["am"] = am.get(s["id"], "")
        s["budget"] = budget(s["am"], s["slot_s"])
    (DATA / "sentences.json").write_text(json.dumps(sents, ensure_ascii=False, indent=1), encoding="utf-8")

    bank, bank_text, heldout, tests = pick(sents, a.per_speaker)
    genders = dict(g.split("=") for g in a.gender)
    for spk in bank:
        if spk not in genders:
            talk = [s["text"] for s in sents if s["speaker"] == spk][:2]
            genders[spk] = input(f"{spk} said {talk!r}\n  gender (female/male)? ").strip().lower()

    edge_dir = DATA / "edge"
    edge_dir.mkdir(exist_ok=True)
    items, files = [], []
    for s in tests:
        mp3 = edge_dir / f"edge_{s['id']}.mp3"
        if not mp3.exists():
            asyncio.run(edge(s["am"], EDGE_VOICE[genders[s["speaker"]]], mp3))
        files.append(mp3)
        items.append({"id": s["id"], "speaker": s["speaker"], "start": s["start"], "end": s["end"],
                      "slot_s": s["slot_s"], "en": s["text"], "am": s["am"],
                      "edge": f"jobs/JOB/in/{mp3.name}", "gender": genders[s["speaker"]],
                      "budget": s["budget"]})
    plan = {"items": items, "bank": bank, "bank_text": bank_text, "heldout": heldout, "genders": genders}
    plan_path = DATA / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    for it in items:
        print(f"  #{it['id']:<3} {it['speaker']} {it['slot_s']:5.2f}s ratio={it['budget']['ratio']}  {it['en'][:50]}")
        print(f"        {it['am']}")

    job = q.submit("tts_bakeoff", files=[plan_path, *files],
                   shared=[q.out_ref(ids["separate"], "vocals.flac")])
    ids["tts_bakeoff"] = job
    (DATA / "jobs.json").write_text(json.dumps(ids, indent=1))
    print("queued", job)


if __name__ == "__main__":
    main()
