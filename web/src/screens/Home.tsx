import { HardDrive, Library, PackageOpen, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api, fmtTime, type AppState, type ImportReport, type LibraryInfo, type PackageInfo, type Project, type Series, type SeriesKind } from "../api";
import { go, goLibrary, goSeries } from "../router";
import VideoForm, { LangOptions } from "../shell/VideoForm";
import { Button, Panel, Tag, stateTone } from "../ui";

const KIND_HINT: Record<SeriesKind, string> = {
  show: "episodes of a show or film series",
  channel: "a podcast or YouTube channel / playlist",
  speaker: "talks, sermons or teachings by one person",
  course: "lessons from an education channel",
  news: "news segments with recurring anchors",
  other: "any group of videos worked on together",
  single: "a standalone video",
};

const codes = (v: string) => v.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);

export default function Home({ projects, series, libraries, state, reload }: {
  projects: Project[]; series: Series[]; libraries: LibraryInfo[]; state: AppState | null; reload: () => void;
}) {
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

      <Libraries libraries={libraries} state={state} onDone={reload} />

      <OpenShared onDone={reload} />

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

/** Folders of videos on a device (Drive for Colab, a disk for this PC), explored per library. */
function Libraries({ libraries, state, onDone }: { libraries: LibraryInfo[]; state: AppState | null; onDone: () => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [root, setRoot] = useState("");
  const [path, setPath] = useState("");
  const [src, setSrc] = useState("en");
  const [targets, setTargets] = useState("am");
  const [kind, setKind] = useState("other");
  const [err, setErr] = useState<string | null>(null);
  const roots = state?.roots ?? [];
  const where = root || roots[0]?.id || "";
  async function add() {
    setErr(null);
    try {
      const L = await api.createLibrary({ name: name.trim() || path.split(/[\\/]/).filter(Boolean).pop() || "Library", root: where, path: path.trim(),
        src_lang: src.trim().toLowerCase(), targets: codes(targets), kind });
      await api.scanLibrary(L.id);
      setAdding(false); onDone(); goLibrary(L.id);
    } catch (e) { setErr((e as Error).message); }
  }
  return (
    <Panel title={`Libraries · ${libraries.length}`} actions={!adding && <Button onClick={() => setAdding(true)}><Plus size={12} />Add a library folder</Button>}>
      {adding && (
        <form className="p-14 grid gap-10 border-b border-border bg-panel2" onSubmit={(e) => { e.preventDefault(); if (path.trim()) void add(); }}>
          <div className="text-11 text-dim">A folder teams push videos into (layout in docs/LIBRARY_FOLDERS.md). It is processed by the device that can read it:
            a folder in your Google Drive by Colab, a folder on this PC or an external disk by this PC's worker. Nothing is copied; scanning reads names only.</div>
          <div className="grid grid-cols-[2fr_1fr] gap-10 max-md:grid-cols-1">
            <label className="grid gap-4"><span className="label">Folder</span>
              <input className="field" autoFocus value={path} onChange={(e) => setPath(e.target.value)} placeholder="G:\My Drive\Libraries\Teachings   or   E:\Preachings\PastorJohnVideos" /></label>
            <label className="grid gap-4"><span className="label">Runs on</span>
              <select className="field" value={where} onChange={(e) => setRoot(e.target.value)}>
                {roots.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select></label>
          </div>
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr] gap-10 max-md:grid-cols-2">
            <label className="grid gap-4"><span className="label">Name</span><input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="the folder's name" /></label>
            <label className="grid gap-4"><span className="label">Spoken</span><input list="lb-langs-all" className="field font-mono" value={src} onChange={(e) => setSrc(e.target.value)} /></label>
            <label className="grid gap-4"><span className="label">Dub into</span><input list="lb-langs-all" className="field font-mono" value={targets} onChange={(e) => setTargets(e.target.value)} /></label>
            <label className="grid gap-4"><span className="label">Mostly</span>
              <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
                {[["speaker", "talks & teachings"], ["show", "shows"], ["channel", "podcasts"], ["course", "courses"], ["news", "news"], ["other", "mixed"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
          </div>
          <div className="flex items-center gap-8">
            <span className="flex-1" />{err && <span className="text-11 text-bad">{err}</span>}
            <Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!path.trim()}>Add and scan</Button>
          </div>
        </form>
      )}
      {!libraries.length && !adding && <div className="p-14 text-11.5 text-faint">A library is a folder of videos a team keeps adding to — series, standalone talks, podcasts — on Drive or a disk.</div>}
      {libraries.length > 0 && (
        <div className="p-12 grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-10">
          {libraries.map((L) => (
            <button key={L.id} onClick={() => goLibrary(L.id)} className="text-left bg-panel2 hover:bg-panel3 border border-border rounded-3 p-10 flex flex-col gap-5">
              <div className="flex items-center gap-6"><HardDrive size={13} className="text-accent" /><span className="text-12.5 font-semibold flex-1 truncate">{L.name}</span>
                <Tag>{roots.find((r) => r.id === L.root_id)?.kind === "colab" ? "Drive" : "this PC"}</Tag></div>
              <div className="text-10 font-mono text-dim truncate">{L.path}</div>
              <div className="text-10.5 text-dim">{L.counts?.works ?? 0} works · {L.counts?.videos ?? 0} videos</div>
            </button>
          ))}
        </div>
      )}
    </Panel>
  );
}

/** Open a work another team shared (.lbwork): see what it holds, then bring it in. */
function OpenShared({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState("");
  const [info, setInfo] = useState<PackageInfo | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function run<T>(fn: () => Promise<T>, then: (v: T) => void) {
    setBusy(true); setErr(null);
    try { then(await fn()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <Panel title="Open a shared work">
      <div className="p-14 flex flex-col gap-10 text-11.5">
        <div className="flex items-center gap-8">
          <PackageOpen size={14} className="text-faint" />
          <input className="field flex-1 h-28 text-12" value={path} onChange={(e) => { setPath(e.target.value); setInfo(null); setReport(null); }}
            placeholder="Path of a .lbwork file on this PC, e.g. D:\shared\six-minute-english.lbwork" />
          <Button disabled={!path.trim() || busy} onClick={() => void run(() => api.inspectPackage(path), setInfo)}>Look inside</Button>
        </div>
        {err && <div className="text-bad">{err}</div>}
        {info && !report && (
          <div className="border border-border rounded-3 p-10 flex flex-col gap-6">
            <div><b>{info.work.name}</b> <Tag>{info.work.kind}</Tag> · {info.sources} source{info.sources === 1 ? "" : "s"} ·
              spoken <span className="font-mono">{info.work.src_lang}</span> · languages included:{" "}
              <span className="font-mono">{info.languages.join(", ") || "none"}</span> · media: {info.media}</div>
            {info.note && <div className="text-dim">“{info.note}”</div>}
            <div className="text-dim">{info.here
              ? "This work is already here: importing adds what is missing and never overwrites what people decided here."
              : "New here: it becomes a work of its own; add your language to it after importing."}
              {info.media === "none" && " Videos and voices are fetched and separated again (one video at a time)."}</div>
            <div className="flex justify-end">
              <Button variant="primary" disabled={busy} onClick={() => void run(() => api.importPackage(path), (r) => { setReport(r); onDone(); })}>
                {busy ? "Importing…" : info.here ? "Add to the work here" : "Import"}</Button>
            </div>
          </div>
        )}
        {report && (
          <div className="border border-good rounded-3 p-10 flex flex-col gap-4">
            <div>{report.created ? "Imported" : "Updated"} <b>{report.work}</b>: {report.sources.added.length} new and {report.sources.matched.length} matching
              source(s), {report.lines} lines, {report.characters.added} new character(s), {report.clips.added} clip(s).</div>
            {Object.entries(report.translations).map(([l, t]) => (
              <div key={l} className="text-dim font-mono text-10.5">{l}: {t.written} written, {t.kept_here} kept as they were here{t.conflicts ? `, ${t.conflicts} differed` : ""}</div>
            ))}
            {report.fetching.length > 0 && <div className="text-dim">Fetching media for {report.fetching.length} source(s) in the background.</div>}
            {report.notes.map((n, i) => <div key={i} className="text-warn text-10.5">{n}</div>)}
            <div><Button onClick={() => goSeries(report.work)}><Library size={12} />Open it</Button></div>
          </div>
        )}
      </div>
    </Panel>
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
