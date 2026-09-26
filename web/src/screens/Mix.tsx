import { Clapperboard, Download, FolderOpen, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, fmtTime, usePoll, type FitLine, type MixParams, type Project } from "../api";
import { go } from "../router";
import LangBar, { langName, useLang } from "../shell/LangBar";
import { Button, Empty, Panel, Progress, Segmented, Tag, stateTone } from "../ui";

type Listen = "mix" | "dub" | "original";
const STATUS: Record<FitLine["status"], { tone: "good" | "accent" | "warn" | "bad" | "neutral"; label: string; help: string }> = {
  fits: { tone: "good", label: "fits", help: "Plays inside the original line's time." },
  borrowed: { tone: "accent", label: "uses pause", help: "Runs into the silence around the line; no speed change." },
  stretched: { tone: "neutral", label: "sped up", help: "Slightly faster than spoken (inside the natural limit)." },
  squeezed: { tone: "warn", label: "squeezed", help: "Noticeably faster; consider a shorter translation." },
  overflow: { tone: "bad", label: "overflows", help: "Still too long at the hard limit: it overlaps the next line. Shorten the translation or regenerate." },
};

export default function Mix({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [lang, setLang] = useLang(project);
  const m = usePoll(() => api.mix(project.id, lang), [project.id, lang], 3000);
  const [listen, setListen] = useState<Listen>("mix");
  const [issuesOnly, setIssuesOnly] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const data = m.data;
  const rendering = data?.tasks.find((t) => t.kind === "mix" && t.state === "running");
  const exporting = data?.tasks.find((t) => t.kind === "export" && t.state === "running");
  const failed = data?.tasks.find((t) => t.state === "failed" && t.finished && (!data.mix_mtime || t.finished > data.mix_mtime));

  // The video carries the original sound; the Amharic mix / dub plays on a second
  // element kept in lock-step with it.
  useEffect(() => {
    const v = video.current;
    const a = audio.current;
    if (!v || !a) return;
    v.muted = listen !== "original";
    const sync = () => { if (listen !== "original" && Math.abs(a.currentTime - v.currentTime) > 0.08) a.currentTime = v.currentTime; };
    const play = () => { if (listen !== "original") { a.currentTime = v.currentTime; void a.play(); } };
    const pause = () => a.pause();
    v.addEventListener("play", play);
    v.addEventListener("pause", pause);
    v.addEventListener("seeked", sync);
    v.addEventListener("timeupdate", sync);
    if (listen === "original") a.pause(); else if (!v.paused) play();
    return () => { v.removeEventListener("play", play); v.removeEventListener("pause", pause); v.removeEventListener("seeked", sync); v.removeEventListener("timeupdate", sync); };
  }, [listen, data?.mix_mtime]);

  const rows = useMemo(() => (data?.summary?.lines ?? []).filter((l) => !issuesOnly || l.status === "squeezed" || l.status === "overflow"), [data, issuesOnly]);

  if (!data) return <div className="p-16 text-11.5 text-faint">Loading…</div>;
  const p = data.params;
  const c = data.summary?.counts ?? {};

  async function setParam(b: Partial<MixParams>) {
    await api.mixParams(project.id, b);
    void m.reload();
  }
  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try { await fn(); void m.reload(); } catch (e) { setErr((e as Error).message); }
  }
  const seek = (t: number) => { const v = video.current; if (v) { v.currentTime = Math.max(0, t - 0.3); void v.play(); } };

  return (
    <div className="p-16 max-w-[1280px] mx-auto w-full flex flex-col gap-12">
      <LangBar project={project} lang={lang} onChange={setLang} onAdded={onChanged} />
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1 min-w-[300px]">
          <div className="text-15 font-semibold">Mix & export · {langName(lang)}</div>
          <div className="text-11.5 text-dim">
            Each chosen take starts where the original line started. A take that runs long first uses the pause after it, then is sped up
            gently (voice character kept); lines that still do not fit are flagged below. Loudness follows the original line.
          </div>
        </div>
        {data.summary && (
          <>
            <Tag tone="good">{c.dubbed ?? 0} dubbed</Tag>
            {!!c.missing && <Tag tone="warn" title="Lines of dubbed characters with no usable take: the original voice plays">{c.missing} not voiced</Tag>}
            {!!c.extras && <Tag title="Characters not marked for dubbing keep their own voice">{c.extras} extras</Tag>}
            {!!c.kept && <Tag tone="cross" title="Interjections kept in the original voice">{c.kept} kept original</Tag>}
            {!!c.squeezed && <Tag tone="warn">{c.squeezed} squeezed</Tag>}
            {!!c.overflow && <Tag tone="bad">{c.overflow} overflow</Tag>}
          </>
        )}
      </div>

      {!data.has_mix && !rendering ? (
        <Panel>
          <Empty icon={<Clapperboard size={28} />} title="No mix yet">
            Render the mix to hear the dub over the background. Lines without a chosen take keep the original voice, so you can render at any point.
            <div className="mt-10"><Button variant="primary" onClick={() => void run(() => api.renderMix(project.id, lang))}><RefreshCw size={12} />Render mix</Button></div>
          </Empty>
        </Panel>
      ) : (
        <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(280px,1fr)] gap-12 max-lg:grid-cols-1">
          <Panel title="Preview" actions={<Segmented<Listen> value={listen} onChange={setListen}
            options={[{ value: "mix", label: `${langName(lang)} mix` }, { value: "dub", label: "Dub only" }, { value: "original", label: "Original" }]} />}>
            <div className="p-10">
              <video ref={video} src={api.media(project.id, "video")} controls className="w-full rounded-3 bg-black aspect-video" />
              <audio ref={audio} src={api.mixAudio(project.id, listen === "dub" ? "dub" : "mix", data.mix_mtime, lang)} preload="auto" />
              <div className="text-10.5 text-faint mt-6">Click a line below to jump there.</div>
            </div>
          </Panel>

          <Panel title="Mix settings" actions={
            <Button variant="primary" disabled={!!rendering} onClick={() => void run(() => api.renderMix(project.id, lang))}>
              <RefreshCw size={12} className={rendering ? "animate-spin" : ""} />{rendering ? "Rendering…" : "Render mix"}
            </Button>}>
            <div className="p-12 flex flex-col gap-10 text-11.5">
              <Num label="Lower the background under the dub" unit="dB" value={p.duck_db} min={0} max={15} step={1} onChange={(v) => void setParam({ duck_db: v })} />
              <Toggle label="Keep laughs, breaths and other non-speech sounds" value={p.keep_nonspeech} onChange={(v) => void setParam({ keep_nonspeech: v })}>
                {p.keep_nonspeech && <Num label="at" unit="dB" value={p.nonspeech_db} min={-24} max={0} step={1} onChange={(v) => void setParam({ nonspeech_db: v })} />}
              </Toggle>
              <Toggle label="Extras keep their original voice" value={p.keep_extras} onChange={(v) => void setParam({ keep_extras: v })} />
              <Toggle label="Follow the original line's loudness" value={p.loudness_follow} onChange={(v) => void setParam({ loudness_follow: v })} />
              <Num label="Natural speed-up limit" unit="%" value={Math.round((p.max_stretch - 1) * 100)} min={0} max={25} step={1}
                onChange={(v) => void setParam({ max_stretch: 1 + v / 100 })} />
              <Num label="Hard speed-up limit" unit="%" value={Math.round((p.hard_stretch - 1) * 100)} min={5} max={50} step={1}
                onChange={(v) => void setParam({ hard_stretch: 1 + v / 100 })} />
              {rendering && <div className="flex items-center gap-8"><div className="flex-1"><Progress value={rendering.progress} /></div><span className="text-10.5 text-dim">{rendering.note}</span></div>}
              {failed && <div className="text-11 text-bad">{failed.kind} failed: {failed.error}</div>}
              <div className="text-10.5 text-faint">Settings apply on the next render.</div>
            </div>
          </Panel>
        </div>
      )}

      {data.summary && (
        <Panel title={`Line fit · ${data.summary.lines.length}`} actions={
          <label className="flex items-center gap-6 text-11 text-dim normal-case tracking-normal">
            <input type="checkbox" checked={issuesOnly} onChange={(e) => setIssuesOnly(e.target.checked)} />problems only
          </label>}>
          <table className="w-full border-collapse text-11.5">
            <thead>
              <tr className="text-left text-9.5 uppercase tracking-label text-faint">
                {["Time", "Line", "Take", "Placed", "Speed", "Level", "Fit"].map((h) => <th key={h} className="px-10 py-5 font-semibold border-b border-border">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((l) => {
                const s = STATUS[l.status];
                return (
                  <tr key={l.id} onClick={() => seek(l.start)} className="border-b border-border last:border-0 cursor-pointer hover:bg-panel2 align-top">
                    <td className="px-10 py-5 font-mono text-dim">{fmtTime(l.slot_start)}</td>
                    <td className="px-10 py-5 max-w-[460px]"><div className="font-eth text-12.5">{l.tr}</div><div className="text-10.5 text-faint truncate">{l.src}</div>
                      {l.linked && <div className="text-9.5 text-cross">reused from {l.linked}</div>}</td>
                    <td className="px-10 py-5 font-mono">{l.dur.toFixed(1)}s<span className="text-faint"> / {(l.slot_end - l.slot_start).toFixed(1)}s</span></td>
                    <td className="px-10 py-5 font-mono text-dim">{fmtTime(l.start)}–{fmtTime(l.end)}</td>
                    <td className="px-10 py-5 font-mono">{l.factor > 1.001 ? `+${Math.round((l.factor - 1) * 100)}%` : "–"}</td>
                    <td className="px-10 py-5 font-mono text-dim">{l.gain_db > 0 ? "+" : ""}{l.gain_db} dB</td>
                    <td className="px-10 py-5" title={s.help}>
                      <Tag tone={s.tone}>{s.label}{l.overlap_s ? ` ${l.overlap_s.toFixed(1)}s` : ""}</Tag>
                      {l.status === "overflow" && (
                        <button onClick={(e) => { e.stopPropagation(); go(project.id, "translate"); }} className="block mt-3 bg-transparent border-0 p-0 text-10.5 text-accent">shorten translation</button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!rows.length && <tr><td colSpan={7} className="px-10 py-8 text-11 text-faint">{issuesOnly ? "No problem lines." : "No dubbed lines yet: voice some lines first."}</td></tr>}
            </tbody>
          </table>
        </Panel>
      )}

      <Panel title="Export">
        <div className="p-12 flex items-center gap-10 flex-wrap text-11.5">
          <Button variant="primary" disabled={!data.has_mix || !!exporting || !!rendering} onClick={() => void run(() => api.exportMix(project.id, lang))}>
            <Download size={12} />{exporting ? "Exporting…" : "Export MP4"}
          </Button>
          <span className="text-dim flex-1 min-w-[260px]">
            Video + {langName(lang)} dub (default audio) + original audio as a second track + {langName(lang)} and {langName(project.src_lang)} subtitle tracks, and .srt files.
          </span>
          {data.export && (
            <>
              <Tag tone={stateTone("done")}>exported</Tag>
              <span className="font-mono text-10.5 text-dim truncate max-w-[420px]" title={data.export.mp4}>{data.export.mp4.split(/[\\/]/).pop()}</span>
              <Button onClick={() => void api.openExport(project.id)}><FolderOpen size={12} />Open folder</Button>
            </>
          )}
          {err && <span className="text-11 text-bad w-full">{err}</span>}
        </div>
      </Panel>
    </div>
  );
}

function Num({ label, unit, value, min, max, step, onChange }: { label: string; unit: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <label className="flex items-center gap-8">
      <span className="flex-1">{label}</span>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => setV(Number(e.target.value))}
        onMouseUp={() => v !== value && onChange(v)} onKeyUp={() => v !== value && onChange(v)} onTouchEnd={() => v !== value && onChange(v)}
        className="w-[120px] accent-[var(--accent)]" />
      <span className="font-mono text-10.5 w-[48px] text-right">{v > 0 && unit === "%" ? "+" : ""}{v} {unit}</span>
    </label>
  );
}

function Toggle({ label, value, onChange, children }: { label: string; value: boolean; onChange: (v: boolean) => void; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <label className="flex items-center gap-8 cursor-pointer">
        <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
        <span className="flex-1">{label}</span>
      </label>
      {children && <div className="pl-20">{children}</div>}
    </div>
  );
}
