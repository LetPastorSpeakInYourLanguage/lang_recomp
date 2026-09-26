import { Download, FolderOpen } from "lucide-react";
import { useState } from "react";
import { api, fmtTime, parseTime, type Project } from "../api";
import { go } from "../router";
import { Button, Panel, Tag, stateTone } from "../ui";

export default function Home({ projects, reload }: { projects: Project[]; reload: () => void }) {
  const [source, setSource] = useState("");
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [maxSpk, setMaxSpk] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const isUrl = /^https?:\/\//.test(source.trim());

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const p = await api.create({
        name: name.trim() || (isUrl ? "YouTube clip" : source.split(/[\\/]/).pop() || "Untitled"),
        source: source.trim(),
        clip_start: parseTime(start),
        clip_end: parseTime(end),
        max_speakers: maxSpk ? Number(maxSpk) : null,
      });
      reload();
      go(p.id, "overview");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-16 max-w-[1100px] mx-auto w-full flex flex-col gap-14">
      <Panel title="New dubbing project">
        <form className="p-14 grid gap-12" onSubmit={(e) => { e.preventDefault(); if (source.trim()) void submit(); }}>
          <label className="grid gap-4">
            <span className="label">Source — YouTube link or a video file path on this PC</span>
            <div className="flex items-center gap-8">
              {isUrl ? <Download size={14} className="text-accent" /> : <FolderOpen size={14} className="text-faint" />}
              <input className="field flex-1 h-28 text-12" value={source} onChange={(e) => setSource(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=…   or   D:\videos\talk.mp4" autoFocus />
            </div>
          </label>
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr] gap-10 max-md:grid-cols-2">
            <label className="grid gap-4"><span className="label">Name</span>
              <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="optional" /></label>
            <label className="grid gap-4"><span className="label">Clip from</span>
              <input className="field font-mono" value={start} onChange={(e) => setStart(e.target.value)} placeholder="0:00" /></label>
            <label className="grid gap-4"><span className="label">Clip to</span>
              <input className="field font-mono" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="end" /></label>
            <label className="grid gap-4"><span className="label">Max speakers</span>
              <input className="field font-mono" value={maxSpk} onChange={(e) => setMaxSpk(e.target.value.replace(/\D/g, ""))} placeholder="auto" /></label>
          </div>
          <div className="flex items-center gap-10">
            <Tag tone="accent">English → Amharic</Tag>
            <span className="text-11 text-dim flex-1">
              Downloads and extracts audio here, then queues separation, transcription and speaker detection for the Colab GPU worker.
            </span>
            {err && <span className="text-11 text-bad">{err}</span>}
            <Button type="submit" variant="primary" disabled={!source.trim() || busy}>{busy ? "Creating…" : "Create & analyze"}</Button>
          </div>
        </form>
      </Panel>

      <Panel title={`Projects · ${projects.length}`}>
        {projects.length === 0 ? (
          <div className="p-14 text-11.5 text-faint">Nothing yet — start with a short clip (1–3 minutes) while you tune voices.</div>
        ) : (
          <table className="w-full border-collapse text-11.5">
            <thead>
              <tr className="text-left text-9.5 uppercase tracking-label text-faint">
                {["Project", "Length", "Analysis", "Lines", "Translated", "Characters"].map((h) => <th key={h} className="px-12 py-6 font-semibold border-b border-border">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} onClick={() => go(p.id)} className="cursor-pointer hover:bg-panel2 border-b border-border last:border-0">
                  <td className="px-12 py-7"><div className="font-medium">{p.name}</div><div className="text-10 text-faint font-mono truncate max-w-[380px]">{p.source}</div></td>
                  <td className="px-12 font-mono">{fmtTime(p.duration)}</td>
                  <td className="px-12"><div className="flex gap-3">{(["separate", "asr", "diarize"] as const).map((s) => <Tag key={s} tone={stateTone(p.analysis[s])}>{s}</Tag>)}</div></td>
                  <td className="px-12 font-mono">{p.counts.sentences}</td>
                  <td className="px-12 font-mono">{p.counts.translated}/{p.counts.sentences}</td>
                  <td className="px-12 font-mono">{p.counts.characters}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
