"""Shorter English for the lines whose translation cannot fit (decision 47).

After Google has translated a run, a line is **tight** when its predicted spoken length
overflows its window even at the mixer's hardest squeeze (`app/translate/fit.py`). Only
those lines are worked on, once for every target language:

1. a local model (`llm.Server`, Gemma 4) rewrites the English of the tight lines of a
   chapter shorter, in two versions (word limits from the tightest language), seeing the
   lines around them so it can drop what they already say;
2. Google translates both versions;
3. each version is measured (syllables of its translation in the line's window) and
   checked for meaning (the shortened English against the original, sentence embeddings
   on the CPU);
4. `fit.choose` picks Google's original or a shorter version; all of them are stored
   (`project.set_options`) for people to pick another in the app.

People's wording, locked lines, lines kept in the original voice and lines of a
recurring part are never touched. If the model cannot run, the run goes on with
Google's translations. The model's word counts are never trusted: everything is measured.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from . import llm

CHUNK = 8     # tight lines per request (they share the context lines)
CONTEXT = 2   # lines shown before and after them
EMBEDDER = "sentence-transformers/all-mpnet-base-v2"

SYSTEM = """You shorten lines of a spoken transcript so they can be dubbed into another language: the translation of each marked line takes longer to say than the speaker took.
Rewrite each marked line in plain English, shorter, keeping what it means: drop filler, repetition and what the lines around it already say, and prefer short words.
Keep every name, number and Bible reference. Each version must be a complete sentence (or sentences) in the same person, tense and tone as the original, and must follow on from the line before it.
Write two versions of each marked line: "a" with no more words than its limit a, and "b" with no more words than its limit b.
Answer with exactly two lines per marked line and nothing else, like this:
12a: <version a of line 12>
12b: <version b of line 12>"""

# One answer line: "12a: text", tolerating "[12*] a -", "**12b.**" and the like.
_ANSWER = re.compile(r"^\[?(\d+)\*?\]?\s*([ab])\s*[:.)\-–—]\s*(.+)$", re.IGNORECASE)
RETRY_CHUNK = 3  # lines left unanswered are asked again, a few at a time


def parse_answer(text: str, ids) -> dict[int, dict[str, str]]:
    """The versions in a model's answer, for the lines asked about; plain lines, so an
    answer cut short still gives every line it finished."""
    want, out = set(ids), {}
    for raw in (text or "").splitlines():
        line = raw.strip().replace("**", "").lstrip("*-• ").strip()
        m = _ANSWER.match(line)
        if not m or int(m.group(1)) not in want:
            continue
        v = m.group(3).strip().strip('"“”').strip()
        if v and not v.startswith("<version"):  # not the format's own placeholder
            out.setdefault(int(m.group(1)), {})[m.group(2).lower()] = v
    return {k: v for k, v in out.items() if v.get("a")}


def basis(model: str, text: str, caps: tuple[int, int]) -> str:
    """What a line's versions were made from: the same basis means nothing to redo."""
    return hashlib.sha1(f"{model}|{text}|{caps[0]}|{caps[1]}".encode()).hexdigest()[:12]


def prompt(title: str, lines: list[dict], caps: dict[int, tuple[int, int]]) -> str:
    rows = []
    for s in lines:
        who = f" ({s['speaker']})" if s.get("speaker") else ""
        if s["id"] in caps:
            a, b = caps[s["id"]]
            rows.append(f"[{s['id']}*]{who} {s['text']}   <- rewrite: a at most {a} words, b at most {b} words")
        else:
            rows.append(f"[{s['id']}]{who} {s['text']}")
    head = f"Chapter: {title}\n\n" if title else ""
    return head + "Transcript (marked lines are to be rewritten):\n" + "\n".join(rows)


class Embedder:
    """Sentence embeddings on the CPU, loaded in the background while the model writes."""

    def __init__(self, name: str = EMBEDDER):
        self.name, self.model, self.error = name, None, None
        self.thread = threading.Thread(target=self._load, daemon=True)
        self.thread.start()

    def _load(self):
        try:
            from .deps import ensure

            ensure("sentence-transformers", probe="sentence_transformers")
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.name, device="cpu")
        except Exception as e:  # meaning cannot be checked: shorter versions are then not used
            self.error = f"{type(e).__name__}: {e}"

    def __call__(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.thread.join()
        if self.model is None or not pairs:
            return [0.0] * len(pairs)
        a = self.model.encode([p[0] for p in pairs], normalize_embeddings=True, batch_size=64)
        b = self.model.encode([p[1] for p in pairs], normalize_embeddings=True, batch_size=64)
        return [round(float((x * y).sum()), 3) for x, y in zip(a, b)]


def run(pids: list[str], langs_of, rate_of, work: Path, cache: Path, log=print, model: str = llm.DEFAULT_MODEL,
        gpu: int | None = 0, server=None, similarity=None, translator=None, raw_log: Path | None = None) -> dict:
    """Shorten the tight lines of these videos in their languages. ``langs_of(pid)`` lists a
    video's target languages, ``rate_of(pid, lang)`` the voice's syllables per second.
    ``server``, ``similarity`` and ``translator`` stand in for the model, the embedder and
    Google (tests). ``raw_log`` keeps every answer as it came (JSON lines). Returns the
    report written to the run folder."""
    from app import chapters, project
    from app.translate import fit

    t0 = time.time()
    rep = {"model": model, "tight": 0, "fits": 0, "closer": 0, "too_long": 0, "done_before": 0, "failed": 0,
           "videos": {}}
    # 1. the tight lines, per video: English once, with the need of each language
    jobs = []  # (pid, chapter title, chapter lines, {sid: caps}, {sid: {lang: (need, window, rate, tr)}})
    for pid in pids:
        p = project.get(pid)
        total = p.get("duration")
        per: dict[int, dict] = {}
        for lang in langs_of(pid):
            lines = project.sentences(pid, lang)
            rate = rate_of(pid, lang)
            for i, (s, f) in enumerate(zip(lines, fit.of_lines(lines, lang, rate, total))):
                if not (f and f["tight"]) or s["tr_locked"] or s["tr_provenance"] != "machine" \
                        or s["mode"] == "keep" or s["linked"]:
                    continue
                per.setdefault(s["id"], {})[lang] = {"need": f["need"], "win": fit.window(lines, i, total),
                                                     "rate": rate, "tr": s["tr"]}
        if not per:
            continue
        lines = project.sentences(pid)
        by_id = {s["id"]: s for s in lines}
        opts = {lang: project.options(pid, lang) for lang in langs_of(pid)}
        caps, todo = {}, {}
        for sid, need_by in per.items():
            c = fit.word_caps(len(by_id[sid]["text"].split()), max(v["need"] for v in need_by.values()))
            b = basis(model, by_id[sid]["text"], c)
            if all((opts[lang].get(sid) or [{}])[0].get("basis") == b for lang in need_by):
                rep["done_before"] += len(need_by)
                continue
            caps[sid], todo[sid] = c, need_by
        tight = sum(len(v) for v in per.values())  # lines × languages, like the verdicts below
        rep["tight"] += tight
        rep["videos"][p["uid"]] = {"tight": tight}
        for ch, clines in chapters.group(lines, chapters.ensure(pid)):
            ids = [s["id"] for s in clines if s["id"] in caps]
            for k in range(0, len(ids), CHUNK):
                part = ids[k:k + CHUNK]
                pos = [i for i, s in enumerate(clines) if s["id"] in part]
                ctx = clines[max(0, pos[0] - CONTEXT): pos[-1] + CONTEXT + 1]
                jobs.append({"pid": pid, "src": p["src_lang"], "title": ch.get("title") or "", "lines": ctx,
                             "caps": {sid: caps[sid] for sid in part}, "need": {sid: todo[sid] for sid in part},
                             "text": {sid: by_id[sid]["text"] for sid in part}})
    n = sum(len(j["caps"]) for j in jobs)
    job_of = {(j["pid"], sid): j for j in jobs for sid in j["caps"]}
    if not n:
        log(f"shortening: no line is too long to fit ({rep['tight']} tight, all done before)" if rep["tight"]
            else "shortening: every translation fits its place")
        rep["seconds"] = round(time.time() - t0, 1)
        return rep
    # 2. the model writes shorter English for every tight line in one session
    log(f"shortening {n} lines that are too long to fit, in {len(jobs)} requests, with {llm.MODELS[model]['name']}")
    sim = similarity or Embedder()
    srv = server or llm.Server(model, work, cache=cache, gpu=gpu, slots=8 if gpu is not None else 2, log=log)
    raw = open(raw_log, "w", encoding="utf-8") if raw_log else None
    raw_lock = threading.Lock()

    def ask(j):
        a = srv.chat([{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": prompt(j["title"], j["lines"], j["caps"])}],
                     max_tokens=120 * len(j["caps"]) + 200, full=True)
        got = parse_answer(a["text"], j["caps"])
        if raw:
            with raw_lock:
                raw.write(json.dumps({"ids": list(j["caps"]), "finish": a.get("finish"), "got": len(got),
                                      "answer": a["text"]}, ensure_ascii=False) + "\n")
        return got

    versions: dict[tuple[str, int], dict[str, str]] = {}
    why: list[str] = []
    t1 = time.time()
    try:
        with srv:
            for attempt in (1, 2):
                answers = srv.map(ask, jobs)
                left = []
                for j, ans in zip(jobs, answers):
                    if isinstance(ans, Exception):
                        why.append(f"{type(ans).__name__}: {str(ans)[:160]}")
                        ans = {}
                    for sid in j["caps"]:
                        if sid in ans:
                            versions[(j["pid"], sid)] = {"short_a": ans[sid]["a"], "short_b": ans[sid].get("b", "")}
                    missing = [sid for sid in j["caps"] if sid not in ans]
                    for k in range(0, len(missing), RETRY_CHUNK):  # asked again in smaller requests
                        part = missing[k:k + RETRY_CHUNK]
                        left.append(j | {"caps": {sid: j["caps"][sid] for sid in part}})
                if not left or attempt == 2:
                    break
                log(f"asking again for {sum(len(j['caps']) for j in left)} lines the model did not answer")
                jobs = left
    except Exception as e:
        log(f"shortening skipped: {str(e)[-400:]}")
        rep.update(error=str(e)[-400:], seconds=round(time.time() - t0, 1))
        return rep
    finally:
        if raw:
            raw.close()
    rep["failed"] = n - len(versions)
    if why:
        rep["errors"] = sorted(set(why))[:5]
        log("some requests failed: " + " | ".join(rep["errors"][:3]))
    gen_s = time.time() - t1
    rep.update(llm_seconds=round(gen_s, 1), tokens=srv.tokens, tokens_per_s=round(srv.tokens / gen_s, 1) if gen_s else None)
    # 3. meaning kept (English against English) and 4. the versions in every language
    keys = [(k, kind) for k, v in versions.items() for kind, text in v.items() if text]
    sims = dict(zip(keys, sim([(job_of[k]["text"][k[1]], versions[k][kind]) for k, kind in keys])))
    if getattr(sim, "error", None):
        log(f"meaning could not be checked ({sim.error}): shorter versions are kept as options only")
    translated: dict[tuple, str] = {}
    pairs_by = {}
    for (pid, sid), kind in keys:
        j = job_of[(pid, sid)]
        for lang in j["need"][sid]:
            pairs_by.setdefault((j["src"], lang), []).append((pid, sid, kind))
    for (src, lang), items in pairs_by.items():
        tr = translator(src, lang) if translator else project.GoogleBatchTranslator(src, lang, context=0)
        out = tr.translate([{"id": i, "text": versions[(pid, sid)][kind]} for i, (pid, sid, kind) in enumerate(items)])
        for i, key in enumerate(items):
            translated[(*key, lang)] = out.get(i, "")
    for (pid, sid), j in job_of.items():
        if (pid, sid) not in versions:
            continue
        for lang, v in j["need"][sid].items():
            rows = [{"kind": "google", "text": v["tr"], "source_text": j["text"][sid], "need": v["need"], "sim": 1.0}]
            for kind, eng in versions[(pid, sid)].items():
                text = translated.get((pid, sid, kind, lang), "")
                if eng and text:
                    rows.append({"kind": kind, "text": text, "source_text": eng, "sim": sims.get(((pid, sid), kind), 0.0),
                                 "need": fit.need(text, lang, v["rate"], v["win"])})
            b = basis(model, j["text"][sid], j["caps"][sid])
            for r in rows:
                r["basis"] = b
            pick, status = fit.choose(rows)
            rep[status] += 1
            project.set_options(pid, lang, sid, rows)
            if pick["kind"] != "google":
                project.set_translation(pid, sid, lang, pick["text"], provenance="machine")
    rep["seconds"] = round(time.time() - t0, 1)
    log(f"shortened: {rep['fits']} now fit, {rep['closer']} closer, {rep['too_long']} still too long"
        + (f", {rep['failed']} not answered (see shorten_raw.jsonl)" if rep["failed"] else "")
        + f" ({rep['seconds']:.0f} s; the model {rep['llm_seconds']:.0f} s at {rep['tokens_per_s'] or 0:.0f} tokens/s)")
    return rep
