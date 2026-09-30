import { Languages, Lock, LockOpen, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, usePoll, type AppState, type Character, type Project, type Sentence } from "../api";
import LangBar, { langName, useLang } from "../shell/LangBar";
import { Button, Empty, LinkedTag, ModeToggle, Panel, PlayButton, SpeakerDot, Tag } from "../ui";

/** Google tends to pick masculine second-person forms; any line saying "you" to
 *  someone is worth checking against the listener's gender. */
const addressesSomeone = (en: string) => /\byou(r|rs|rself)?\b/i.test(en);

export default function Translate({ project, state, onChanged }: { project: Project; state: AppState | null; onChanged: () => void }) {
  const [lang, setLang] = useLang(project);
  const sents = usePoll(() => api.sentences(project.id, lang), [project.id, lang]);
  // Another language shown under each source line as a reference (a pivot): e.g. the
  // Amharic while translating into Tigrinya, when the team reads Amharic better than English.
  const [pivot, setPivot] = useState<string>("");
  const piv = usePoll(() => (pivot ? api.sentences(project.id, pivot) : Promise.resolve([])), [project.id, pivot]);
  const pivotOf = useMemo(() => Object.fromEntries((piv.data ?? []).map((s) => [s.id, s.tr])), [piv.data]);
  const chars = usePoll(() => api.characters(project.id), [project.id]);
  const chaps = usePoll(() => api.chapters(project.id), [project.id]);
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

  // Lines grouped under their chapter, in time order (chapters without lines are skipped).
  const chapters = (chaps.data ?? []).map((c) => ({ c, lines: rows.filter((s) => s.chapter === c.id) })).filter((g) => g.lines.length);
  const done = rows.filter((r) => r.tr).length;
  const over = rows.filter((r) => r.fit?.tight).length;

  return (
    <div className="p-16 max-w-[1280px] mx-auto w-full flex flex-col gap-12">
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1"><LangBar project={project} lang={lang} onChange={setLang} onAdded={onChanged} counts={project.counts.translated_by_lang} /></div>
        {project.targets.length > 1 && (
          <label className="flex items-center gap-5 text-11 text-dim" title="Show another language's translation under each source line, as a reference">
            Reference
            <select className="field" value={pivot} onChange={(e) => setPivot(e.target.value)}>
              <option value="">none</option>
              {project.targets.filter((t) => t !== lang).map((t) => <option key={t} value={t}>{t} · {langName(t)}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1 min-w-[300px]">
          <div className="text-15 font-semibold">{langName(project.src_lang)} → {langName(lang)}</div>
          <div className="text-11.5 text-dim">
            Each chapter is translated as one piece of context. The meter compares the translation's spoken length (syllables) with the time the
            original line takes. Editing a line locks it, so re-translating never overwrites your wording.
          </div>
        </div>
        <Tag tone={done === rows.length ? "good" : "neutral"}>{done}/{rows.length} translated</Tag>
        {over > 0 && <Tag tone="warn" title={`Estimated ${langName(lang)} length needs more than a 1.25× speed-up to fit between its neighbours`}>{over} too long</Tag>}
        {err && <span className="text-11 text-bad">{err}</span>}
        <Button variant="primary" disabled={running} onClick={() => void translate()}>
          <RefreshCw size={11} className={running ? "animate-spin" : ""} />{running ? "Translating…" : done ? "Re-translate unlocked" : "Translate all"}
        </Button>
      </div>

      {chapters.map(({ c, lines }) => (
        <Panel key={c.id} title={`Chapter ${c.index + 1}${c.title ? ` · ${c.title}` : ""} · ${lines.length} lines`}
          actions={<Button variant="ghost" disabled={running} onClick={() => void translate(c.id)}><RefreshCw size={11} />Re-translate chapter</Button>}>
          <div className="divide-y divide-border">
            {lines.map((s) => <Line key={s.id} s={s} c={s.speaker ? byLabel[s.speaker] : undefined} project={project} lang={lang}
              pivot={pivot ? { lang: pivot, text: pivotOf[s.id] ?? "" } : null} onPatch={(b) => void patch(s, b)} />)}
          </div>
        </Panel>
      ))}
    </div>
  );
}

function Line({ s, c, project, lang, pivot, onPatch }: {
  s: Sentence; c?: Character; project: Project; lang: string; pivot: { lang: string; text: string } | null;
  onPatch: (b: Parameters<typeof api.patchSentence>[2]) => void;
}) {
  const [draft, setDraft] = useState(s.tr);
  useEffect(() => setDraft(s.tr), [s.tr]);
  // the speed-up the line would need in its window: up to 1.12 is free, to 1.25 squeezed, beyond it overflows
  const r = s.fit?.need ?? null;
  const tone = r == null ? "bg-faint" : r <= 1.12 ? "bg-good" : r <= 1.25 ? "bg-warn" : "bg-bad";
  return (
    <div className="grid grid-cols-[130px_1fr_1.2fr_150px] gap-10 px-12 py-8 items-start max-lg:grid-cols-[1fr]">
      <div className="flex items-center gap-6 min-w-0 pt-2">
        <PlayButton src={api.media(project.id, "audio")} start={s.start} end={s.end} k={`t-${s.id}`} size={18} />
        {c && <SpeakerDot color={c.color} />}
        <span className={`text-11.5 font-medium truncate ${c ? `text-s${c.color % 8}` : "text-faint"}`}>{c?.name ?? "unknown"}</span>
      </div>
      <div className="flex flex-col gap-4 pt-2">
        <div className="text-12 leading-relaxed text-dim">{s.text}</div>
        {pivot && <div lang={pivot.lang} className="font-eth text-12.5 leading-relaxed text-cross" title={`${langName(pivot.lang)} (reference)`}>
          {pivot.text || <span className="text-faint">— no {langName(pivot.lang)} yet</span>}</div>}
        <ModeToggle mode={s.mode} set={s.mode_set} suggested={s.mode_suggested} onChange={(m) => onPatch({ mode: m })} />
      </div>
      <div className={`flex flex-col gap-4 ${s.mode === "keep" ? "opacity-45" : ""}`}
        title={s.mode === "keep" ? "Kept in the original language: this translation is not voiced" : ""}>
        {s.linked ? (
          <>
            <div lang={lang} className="font-eth text-14 leading-relaxed text-dim px-6 py-4 border border-dashed border-border2 rounded-2">{s.tr || "—"}</div>
            <span><LinkedTag linked={s.linked} /></span>
          </>
        ) : (
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={Math.max(1, Math.ceil(draft.length / 48))}
            onBlur={() => draft.trim() !== s.tr && onPatch({ tr: draft.trim() })}
            placeholder="—" lang={lang}
            className="field h-auto py-4 font-eth text-14 leading-relaxed resize-none w-full" />
        )}
        {addressesSomeone(s.text) && s.tr && <span className="text-10 text-warn">Check the “you” form matches who is being spoken to.</span>}
        {s.options.length > 0 && !s.linked && <Versions s={s} lang={lang} onUse={(text) => onPatch({ tr: text })} />}
      </div>
      <div className="flex flex-col gap-4 pt-3">
        <div className="flex items-center gap-6">
          <div className="flex-1 h-5 bg-panel3 rounded-full overflow-hidden relative">
            <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, (r ?? 0) * 64)}%` }} />
            <div className="absolute top-0 bottom-0 w-px bg-text opacity-40" style={{ left: `${1.12 * 64}%` }} title="fits (up to 1.12× faster)" />
            <div className="absolute top-0 bottom-0 w-px bg-bad opacity-60" style={{ left: `${1.25 * 64}%` }} title="the mix's hardest squeeze (1.25×)" />
          </div>
          <button onClick={() => onPatch({ tr_locked: !s.tr_locked })} title={s.tr_locked ? "Locked — re-translate skips it" : "Unlocked"}
            className={`bg-transparent border-0 p-0 ${s.tr_locked ? "text-accent" : "text-faint"}`}>
            {s.tr_locked ? <Lock size={12} /> : <LockOpen size={12} />}
          </button>
        </div>
        <span className="text-9.5 font-mono text-faint">
          {s.budget ? `${s.budget.syllables} syl · ~${s.budget.est_s}s / ${s.slot_s.toFixed(1)}s` : `${s.slot_s.toFixed(1)}s slot`}
          {r != null && ` · ${r.toFixed(2)}×`}
        </span>
      </div>
    </div>
  );
}

const VERSION_LABEL = { google: "As translated", short_a: "Shorter English", short_b: "Shortest English" } as const;

/** A line whose first translation was too long for its place: Google's own and Google's
 *  translation of shorter English written by the run's local model (decision 47). */
function Versions({ s, lang, onUse }: { s: Sentence; lang: string; onUse: (text: string) => void }) {
  return (
    <div className="flex flex-col gap-4 border-l-2 border-border2 pl-8 mt-2">
      <span className="text-10 text-faint">Too long to fit as first translated: shorter versions</span>
      {s.options.map((o) => {
        const inUse = o.text === s.tr;
        return (
          <div key={o.kind} className="flex items-start gap-6">
            <div className="flex-1 min-w-0">
              <div lang={lang} className={`font-eth text-12.5 leading-relaxed ${inUse ? "" : "text-dim"}`}>{o.text}</div>
              <div className="text-10 text-faint">{VERSION_LABEL[o.kind]} · {o.source_text}</div>
            </div>
            <span className="text-9.5 font-mono text-faint whitespace-nowrap pt-2" title="speed-up it needs to fit · meaning of the English kept">
              {o.need != null ? `${o.need.toFixed(2)}×` : "–"}{o.kind !== "google" && o.sim != null ? ` · ${Math.round(o.sim * 100)}%` : ""}
            </span>
            {inUse ? <Tag tone="good">in use</Tag> : <Button variant="ghost" onClick={() => onUse(o.text)}>Use</Button>}
          </div>
        );
      })}
    </div>
  );
}
