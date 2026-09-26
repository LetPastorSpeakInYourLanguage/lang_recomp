import { Library, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api, fmtTime, type Project, type Series, type SeriesKind } from "../api";
import { go, goSeries } from "../router";
import VideoForm, { LangOptions } from "../shell/VideoForm";
import { Button, Panel, Tag, stateTone } from "../ui";

const KIND_HINT: Record<SeriesKind, string> = {
  show: "episodes of a show or film series",
  channel: "a podcast or YouTube channel / playlist",
  speaker: "talks, sermons or teachings by one person",
  course: "lessons from an education channel",
  news: "news segments with recurring anchors",
  other: "any group of videos worked on together",
};

const codes = (v: string) => v.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);

export default function Home({ projects, series, reload }: { projects: Project[]; series: Series[]; reload: () => void }) {
  const [adding, setAdding] = useState(false);
  const [src, setSrc] = useState("en");
  const [tgt, setTgt] = useState("am");
  const standalone = projects.filter((p) => p.standalone);

  return (
    <div className="p-16 max-w-[1100px] mx-auto w-full flex flex-col gap-14">
      <LangOptions />
      <Panel title={`Series · ${series.length}`}
        actions={!adding && <Button variant="primary" onClick={() => setAdding(true)}><Plus size={12} />New series</Button>}>
        {adding && <NewSeries onDone={(s) => { setAdding(false); reload(); if (s) goSeries(s.id); }} />}
        {series.length === 0 && !adding ? (
          <div className="p-14 text-11.5 text-faint">
            A series groups videos that are dubbed together — a show's episodes, a channel, one speaker's talks, a course,
            a news programme. New videos in it take its languages and settings.
          </div>
        ) : (
          <div className="p-12 grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-10">
            {series.map((s) => (
              <button key={s.id} onClick={() => goSeries(s.id)}
                className="text-left bg-panel2 hover:bg-panel3 border border-border rounded-3 p-10 flex flex-col gap-6">
                <div className="flex items-center gap-6"><Library size={13} className="text-accent" />
                  <span className="text-12.5 font-semibold flex-1 truncate">{s.name}</span><Tag>{s.label}</Tag></div>
                <div className="text-10 font-mono text-dim">{s.src_lang}→{s.targets.join(",")}</div>
                <div className="text-10.5 text-dim">{s.counts?.sources ?? 0} {s.unit}{s.counts?.sources === 1 ? "" : "s"} · {fmtTime(s.counts?.duration ?? 0)}</div>
              </button>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Single video">
        <VideoForm submitLabel="Create & analyze"
          onSubmit={async (v) => { const p = await api.create({ ...v, src_lang: src.trim().toLowerCase(), tgt_lang: tgt.trim().toLowerCase() }); reload(); go(p.id, "overview"); }}
          note="Downloads and extracts audio here, then queues separation, transcription and speaker detection on the active worker."
          extra={<span className="flex items-center gap-5 text-11 text-dim">
            <input list="lb-langs-all" className="field font-mono w-[64px]" value={src} onChange={(e) => setSrc(e.target.value)} title="spoken language" />
            →
            <input list="lb-langs-all" className="field font-mono w-[64px]" value={tgt} onChange={(e) => setTgt(e.target.value)} title="dub into" />
          </span>} />
      </Panel>

      <Panel title={`Standalone videos · ${standalone.length}`}>
        {standalone.length === 0 ? (
          <div className="p-14 text-11.5 text-faint">Nothing yet — start with a short clip (1–3 minutes) while you tune voices.</div>
        ) : (
          <table className="w-full border-collapse text-11.5">
            <thead>
              <tr className="text-left text-9.5 uppercase tracking-label text-faint">
                {["Video", "Length", "Analysis", "Lines", "Translated", "Characters", "Series"].map((h) => <th key={h} className="px-12 py-6 font-semibold border-b border-border">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {standalone.map((p) => (
                <tr key={p.id} onClick={() => go(p.id)} className="cursor-pointer hover:bg-panel2 border-b border-border last:border-0">
                  <td className="px-12 py-7"><div className="font-medium">{p.name}</div><div className="text-10 text-faint font-mono truncate max-w-[340px]">{p.source}</div></td>
                  <td className="px-12 font-mono">{fmtTime(p.duration)}</td>
                  <td className="px-12"><div className="flex gap-3">{(["separate", "asr", "diarize"] as const).map((s) => <Tag key={s} tone={stateTone(p.analysis[s])}>{s}</Tag>)}</div></td>
                  <td className="px-12 font-mono">{p.counts.sentences}</td>
                  <td className="px-12 font-mono">{p.counts.translated}/{p.counts.sentences}</td>
                  <td className="px-12 font-mono">{p.counts.characters}</td>
                  <td className="px-12" onClick={(e) => e.stopPropagation()}>
                    {series.length > 0 && (
                      <select className="field h-22 text-10.5" value="" title="Move this video into a series"
                        onChange={async (e) => { if (e.target.value) { await api.attachProject(p.id, e.target.value); reload(); } }}>
                        <option value="">Move to…</option>
                        {series.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function NewSeries({ onDone }: { onDone: (s: Series | null) => void }) {
  const [kinds, setKinds] = useState<{ kind: SeriesKind; label: string; unit: string }[]>([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<SeriesKind>("channel");
  const [src, setSrc] = useState("en");
  const [targets, setTargets] = useState("am");
  const [feed, setFeed] = useState("");
  const [maxSpk, setMaxSpk] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { void api.seriesKinds().then(setKinds); }, []);

  async function create() {
    setErr(null);
    try {
      const s = await api.createSeries({
        name: name.trim(), kind, src_lang: src.trim().toLowerCase(), targets: codes(targets), feed_url: feed.trim() || null,
        settings: maxSpk ? { max_speakers: Number(maxSpk) } : {},
      });
      onDone(s);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <form className="p-14 grid gap-10 border-b border-border bg-panel2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void create(); }}>
      <div className="grid grid-cols-[2fr_1fr] gap-10 max-md:grid-cols-1">
        <label className="grid gap-4"><span className="label">Name</span>
          <input className="field" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sunday teachings" /></label>
        <label className="grid gap-4"><span className="label">Kind</span>
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value as SeriesKind)}>
            {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select></label>
      </div>
      <div className="text-10.5 text-faint -mt-4">{KIND_HINT[kind]}</div>
      <div className="grid grid-cols-[1fr_2fr_1fr] gap-10 max-md:grid-cols-1">
        <label className="grid gap-4"><span className="label">Spoken language</span>
          <input list="lb-langs-all" className="field font-mono" value={src} onChange={(e) => setSrc(e.target.value)} /></label>
        <label className="grid gap-4"><span className="label">Dub into (codes, first is primary)</span>
          <input list="lb-langs-all" className="field font-mono" value={targets} onChange={(e) => setTargets(e.target.value)} placeholder="am, om, ti" /></label>
        <label className="grid gap-4"><span className="label">Max speakers</span>
          <input className="field font-mono" value={maxSpk} onChange={(e) => setMaxSpk(e.target.value.replace(/\D/g, ""))} placeholder="auto" /></label>
      </div>
      <label className="grid gap-4"><span className="label">Channel or playlist link (optional, to pick videos from)</span>
        <input className="field" value={feed} onChange={(e) => setFeed(e.target.value)} placeholder="https://www.youtube.com/@channel  or  …/playlist?list=…" /></label>
      <div className="flex items-center gap-8">
        <span className="flex-1" />
        {err && <span className="text-11 text-bad">{err}</span>}
        <Button variant="ghost" onClick={() => onDone(null)}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!name.trim()}>Create series</Button>
      </div>
    </form>
  );
}
