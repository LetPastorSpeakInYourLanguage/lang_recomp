import { Archive, ArchiveRestore, Bookmark, Plus, Repeat, Trash2, Undo2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { api, fmtTime, usePoll, type Clip, type ClipKind, type Collection, type Project, type Series } from "../api";
import { go, goClips } from "../router";
import { langName, useLangNames } from "../shell/LangBar";
import { Button, Empty, PlayButton, Tag } from "../ui";

const KINDS: ClipKind[] = ["clip", "intro", "opener", "outro", "jingle", "recurring"];
type View = { kind: "all" } | { kind: "recurring" } | { kind: "collection"; id: number } | { kind: "removed" };

/** The team library: saved clips and the collections that hold them. */
export default function Clips({ seriesId, series, projects }: { seriesId: string | null; series: Series[]; projects: Project[] }) {
  useLangNames();
  const langs = useMemo(() => [...new Set(projects.flatMap((p) => p.targets))], [projects]);
  const [lang, setLang] = useState(langs[0] ?? "am");
  const [view, setView] = useState<View>({ kind: "all" });
  const [q, setQ] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const cols = usePoll(() => api.collections(showArchived), [showArchived]);
  const clips = usePoll(() => api.clips({
    series: seriesId ?? undefined, lang, deleted: view.kind === "removed",
    collection: view.kind === "collection" ? view.id : undefined,
  }), [seriesId, lang, view.kind, view.kind === "collection" ? view.id : 0]);
  const [newName, setNewName] = useState("");

  const list = (clips.data ?? []).filter((c) =>
    (view.kind !== "recurring" || c.recurring) &&
    (!q.trim() || `${c.title} ${c.note} ${(c.lines ?? []).map((l) => `${l.text} ${l.tr}`).join(" ")}`.toLowerCase().includes(q.trim().toLowerCase())));
  const reload = () => { void clips.reload(); void cols.reload(); };

  async function addCollection() {
    if (!newName.trim()) return;
    const c = await api.createCollection(newName);
    setNewName("");
    await cols.reload();
    setView({ kind: "collection", id: c.id });
  }

  const nav = (v: View, label: string, icon: ReactNode, count?: number) => {
    const on = v.kind === view.kind && (v.kind !== "collection" || (view.kind === "collection" && view.id === v.id));
    return (
      <button key={label + (v.kind === "collection" ? v.id : "")} onClick={() => setView(v)}
        className={`w-full text-left border-0 rounded-3 px-8 py-5 flex items-center gap-6 text-11.5 ${on ? "bg-sel font-semibold text-text" : "bg-transparent text-dim hover:bg-panel3"}`}>
        {icon}<span className="flex-1 truncate">{label}</span>{count !== undefined && <span className="font-mono text-9.5 text-faint">{count}</span>}
      </button>
    );
  };

  return (
    <div className="flex-1 min-h-0 grid grid-cols-[220px_1fr] max-md:grid-cols-1">
      <div className="border-r border-border bg-panel2 p-10 flex flex-col gap-2 min-h-0 overflow-y-auto">
        <div className="label px-8 pb-4">Library</div>
        {nav({ kind: "all" }, "All clips", <Bookmark size={12} />)}
        {nav({ kind: "recurring" }, "Recurring parts", <Repeat size={12} />)}
        <div className="label px-8 pt-10 pb-4 flex items-center gap-6">
          <span className="flex-1">Collections</span>
          <button onClick={() => setShowArchived(!showArchived)} title={showArchived ? "Show current collections" : "Show archived collections"}
            className="bg-transparent border-0 p-0 text-faint hover:text-accent">{showArchived ? <ArchiveRestore size={12} /> : <Archive size={12} />}</button>
        </div>
        {(cols.data ?? []).map((c) => (
          <CollectionRow key={c.id} c={c} on={view.kind === "collection" && view.id === c.id} onOpen={() => setView({ kind: "collection", id: c.id })}
            onChanged={reload} archived={showArchived} />
        ))}
        {!showArchived && (
          <form className="flex items-center gap-4 px-4 pt-4" onSubmit={(e) => { e.preventDefault(); void addCollection(); }}>
            <input className="field flex-1 min-w-0" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New collection" />
            <Button type="submit" variant="ghost" disabled={!newName.trim()}><Plus size={12} /></Button>
          </form>
        )}
        <div className="flex-1" />
        {nav({ kind: "removed" }, "Removed clips", <Trash2 size={12} />)}
      </div>

      <div className="min-h-0 overflow-y-auto p-14 flex flex-col gap-10">
        <div className="flex items-center gap-8 flex-wrap">
          <select className="field" value={seriesId ?? ""} onChange={(e) => goClips(e.target.value || null)} title="Which series">
            <option value="">All series and videos</option>
            {series.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select className="field" value={lang} onChange={(e) => setLang(e.target.value)} title="Captions and dub language">
            {(langs.length ? langs : ["am"]).map((l) => <option key={l} value={l}>{l} · {langName(l)}</option>)}
          </select>
          <input className="field flex-1 min-w-[180px]" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search titles, notes and lines" />
          <span className="text-10.5 font-mono text-faint">{list.length} clip{list.length === 1 ? "" : "s"}</span>
        </div>
        {clips.data && !list.length && (
          <Empty icon={<Bookmark size={26} />} title={view.kind === "removed" ? "Nothing removed" : view.kind === "collection" ? "This collection is empty" : "No clips here yet"}>
            {view.kind === "collection"
              ? "Open All clips and tick this collection on the clips it should hold; a clip can be in several collections."
              : view.kind === "removed" ? "Removed clips wait here and can be restored."
              : "In Transcript, select lines (Shift+J/K or Shift+click) and press S to save them as a clip — a moment worth keeping, or a recurring part such as an intro."}
          </Empty>
        )}
        {list.map((c) => <ClipCard key={c.id} c={c} lang={lang} cols={cols.data ?? []} onChanged={reload} />)}
      </div>
    </div>
  );
}

function CollectionRow({ c, on, onOpen, onChanged, archived }: { c: Collection; on: boolean; onOpen: () => void; onChanged: () => void; archived: boolean }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  if (editing) {
    return (
      <input className="field mx-4" autoFocus value={name} onChange={(e) => setName(e.target.value)}
        onBlur={async () => { setEditing(false); if (name.trim() && name !== c.name) { await api.renameCollection(c.id, name); onChanged(); } }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setName(c.name); setEditing(false); } }} />
    );
  }
  return (
    <div className={`group flex items-center gap-4 rounded-3 px-8 py-5 text-11.5 ${on ? "bg-sel font-semibold" : "hover:bg-panel3"}`}>
      <button onClick={onOpen} onDoubleClick={() => !archived && setEditing(true)} title="Double-click to rename"
        className={`flex-1 text-left truncate bg-transparent border-0 p-0 ${on ? "text-text" : "text-dim"}`}>{c.name}</button>
      <span className="font-mono text-9.5 text-faint">{c.items}</span>
      <button title={archived ? "Restore this collection" : "Archive this collection (its clips stay)"}
        onClick={async () => { await (archived ? api.restoreCollection(c.id) : api.archiveCollection(c.id)); onChanged(); }}
        className="bg-transparent border-0 p-0 text-faint hover:text-accent opacity-0 group-hover:opacity-100">
        {archived ? <ArchiveRestore size={11} /> : <Archive size={11} />}
      </button>
    </div>
  );
}

function ClipCard({ c, lang, cols, onChanged }: { c: Clip; lang: string; cols: Collection[]; onChanged: () => void }) {
  const seg = c.segments[0];
  const [title, setTitle] = useState(c.title);
  const mixed = c.mixed?.[lang];
  async function patch(b: Parameters<typeof api.patchClip>[1]) { await api.patchClip(c.id, b); onChanged(); }
  async function toggle(colId: number) {
    const next = c.collections.includes(colId) ? c.collections.filter((x) => x !== colId) : [...c.collections, colId];
    await api.setClipCollections(c.id, next);
    onChanged();
  }
  return (
    <div className="bg-panel border border-border rounded-3 p-10 flex flex-col gap-6">
      <div className="flex items-center gap-8 flex-wrap">
        <PlayButton src={api.media(seg.source_id, "audio")} start={seg.start} end={seg.end} k={`clip-${c.id}-src`} />
        {mixed && <span className="flex items-center gap-4"><PlayButton src={api.mixAudio(seg.source_id, "mix", mixed, lang)} start={seg.start} end={seg.end} k={`clip-${c.id}-${lang}`} />
          <span className="text-9.5 font-mono text-accent">{lang}</span></span>}
        <input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => title.trim() && title !== c.title && void patch({ title })}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
          className="flex-1 min-w-[160px] bg-transparent border-0 border-b border-transparent hover:border-border2 focus:border-accent outline-none text-12.5 font-semibold" />
        <select className="field h-22 text-10.5" value={c.kind} onChange={(e) => void patch({ kind: e.target.value as ClipKind })}
          title="A recurring part (intro, opener…) is dubbed once and reused wherever it occurs">
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        {c.recurring && <Tag tone="accent">recurring</Tag>}
        {c.deleted ? (
          <Button variant="ghost" onClick={async () => { await api.restoreClip(c.id); onChanged(); }}><Undo2 size={11} />Restore</Button>
        ) : (
          <Button variant="ghost" title="Remove (can be restored)" onClick={async () => { await api.removeClip(c.id); onChanged(); }}><Trash2 size={11} /></Button>
        )}
      </div>
      <div className="text-10 font-mono text-faint flex items-center gap-6">
        <button onClick={() => go(c.source_id, "transcript")} className="bg-transparent border-0 p-0 text-dim hover:text-accent font-sans text-10.5">{c.source_name ?? c.source_id}</button>
        <span>{fmtTime(seg.start)}–{fmtTime(seg.end)} · {c.duration.toFixed(1)}s{c.rev > 1 ? ` · rev ${c.rev}` : ""}</span>
      </div>
      {!!c.lines?.length && (
        <div className="grid gap-2 text-11.5 border-l-2 border-border pl-8">
          {c.lines.map((l) => (
            <div key={`${l.source_id}-${l.id}`}><span className="text-text">{l.text}</span>
              {l.tr && <span className="text-dim"> · {l.tr}</span>}</div>
          ))}
        </div>
      )}
      {cols.length > 0 && (
        <div className="flex items-center gap-4 flex-wrap">
          {cols.map((col) => (
            <button key={col.id} onClick={() => void toggle(col.id)}
              className={`h-20 px-7 rounded-full border text-10 ${c.collections.includes(col.id) ? "bg-accent border-accent text-white" : "bg-panel border-border2 text-dim hover:border-accent"}`}>
              {col.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
