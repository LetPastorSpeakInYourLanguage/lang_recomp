import { AudioLines, RefreshCw, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api, usePoll, type AppState, type Character, type Project, type Take, type VoiceLine } from "../api";
import LangBar, { langName, useLang } from "../shell/LangBar";
import { Button, Empty, ModeToggle, Panel, PlayButton, Progress, Segmented, SpeakerDot, Tag, stateTone } from "../ui";

/** Same ranking the worker uses to pick the best take. */
const takeScore = (t: Take) => (t.sim ?? 0) - 0.6 * (t.cer ?? 1) - 0.25 * Math.max(0, (t.dur ?? 1) - 1.15);

export default function Voice({ project, state, onChanged }: { project: Project; state: AppState | null; onChanged: () => void }) {
  const [lang, setLang] = useLang(project);
  const v = usePoll(() => api.voice(project.id, lang), [project.id, lang], 8000);
  const chars = usePoll(() => api.characters(project.id), [project.id]);
  const [order, setOrder] = useState<"time" | "worst">("time");
  const [target, setTarget] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const byLabel = useMemo(() => Object.fromEntries((chars.data ?? []).map((c) => [c.label, c])), [chars.data]);
  const data = v.data;
  const roots = state?.roots ?? [];
  const where = target || state?.active || "";

  if (!data) return <div className="p-16 text-11.5 text-faint">Loading…</div>;
  // lines of a confirmed recurring part are voiced once, at its origin
  const reused = data.lines.filter((l) => l.linked).length;
  const lines = data.lines.filter((l) => l.tr && !l.linked && (!l.speaker || byLabel[l.speaker]?.important !== 0));
  const bar = <LangBar project={project} lang={lang} onChange={setLang} onAdded={onChanged} />;
  if (!lines.length) {
    return (
      <div className="p-16 max-w-[1280px] mx-auto w-full flex flex-col gap-12">
        {bar}
        <Empty icon={<AudioLines size={28} />} title={`Nothing to voice in ${langName(lang)} yet`}>
          Translate the lines first (Translate), and make sure the speakers are marked as needing a dub (Characters).
        </Empty>
      </div>
    );
  }
  const chosen = (l: VoiceLine) => l.takes.find((t) => t.chosen && !t.stale) ?? null;
  const dubLines = lines.filter((l) => l.mode === "dub");
  const voiced = dubLines.filter((l) => chosen(l)).length;
  const keptCount = lines.length - dubLines.length;
  const running = data.jobs.find((j) => j.state === "running" || j.state === "claimed");
  const queued = data.jobs.find((j) => !j.state || j.state === "queued");
  const active = running ?? queued;
  const sorted = order === "time" ? lines : [...lines].sort((a, b) => {
    const s = (l: VoiceLine) => (chosen(l) ? takeScore(chosen(l)!) : -9);
    return s(a) - s(b);
  });

  async function queue(ids?: number[]) {
    setMsg(null);
    try {
      const r = await api.queueVoice(project.id, { root: where, ids, lang });
      setMsg(`Queued ${r.lines} line${r.lines === 1 ? "" : "s"} in ${roots.find((x) => x.id === r.root)?.name ?? r.root}.`);
      void v.reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function choose(t: Take) {
    await api.chooseTake(project.id, t.take_id);
    await v.reload();
    onChanged();
  }

  const e = data.engine;
  return (
    <div className="p-16 max-w-[1280px] mx-auto w-full flex flex-col gap-12">
      {bar}
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1 min-w-[300px]">
          <div className="text-15 font-semibold">Voice · {langName(lang)}</div>
          <div className="text-11.5 text-dim">
            Each line is spoken in its speaker's cloned voice, {e.takes} takes per line. Every take is scored for likeness to the
            speaker, how clearly the {langName(lang)} comes through, and fit to the original timing; the best is picked for you. Listen, swap
            takes, regenerate.{reused > 0 && ` ${reused} line${reused === 1 ? " belongs" : "s belong"} to recurring parts, voiced once at their origin and reused here.`}
          </div>
        </div>
        <Tag tone="accent">OmniVoice · {e.steps} steps · {e.speed}×</Tag>
        <Tag tone={voiced === dubLines.length ? "good" : "neutral"}>{voiced}/{dubLines.length} voiced</Tag>
        {keptCount > 0 && <Tag tone="cross" title="Lines kept in the original voice (interjections)">{keptCount} kept original</Tag>}
        {data.rate && <Tag title="Speaking rate measured from the chosen takes; the Translate meter uses it">{data.rate} syl/s</Tag>}
      </div>

      <Panel>
        <div className="px-12 py-9 flex items-center gap-8 flex-wrap text-11 text-dim">
          <span>Run on</span>
          <select className="field" value={where} onChange={(ev) => setTarget(ev.target.value)}>
            {roots.map((r) => <option key={r.id} value={r.id}>{r.name}{r.online ? " · worker online" : ""}</option>)}
          </select>
          <Button variant="primary" onClick={() => void queue()} disabled={!!active}><Wand2 size={12} />Voice all lines</Button>
          <Button onClick={() => void queue(dubLines.filter((l) => !chosen(l)).map((l) => l.id))} disabled={voiced === dubLines.length || !!active}>
            Voice missing & changed
          </Button>
          <div className="flex-1" />
          <Segmented<"time" | "worst"> value={order} onChange={setOrder}
            options={[{ value: "time", label: "In order" }, { value: "worst", label: "Worst first" }]} />
        </div>
        {active && (
          <div className="px-12 pb-9 flex items-center gap-8 text-11">
            <Tag tone={stateTone(active.state)}>{active.state ?? "queued"}</Tag>
            <div className="w-[220px]"><Progress value={active.progress ?? 0} /></div>
            <span className="text-dim">{running ? "voicing…" : "waiting for the worker of that folder (see Folders)"}</span>
          </div>
        )}
        {msg && <div className="px-12 pb-9 text-11 text-dim">{msg}</div>}
      </Panel>

      <div className="flex flex-col gap-6">
        {sorted.map((l) => (
          <Line key={l.id} l={l} c={l.speaker ? byLabel[l.speaker] : undefined} project={project}
            onChoose={(t) => void choose(t)} onRegenerate={() => void queue([l.id])} busy={!!active}
            onMode={async (m) => { await api.patchSentence(project.id, l.id, { mode: m }); await v.reload(); onChanged(); }} />
        ))}
      </div>
    </div>
  );
}

function Line({ l, c, project, onChoose, onRegenerate, busy, onMode }: {
  l: VoiceLine; c?: Character; project: Project; onChoose: (t: Take) => void; onRegenerate: () => void; busy: boolean;
  onMode: (m: "dub" | "keep" | "auto") => void;
}) {
  const takes = l.takes.filter((t) => !t.stale);
  const stale = l.takes.length > 0 && takes.length === 0;
  return (
    <div className="bg-panel border border-border rounded-3 px-12 py-8 grid grid-cols-[150px_1fr_auto] gap-10 items-start max-lg:grid-cols-1">
      <div className="flex items-center gap-6 min-w-0 pt-2">
        <PlayButton src={api.media(project.id, "audio")} start={l.start} end={l.end} k={`v-src-${l.id}`} size={18} />
        {c && <SpeakerDot color={c.color} />}
        <span className={`text-11.5 font-medium truncate ${c ? `text-s${c.color % 8}` : "text-faint"}`}>{c?.name ?? "unknown"}</span>
      </div>
      <div className="min-w-0">
        <div className="text-11.5 text-dim">{l.text}</div>
        <div className={`font-eth text-14 leading-relaxed ${l.mode === "keep" ? "opacity-45 line-through" : ""}`}>{l.tr}</div>
        <div className="mt-4"><ModeToggle mode={l.mode} set={l.mode_set} suggested={l.mode_suggested} onChange={onMode} /></div>
        {l.mode === "keep" ? (
          <div className="text-10.5 text-dim mt-5">The speaker's original voice plays here, and the subtitles show the original words.</div>
        ) : <div className="flex flex-wrap gap-6 mt-5">
          {takes.map((t) => <TakeChip key={t.take_id} t={t} project={project} slot={l.slot_s} onChoose={() => onChoose(t)} />)}
          {!takes.length && (
            <span className="text-10.5 text-faint">
              {stale ? "The translation changed after these takes were made: regenerate." : "Not voiced yet."}
            </span>
          )}
        </div>}
      </div>
      <Button variant="ghost" onClick={onRegenerate} disabled={busy || l.mode === "keep"} title="Make new takes for this line">
        <RefreshCw size={11} />Regenerate
      </Button>
    </div>
  );
}

function TakeChip({ t, project, slot, onChoose }: { t: Take; project: Project; slot: number; onChoose: () => void }) {
  const fit = t.dur ?? 0;
  const tone = (ok: boolean, warn: boolean) => (ok ? "text-good" : warn ? "text-warn" : "text-bad");
  return (
    <div onClick={onChoose} title="Click to use this take"
      className={`flex items-center gap-7 border rounded-3 px-7 py-4 cursor-pointer ${t.chosen ? "border-accent bg-soft" : "border-border bg-panel2 hover:border-border2"}`}>
      <PlayButton src={api.takeUrl(project.id, t.take_id)} start={0} end={9999} k={`take-${t.take_id}`} size={18} />
      <span className="text-10 font-mono text-dim">#{t.take + 1}</span>
      <span className={`text-10 font-mono ${tone((t.sim ?? 0) >= 0.85, (t.sim ?? 0) >= 0.75)}`} title="voice likeness (0–1)">
        sim {t.sim?.toFixed(2) ?? "–"}
      </span>
      <span className={`text-10 font-mono ${tone((t.cer ?? 1) <= 0.12, (t.cer ?? 1) <= 0.25)}`} title="character error rate when the take is transcribed back (– when the language has no aligner)">
        CER {t.cer != null ? `${Math.round(t.cer * 100)}%` : "–"}
      </span>
      <span className={`text-10 font-mono ${tone(fit <= 1.1, fit <= 1.3)}`} title={`${t.dur_s?.toFixed(1) ?? "?"}s for a ${slot.toFixed(1)}s slot`}>
        fit {fit ? `${fit.toFixed(2)}×` : "–"}
      </span>
      {!!t.chosen && <Tag tone="accent">using</Tag>}
    </div>
  );
}
