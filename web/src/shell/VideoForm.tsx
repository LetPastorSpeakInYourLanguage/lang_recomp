import { Download, FolderOpen } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, parseTime, type NewVideo } from "../api";
import { Button } from "../ui";

let catalogue: { code: string; name: string }[] | null = null;

/** A `<datalist id="lb-langs-all">` of known languages, for any language-code field. */
export function LangOptions() {
  const [list, setList] = useState(catalogue ?? []);
  useEffect(() => {
    if (!catalogue) void api.languages().then((l) => { catalogue = l; setList(l); });
  }, []);
  return <datalist id="lb-langs-all">{list.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</datalist>;
}

/** One video to add: a YouTube link or a file on this PC, an optional clip range. The
 *  caller supplies what surrounds it (language fields for a standalone video, nothing
 *  for a series source, which takes the series' languages). */
export default function VideoForm({ onSubmit, submitLabel, note, extra }: {
  onSubmit: (v: NewVideo) => Promise<void>; submitLabel: string; note: ReactNode; extra?: ReactNode;
}) {
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
      await onSubmit({
        name: name.trim() || (isUrl ? "YouTube clip" : source.split(/[\\/]/).pop() || "Untitled"),
        source: source.trim(),
        clip_start: parseTime(start),
        clip_end: parseTime(end),
        max_speakers: maxSpk ? Number(maxSpk) : null,
      });
      setSource(""); setName(""); setStart(""); setEnd("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="p-14 grid gap-12" onSubmit={(e) => { e.preventDefault(); if (source.trim()) void submit(); }}>
      <label className="grid gap-4">
        <span className="label">Source — YouTube link or a video file path on this PC</span>
        <div className="flex items-center gap-8">
          {isUrl ? <Download size={14} className="text-accent" /> : <FolderOpen size={14} className="text-faint" />}
          <input className="field flex-1 h-28 text-12" value={source} onChange={(e) => setSource(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=…   or   D:\videos\talk.mp4" />
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
      <div className="flex items-center gap-10 flex-wrap">
        {extra}
        <span className="text-11 text-dim flex-1 min-w-[200px]">{note}</span>
        {err && <span className="text-11 text-bad">{err}</span>}
        <Button type="submit" variant="primary" disabled={!source.trim() || busy}>{busy ? "Adding…" : submitLabel}</Button>
      </div>
    </form>
  );
}
