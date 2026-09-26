import { ChevronDown, ChevronRight, FileText, FolderSearch, HardDrive, Library as LibIcon, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, fmtTime, usePoll, type AppState, type LibraryWork } from "../api";
import { go } from "../router";
import RunPanel from "../shell/RunPanel";
import { Button, Empty, Panel, Tag } from "../ui";

/** A folder of videos on a device, as its works: explore, play from where it is, run. */
export default function Library({ id, state, onChanged }: { id: string; state: AppState | null; onChanged: () => void }) {
  const lib = usePoll(() => api.library(id), [id]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (lib.error) return <Empty icon={<LibIcon size={28} />} title="No such library">{lib.error}</Empty>;
  if (!lib.data) return <div className="p-16 text-11.5 text-faint">Loading…</div>;
  const L = lib.data;
  const dev = state?.roots.find((r) => r.id === L.root_id);
  const works = L.works.filter((w) => !q.trim() || `${w.name} ${w.videos.map((v) => v.name).join(" ")}`.toLowerCase().includes(q.toLowerCase()));
  const total = L.works.reduce((n, w) => n + w.videos.length, 0);
  const subs = L.works.reduce((n, w) => n + w.with_subtitles, 0);
  const toggle = <T,>(s: Set<T>, v: T) => { const n = new Set(s); if (n.has(v)) n.delete(v); else n.add(v); return n; };
  const pickWork = (w: LibraryWork, on: boolean) => {
    const n = new Set(picked);
    w.videos.forEach((v) => (on ? n.add(v.id) : n.delete(v.id)));
    setPicked(n);
  };
  async function run(fn: () => Promise<string>) {
    setBusy(true); setMsg(null);
    try { setMsg(await fn()); await lib.reload(); onChanged(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="p-16 max-w-[1200px] mx-auto w-full flex flex-col gap-12">
      <div className="flex items-start gap-10 flex-wrap">
        <div className="flex-1 min-w-[280px]">
          <div className="text-15 font-semibold flex items-center gap-8"><LibIcon size={15} className="text-accent" />{L.name}</div>
          <div className="text-11 text-dim flex items-center gap-6 flex-wrap">
            <HardDrive size={11} /><span className="font-mono">{L.path}</span>
            <Tag>{dev?.name ?? L.root_id}</Tag>
            <span>{L.works.length} works · {total} videos · {subs} with subtitles · spoken {L.src_lang} → {L.targets.join(", ")}</span>
          </div>
        </div>
        <Button disabled={busy} onClick={() => void run(async () => {
          const r = await api.scanLibrary(id); return `Scanned: ${r.new_videos} new video(s) in ${r.new_works} new work(s).`;
        })}><RefreshCw size={12} />Scan</Button>
        {subs > 0 && <Button disabled={busy} onClick={() => void run(async () => {
          const r = await api.loadSubtitles(id); return `Loaded lines from ${r.loaded} subtitle file(s)${r.failed.length ? `; ${r.failed.length} could not be read` : ""}.`;
        })}><FileText size={12} />Load subtitles</Button>}
      </div>
      {msg && <div className="text-11.5">{msg}</div>}

      <RunPanel owner={`library:${id}`} videos={[...picked]} name={L.name} state={state} fixedRoot={L.root_id} onOpened={() => void lib.reload()} />

      <Panel title={`Works · ${works.length}`} actions={<input className="field w-[220px]" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search works and videos" />}>
        {!L.works.length && <div className="p-14 text-11.5 text-faint flex items-center gap-6"><FolderSearch size={14} />Nothing yet: put videos in the folder (see docs/LIBRARY_FOLDERS.md) and press Scan.</div>}
        <div className="divide-y divide-border">
          {works.map((w) => {
            const isOpen = open.has(w.id);
            const all = w.videos.every((v) => picked.has(v.id));
            return (
              <div key={w.id}>
                <div className="flex items-center gap-8 px-10 py-6 text-11.5 hover:bg-panel2">
                  <input type="checkbox" checked={all} onChange={() => pickWork(w, !all)} title="Pick every video of this work" />
                  <button className="bg-transparent border-0 p-0 text-dim" onClick={() => setOpen(toggle(open, w.id))}>{isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button>
                  <span className="font-medium flex-1 truncate cursor-pointer" onClick={() => setOpen(toggle(open, w.id))}>{w.name}</span>
                  {w.standalone && <Tag>single</Tag>}
                  {w.languages.length > 1 && <Tag tone="accent">{w.languages.join(" · ")}</Tag>}
                  <span className="font-mono text-10 text-faint w-[210px] text-right">
                    {w.videos.length} video{w.videos.length === 1 ? "" : "s"} · {w.with_subtitles} srt · {w.processed} lines · {w.dubbed} dubbed</span>
                </div>
                {isOpen && (
                  <div className="bg-panel2 border-t border-border">
                    {w.videos.map((v) => (
                      <div key={v.id} className="flex items-center gap-8 pl-36 pr-10 py-4 text-11 border-b border-border last:border-0">
                        <input type="checkbox" checked={picked.has(v.id)} onChange={() => setPicked(toggle(picked, v.id))} />
                        <button onClick={() => go(v.id, v.lines ? "transcript" : "overview")} className="bg-transparent border-0 p-0 text-text hover:text-accent truncate flex-1 text-left">{v.name}</button>
                        {v.group && <span className="text-10 text-faint">{v.group}</span>}
                        <Tag>{v.lang}</Tag>
                        {v.subtitles && <Tag tone="good">srt</Tag>}
                        {v.subtitles_other.map((l) => <Tag key={l}>{l}.srt</Tag>)}
                        {v.lines > 0 && <span className="font-mono text-10 text-dim">{v.lines} lines</span>}
                        {v.dubbed.map((l) => <Tag key={l} tone="accent">dub {l}</Tag>)}
                        <span className="font-mono text-10 text-faint w-[64px] text-right">{v.duration ? fmtTime(v.duration) : v.size ? `${(v.size / 1e6).toFixed(0)} MB` : ""}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
