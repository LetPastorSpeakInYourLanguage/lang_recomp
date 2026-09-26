import { Languages, Lock, LockOpen, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, usePoll, type AppState, type Character, type Project, type Sentence } from "../api";
import LangBar, { langName, useLang } from "../shell/LangBar";
import { Button, Empty, ModeToggle, Panel, PlayButton, SpeakerDot, Tag } from "../ui";

/** Google tends to pick masculine second-person forms; any line saying "you" to
 *  someone is worth checking against the listener's gender. */
const addressesSomeone = (en: string) => /\byou(r|rs|rself)?\b/i.test(en);

export default function Translate({ project, state, onChanged }: { project: Project; state: AppState | null; onChanged: () => void }) {
  const [lang, setLang] = useLang(project);
  const sents = usePoll(() => api.sentences(project.id, lang), [project.id, lang]);
  const chars = usePoll(() => api.characters(project.id), [project.id]);
  const rows = sents.data ?? [];
  const byLabel = useMemo(() => Object.fromEntries((chars.data ?? []).map((c) => [c.label, c])), [chars.data]);
  const running = !!state?.tasks.some((t) => t.project_id === project.id && t.kind === "translate");
  const [err, setErr] = useState<string | null>(null);

  // While a translation runs, refresh lines as they land.
  useEffect(() => {
    if (!running) { void sents.reload(); onChanged(); return; }
    const t = setInterval(() => void sents.reload(), 1500);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  async function translate(chapter?: number) {
    setErr(null);
    try { await api.translate(project.id, lang, chapter); } catch (e) { setErr((e as Error).message); }
  }

  async function patch(s: Sentence, b: Parameters<typeof api.patchSentence>[2]) {
    const u = await api.patchSentence(project.id, s.id, { ...b, lang });
    sents.setData(rows.map((r) => (r.id === s.id ? u : r)));
    onChanged();
  }

  if (sents.data && !rows.length) {
    return <Empty icon={<Languages size={28} />} title="Nothing to translate yet">Load the analysis results and check the transcript first.</Empty>;
  }

  const chapters: Sentence[][] = [];
  rows.forEach((s, i) => { if (i === 0 || s.chapter_break) chapters.push([]); chapters[chapters.length - 1].push(s); });
  const done = rows.filter((r) => r.tr).length;
  const over = rows.filter((r) => (r.budget?.ratio ?? 0) > 1.25).length;

  return (
    <div className="p-16 max-w-[1280px] mx-auto w-full flex flex-col gap-12">
      <LangBar project={project} lang={lang} onChange={setLang} onAdded={onChanged} counts={project.counts.translated_by_lang} />
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1 min-w-[300px]">
          <div className="text-15 font-semibold">{langName(project.src_lang)} → {langName(lang)}</div>
          <div className="text-11.5 text-dim">
            Each chapter is translated as one piece of context. The meter compares the translation's spoken length (syllables) with the time the
            original line takes. Editing a line locks it, so re-translating never overwrites your wording.
          </div>
        </div>
        <Tag tone={done === rows.length ? "good" : "neutral"}>{done}/{rows.length} translated</Tag>
        {over > 0 && <Tag tone="warn" title="Estimated Amharic length is over 125% of the source slot">{over} too long</Tag>}
        {err && <span className="text-11 text-bad">{err}</span>}
        <Button variant="primary" disabled={running} onClick={() => void translate()}>
          <RefreshCw size={11} className={running ? "animate-spin" : ""} />{running ? "Translating…" : done ? "Re-translate unlocked" : "Translate all"}
        </Button>
      </div>

      {chapters.map((ch, ci) => (
        <Panel key={ci} title={`Chapter ${ci + 1} · ${ch.length} lines`}
          actions={<Button variant="ghost" disabled={running} onClick={() => void translate(ci)}><RefreshCw size={11} />Re-translate chapter</Button>}>
          <div className="divide-y divide-border">
            {ch.map((s) => <Line key={s.id} s={s} c={s.speaker ? byLabel[s.speaker] : undefined} project={project} lang={lang} onPatch={(b) => void patch(s, b)} />)}
          </div>
        </Panel>
      ))}
    </div>
  );
}

function Line({ s, c, project, lang, onPatch }: {
  s: Sentence; c?: Character; project: Project; lang: string; onPatch: (b: Parameters<typeof api.patchSentence>[2]) => void;
}) {
  const [draft, setDraft] = useState(s.tr);
  useEffect(() => setDraft(s.tr), [s.tr]);
  const r = s.budget?.ratio ?? null;
  const tone = r == null ? "bg-faint" : r <= 1.05 ? "bg-good" : r <= 1.25 ? "bg-warn" : "bg-bad";
  return (
    <div className="grid grid-cols-[130px_1fr_1.2fr_150px] gap-10 px-12 py-8 items-start max-lg:grid-cols-[1fr]">
      <div className="flex items-center gap-6 min-w-0 pt-2">
        <PlayButton src={api.media(project.id, "audio")} start={s.start} end={s.end} k={`t-${s.id}`} size={18} />
        {c && <SpeakerDot color={c.color} />}
        <span className={`text-11.5 font-medium truncate ${c ? `text-s${c.color % 8}` : "text-faint"}`}>{c?.name ?? "unknown"}</span>
      </div>
      <div className="flex flex-col gap-4 pt-2">
        <div className="text-12 leading-relaxed text-dim">{s.text}</div>
        <ModeToggle mode={s.mode} set={s.mode_set} suggested={s.mode_suggested} onChange={(m) => onPatch({ mode: m })} />
      </div>
      <div className={`flex flex-col gap-4 ${s.mode === "keep" ? "opacity-45" : ""}`}
        title={s.mode === "keep" ? "Kept in the original language: this translation is not voiced" : ""}>
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={Math.max(1, Math.ceil(draft.length / 48))}
          onBlur={() => draft.trim() !== s.tr && onPatch({ tr: draft.trim() })}
          placeholder="—" lang={lang}
          className="field h-auto py-4 font-eth text-14 leading-relaxed resize-none w-full" />
        {addressesSomeone(s.text) && s.tr && <span className="text-10 text-warn">Check the “you” form matches who is being spoken to.</span>}
      </div>
      <div className="flex flex-col gap-4 pt-3">
        <div className="flex items-center gap-6">
          <div className="flex-1 h-5 bg-panel3 rounded-full overflow-hidden relative">
            <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, (r ?? 0) * 80)}%` }} />
            <div className="absolute top-0 bottom-0 w-px bg-text opacity-40" style={{ left: "80%" }} title="fits the slot" />
          </div>
          <button onClick={() => onPatch({ tr_locked: !s.tr_locked })} title={s.tr_locked ? "Locked — re-translate skips it" : "Unlocked"}
            className={`bg-transparent border-0 p-0 ${s.tr_locked ? "text-accent" : "text-faint"}`}>
            {s.tr_locked ? <Lock size={12} /> : <LockOpen size={12} />}
          </button>
        </div>
        <span className="text-9.5 font-mono text-faint">
          {s.budget ? `${s.budget.syllables} syl · ~${s.budget.est_s}s / ${s.slot_s.toFixed(1)}s` : `${s.slot_s.toFixed(1)}s slot`}
        </span>
      </div>
    </div>
  );
}
