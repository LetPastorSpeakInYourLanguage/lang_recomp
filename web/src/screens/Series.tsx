import { ArrowDown, ArrowUp, Bookmark, Library, ListVideo, LogOut } from "lucide-react";
import { useState } from "react";
import { api, fmtTime, parseTime, usePoll, type FeedEntry } from "../api";
import { go, goClips } from "../router";
import VideoForm, { LangOptions } from "../shell/VideoForm";
import { Button, Empty, Panel, Tag, stateTone } from "../ui";

const codes = (v: string) => v.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);

export default function Series({ id, onChanged }: { id: string; onChanged: () => void }) {
  const s = usePoll(() => api.series(id), [id]);
  const [msg, setMsg] = useState<string | null>(null);
  if (s.error) return <Empty icon={<Library size={28} />} title="No such series">{s.error}</Empty>;
  if (!s.data) return <div className="p-16 text-11.5 text-faint">Loading…</div>;
  const d = s.data;
  const sources = d.sources ?? [];
  const reload = async () => { await s.reload(); onChanged(); };

  async function save(b: Parameters<typeof api.patchSeries>[1]) {
    setMsg(null);
    try { await api.patchSeries(id, b); await reload(); } catch (e) { setMsg((e as Error).message); }
  }

  async function move(i: number, by: number) {
    const ids = sources.map((p) => p.id);
    const j = i + by;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await api.orderSeries(id, ids);
    await reload();
  }

  return (
    <div className="p-16 max-w-[1100px] mx-auto w-full flex flex-col gap-14">
      <LangOptions />
      <div className="flex items-start gap-10 flex-wrap">
        <div className="flex-1 min-w-[280px] flex flex-col gap-4">
          <div className="flex items-center gap-8">
            <Library size={15} className="text-accent" />
            <Field value={d.name} onSave={(v) => v.trim() && void save({ name: v })} className="text-15 font-semibold" />
            <Tag>{d.label}</Tag>
            <span className="flex-1" />
            <Button onClick={() => goClips(id)}><Bookmark size={12} />Clips from this series</Button>
          </div>
          <div className="text-11.5 text-dim">
            Every {d.unit} added here is transcribed from <b className="font-mono">{d.src_lang}</b> and dubbed into the series' languages;
            its settings come from here, so a team sets them once.
          </div>
        </div>
      </div>

      <Panel title="Series settings">
        <div className="p-12 grid grid-cols-[1fr_2fr_1fr] gap-10 max-md:grid-cols-1 text-11">
          <label className="grid gap-4"><span className="label">Spoken language</span>
            <Field value={d.src_lang} list="lb-langs-all" className="font-mono" onSave={(v) => void save({ src_lang: v.trim().toLowerCase() })} boxed /></label>
          <label className="grid gap-4"><span className="label">Dub into (first is primary)</span>
            <Field value={d.targets.join(", ")} list="lb-langs-all" className="font-mono" onSave={(v) => void save({ targets: codes(v) })} boxed /></label>
          <label className="grid gap-4"><span className="label">Max speakers</span>
            <Field value={d.settings.max_speakers ? String(d.settings.max_speakers) : ""} className="font-mono" placeholder="auto" boxed
              onSave={(v) => void save({ settings: { max_speakers: v.trim() ? Number(v) : null } })} /></label>
          <label className="grid gap-4 col-span-full max-md:col-span-1"><span className="label">Channel or playlist link</span>
            <Field value={d.feed_url ?? ""} placeholder="https://www.youtube.com/@channel" boxed onSave={(v) => void save({ feed_url: v })} /></label>
        </div>
        {msg && <div className="px-12 pb-10 text-11 text-bad">{msg}</div>}
        <div className="px-12 pb-10 flex items-center gap-8">
          <span className="text-10.5 text-faint flex-1">Changes apply to {d.unit}s added from now on; existing ones keep their own languages.</span>
          <Button variant="ghost" title={`Remove the series; its ${d.unit}s stay, as standalone videos`}
            onClick={async () => { if (confirm(`Remove the series "${d.name}"? Its ${sources.length} ${d.unit}(s) stay as standalone videos.`)) { await api.deleteSeries(id); onChanged(); go(null); } }}>
            Remove series
          </Button>
        </div>
      </Panel>

      {d.feed_url && <FromFeed id={id} unit={d.unit} onAdded={() => void reload()} />}

      <Panel title={`Add a ${d.unit}`}>
        <VideoForm submitLabel={`Add ${d.unit}`} onSubmit={async (v) => { await api.addSource(id, v); await reload(); }}
          note={<>Takes <span className="font-mono">{d.src_lang}→{d.targets.join(",")}</span> from the series; downloads, then queues the analysis.</>} />
      </Panel>

      <Panel title={`${d.unit[0].toUpperCase()}${d.unit.slice(1)}s · ${sources.length}`}>
        {sources.length === 0 ? (
          <div className="p-14 text-11.5 text-faint">No {d.unit}s yet.</div>
        ) : (
          <table className="w-full border-collapse text-11.5">
            <thead>
              <tr className="text-left text-9.5 uppercase tracking-label text-faint">
                {["#", d.unit, "Length", "Analysis", "Lines", "Translated", ""].map((h, i) => <th key={i} className="px-10 py-6 font-semibold border-b border-border">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {sources.map((p, i) => (
                <tr key={p.id} onClick={() => go(p.id)} className="cursor-pointer hover:bg-panel2 border-b border-border last:border-0">
                  <td className="px-10 font-mono text-dim">{i + 1}</td>
                  <td className="px-10 py-7"><div className="font-medium">{p.name}</div><div className="text-10 text-faint font-mono truncate max-w-[320px]">{p.source}</div></td>
                  <td className="px-10 font-mono">{fmtTime(p.duration)}</td>
                  <td className="px-10"><div className="flex gap-3">{(["separate", "asr", "diarize"] as const).map((st) => <Tag key={st} tone={stateTone(p.analysis[st])}>{st}</Tag>)}</div></td>
                  <td className="px-10 font-mono">{p.counts.sentences}</td>
                  <td className="px-10 font-mono">{p.targets.map((t) => `${t} ${p.counts.translated_by_lang[t] ?? 0}`).join(" · ")}</td>
                  <td className="px-10" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-2 justify-end">
                      <Button variant="ghost" title="Earlier" disabled={i === 0} onClick={() => void move(i, -1)}><ArrowUp size={11} /></Button>
                      <Button variant="ghost" title="Later" disabled={i === sources.length - 1} onClick={() => void move(i, 1)}><ArrowDown size={11} /></Button>
                      <Button variant="ghost" title="Take out of the series (it becomes a standalone video; nothing is deleted)"
                        onClick={async () => { await api.attachProject(p.id, null); await reload(); }}><LogOut size={11} /></Button>
                    </div>
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

/** Pick videos from the series' channel or playlist. Listing downloads nothing; the
 *  picked videos are added in order and download one at a time. */
function FromFeed({ id, unit, onAdded }: { id: string; unit: string; onAdded: () => void }) {
  const [entries, setEntries] = useState<FeedEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [hide, setHide] = useState<Set<string>>(new Set(["Shorts"]));
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState<string | null>(null);

  async function check() {
    setBusy(true); setErr(null); setNote(null);
    try { setEntries((await api.seriesFeed(id)).entries); setPicked(new Set()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  async function add() {
    if (!entries) return;
    setBusy(true); setErr(null);
    try {
      const items = entries.filter((e) => picked.has(e.id)).reverse(); // oldest first, like episodes
      const r = await api.addFromFeed(id, items, { clip_start: parseTime(start), clip_end: parseTime(end) });
      setNote(`Added ${r.added.length}; they download one at a time.${r.skipped.length ? ` Skipped ${r.skipped.length}.` : ""}`);
      setEntries(entries.map((e) => (picked.has(e.id) ? { ...e, added: true } : e)));
      setPicked(new Set());
      onAdded();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  const sections = [...new Set((entries ?? []).map((e) => e.section))];
  const shown = (entries ?? []).filter((e) => !hide.has(e.section));
  const toggle = (set: Set<string>, v: string) => { const n = new Set(set); if (n.has(v)) n.delete(v); else n.add(v); return n; };
  return (
    <Panel title="From the channel"
      actions={<Button onClick={() => void check()} disabled={busy}><ListVideo size={12} />{entries ? "Check again" : `Check for ${unit}s`}</Button>}>
      {err && <div className="px-12 py-8 text-11 text-bad">{err}</div>}
      {!entries && !err && <div className="px-12 py-10 text-11 text-faint">{busy ? "Listing the channel…" : `Lists the channel's ${unit}s without downloading any; pick which to add.`}</div>}
      {entries && (
        <>
          <div className="px-12 py-8 flex items-center gap-10 flex-wrap border-b border-border text-11 text-dim">
            {sections.map((sec) => (
              <label key={sec} className="flex items-center gap-4"><input type="checkbox" checked={!hide.has(sec)} onChange={() => setHide(toggle(hide, sec))} />
                {sec} <span className="font-mono text-faint">{entries.filter((e) => e.section === sec).length}</span></label>
            ))}
            <span className="flex-1" />
            <span>clip</span>
            <input className="field font-mono w-[64px]" value={start} onChange={(e) => setStart(e.target.value)} placeholder="0:00" title="Start of the part to take from each video" />
            <input className="field font-mono w-[64px]" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="end" title="End of the part to take (blank = whole video)" />
            <Button variant="primary" disabled={!picked.size || busy} onClick={() => void add()}>Add {picked.size || ""} {unit}{picked.size === 1 ? "" : "s"}</Button>
          </div>
          {note && <div className="px-12 py-6 text-11 text-good">{note}</div>}
          <div className="max-h-[320px] overflow-y-auto">
            {shown.map((e) => (
              <label key={e.id} className={`flex items-center gap-8 px-12 py-5 border-b border-border last:border-0 text-11.5 ${e.added || e.live ? "opacity-55" : "hover:bg-panel2 cursor-pointer"}`}>
                <input type="checkbox" disabled={e.added || e.live} checked={picked.has(e.id)} onChange={() => setPicked(toggle(picked, e.id))} />
                <span className="flex-1 truncate">{e.title}</span>
                {e.added && <Tag tone="good">added</Tag>}
                {e.live && <Tag>upcoming</Tag>}
                <span className="font-mono text-10 text-faint w-[60px] text-right">{e.duration ? fmtTime(e.duration) : "–"}</span>
              </label>
            ))}
            {!shown.length && <div className="px-12 py-8 text-11 text-faint">Nothing in the ticked sections.</div>}
          </div>
        </>
      )}
    </Panel>
  );
}

/** Text edited in place, saved on blur or Enter. */
function Field({ value, onSave, className = "", placeholder, list, boxed }: {
  value: string; onSave: (v: string) => void; className?: string; placeholder?: string; list?: string; boxed?: boolean;
}) {
  const [v, setV] = useState(value);
  return (
    <input value={v} list={list} placeholder={placeholder} onChange={(e) => setV(e.target.value)}
      onBlur={() => { if (v !== value) onSave(v); }}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setV(value); } }}
      className={boxed ? `field ${className}` : `bg-transparent border-0 border-b border-transparent hover:border-border2 focus:border-accent outline-none min-w-0 ${className}`} />
  );
}
