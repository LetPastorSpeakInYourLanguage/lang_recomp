import { Cloud, Cpu, FolderCog, Monitor, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, usePoll, type AppState, type Root } from "../api";
import { Button, Panel, Segmented, Tag } from "../ui";
import Aligners from "./Aligners";

/** Job folders: where analysis and voicing jobs are sent, and who processes them. */
export default function Settings({ state, onSaved }: { state: AppState | null; onSaved: () => void }) {
  const loaded = usePoll(api.settings, []);
  const [roots, setRoots] = useState<Root[]>([]);
  const [active, setActive] = useState("");
  const [aligners, setAligners] = useState<Record<string, string>>({});
  const [keepWords, setKeepWords] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    if (loaded.data) { setRoots(loaded.data.roots); setActive(loaded.data.active); setAligners(loaded.data.aligners ?? {}); setKeepWords((loaded.data.keep_words ?? []).join(", ")); }
  }, [loaded.data]);
  const keepList = keepWords.split(/[,\n]/).map((w) => w.trim().toLowerCase()).filter(Boolean);
  const dirty = !!loaded.data && JSON.stringify({ roots, active, aligners, k: [...keepList].sort() }) !==
    JSON.stringify({ roots: loaded.data.roots, active: loaded.data.active, aligners: loaded.data.aligners ?? {}, k: [...(loaded.data.keep_words ?? [])].sort() });
  const live = (id: string) => state?.roots.find((r) => r.id === id);

  const edit = (i: number, b: Partial<Root>) => setRoots(roots.map((r, j) => (j === i ? { ...r, ...b } : r)));

  async function save() {
    try {
      const s = await api.saveSettings({ roots, active, aligners, keep_words: keepList });
      loaded.setData(s);
      setMsg({ ok: true, text: "Saved." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }

  return (
    <div className="p-16 max-w-[980px] mx-auto w-full flex flex-col gap-12">
      <div>
        <div className="text-15 font-semibold flex items-center gap-8"><FolderCog size={16} />Job folders</div>
        <div className="text-11.5 text-dim">
          GPU-heavy steps are sent as jobs to a folder and processed by whichever worker watches it. The <b>active</b> folder is where new
          work goes; jobs already sent keep reporting from their own folder.
        </div>
      </div>

      {roots.map((r, i) => {
        const l = live(r.id);
        return (
          <Panel key={r.id || i}
            title={
              <label className="flex items-center gap-8 normal-case tracking-normal cursor-pointer">
                <input type="radio" name="active" checked={active === r.id} onChange={() => setActive(r.id)} />
                {r.kind === "colab" ? <Cloud size={13} className="text-accent" /> : <Monitor size={13} className="text-accent" />}
                <span className="text-12.5 font-semibold text-text">{r.name}</span>
                {active === r.id && <Tag tone="accent">active</Tag>}
              </label>
            }
            actions={
              <div className="flex items-center gap-6">
                {l && (l.reachable ? <Tag tone="good">folder ok</Tag> : <Tag tone="bad">folder not reachable</Tag>)}
                {l && (l.online
                  ? <Tag tone="good">worker online · {l.workers.find((w) => w.online)?.device ?? ""}</Tag>
                  : <Tag>no worker</Tag>)}
                {roots.length > 1 && (
                  <button title="Remove" onClick={() => setRoots(roots.filter((_, j) => j !== i))} className="bg-transparent border-0 text-faint hover:text-bad p-2">
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            }>
            <div className="p-12 grid grid-cols-[1fr_2fr_auto] gap-10 items-end max-md:grid-cols-1">
              <label className="grid gap-4"><span className="label">Name</span>
                <input className="field" value={r.name} onChange={(e) => edit(i, { name: e.target.value })} /></label>
              <label className="grid gap-4"><span className="label">Folder path</span>
                <input className="field font-mono" value={r.path} onChange={(e) => edit(i, { path: e.target.value })} /></label>
              <div className="grid gap-4"><span className="label">Processed by</span>
                <Segmented<Root["kind"]> value={r.kind} onChange={(k) => edit(i, { kind: k })}
                  options={[{ value: "colab", label: "Colab" }, { value: "local", label: "This PC" }]} /></div>
            </div>
            <div className="px-12 pb-10 text-10.5 text-dim flex items-start gap-6">
              <Cpu size={11} className="mt-2 flex-none" />
              {r.kind === "colab" ? (
                <span>Must be inside your Google Drive. Open <span className="font-mono">worker/lb_worker.ipynb</span> from this folder in Colab,
                  choose a T4 GPU and Run all. Handles every stage, including voicing.</span>
              ) : (
                <span>Double-click <span className="font-mono">Local-Worker.cmd</span> in the app folder. It keeps its own Python, models
                  and cache inside this folder. Separation, alignment and voicing run on the Intel Arc GPU when its environment is set up;
                  transcription and speaker detection on the CPU.</span>
              )}
            </div>
          </Panel>
        );
      })}

      <div className="flex items-center gap-10">
        <Button onClick={() => setRoots([...roots, { id: "", name: "Another folder", kind: "local", path: "" }])}><Plus size={12} />Add folder</Button>
      </div>

      <Aligners value={aligners} onChange={setAligners} />

      <Panel title="Words that can stay in the original language">
        <div className="p-12 flex flex-col gap-6 text-11 text-dim">
          <span>
            A line of at most 3 words and 1.5 s made only of these words is kept in the speaker's own voice instead of dubbed
            (the subtitles show the original words). Any line can be switched by hand in Translate or Voice.
          </span>
          <textarea className="field h-auto py-5 font-mono text-11 leading-relaxed" rows={3} value={keepWords}
            onChange={(e) => setKeepWords(e.target.value)} />
        </div>
      </Panel>

      <div className="flex items-center gap-10 sticky bottom-0 bg-bg py-8">
        <div className="flex-1" />
        {msg && <span className={`text-11 ${msg.ok ? "text-good" : "text-bad"}`}>{msg.text}</span>}
        <Button variant="primary" disabled={!dirty} onClick={() => void save()}>Save</Button>
      </div>
    </div>
  );
}
