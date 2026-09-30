import { Cloud, Cpu, Download, Play } from "lucide-react";
import { useState } from "react";
import { api, usePoll, type AppState, type RunInfo, type Stage } from "../api";
import { Button, Panel, Progress, Tag, stateTone } from "../ui";

const STAGES: { id: Stage; label: string }[] = [
  { id: "fetch", label: "Fetch" }, { id: "transcribe", label: "Transcribe" }, { id: "translate", label: "Translate" },
  { id: "voice", label: "Voice" }, { id: "mix", label: "Mix" },
];
const MODES: { id: string; label: string; stages: Stage[]; hint: string }[] = [
  { id: "all", label: "End to end", stages: ["fetch", "transcribe", "translate", "voice", "mix"], hint: "every stage; checks assumed to pass" },
  { id: "check", label: "Up to the transcript", stages: ["fetch", "transcribe"], hint: "stop for people to check speakers and lines" },
  { id: "lang", label: "Translate → mix", stages: ["translate", "voice", "mix"], hint: "for a team adding its language on checked work" },
  { id: "custom", label: "Choose stages", stages: [], hint: "" },
];

/** Send the pipeline to a device for some videos, and follow the runs sent from here. */
export default function RunPanel({ owner, videos, name, state, fixedRoot, onOpened }: {
  owner: string; videos: string[]; name: string; state: AppState | null; fixedRoot?: string; onOpened: () => void;
}) {
  const runs = usePoll(() => api.runs(owner), [owner], 15000);
  const [root, setRoot] = useState<string>(fixedRoot ?? "");
  const [mode, setMode] = useState("all");
  const [custom, setCustom] = useState<Set<Stage>>(new Set(["fetch", "transcribe"]));
  const [dubLimit, setDubLimit] = useState("5");
  const [takes, setTakes] = useState("1");
  const [captions, setCaptions] = useState("0");
  const [alignCaptions, setAlignCaptions] = useState("0");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const roots = state?.roots ?? [];
  const where = root || fixedRoot || state?.active || "";
  const stages = mode === "custom" ? STAGES.map((s) => s.id).filter((s) => custom.has(s)) : MODES.find((m) => m.id === mode)!.stages;

  async function send() {
    setBusy(true); setMsg(null);
    try {
      const r = await api.createRun({
        videos, root: where, stages, name, owner, options: {
          dub_limit: dubLimit.trim() ? Number(dubLimit) : null, takes: Number(takes) || 1,
          captions_download: Number(captions) || 0, captions_align: Number(alignCaptions) || 0,
        },
      });
      const dev = roots.find((x) => x.id === r.root);
      setMsg(r.dir
        ? `Prepared a run of ${r.videos} video${r.videos === 1 ? "" : "s"}: run it in notebooks/lang_bridge.ipynb with RUN_FOLDER = ${r.dir} (as the notebook sees it, e.g. /content/drive/MyDrive/…).`
        : `Sent ${r.videos} video${r.videos === 1 ? "" : "s"} (${r.works} work${r.works === 1 ? "" : "s"}) to ${dev?.name ?? r.root}.`);
      await runs.reload();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <Panel title="Run the pipeline">
      <div className="p-12 flex flex-col gap-10 text-11.5">
        <div className="flex items-center gap-8 flex-wrap">
          <span className="label">On</span>
          {fixedRoot ? <Tag>{roots.find((r) => r.id === fixedRoot)?.name ?? fixedRoot}</Tag> : (
            <select className="field" value={where} onChange={(e) => setRoot(e.target.value)}>
              {roots.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          )}
          <span className="label ml-8">Do</span>
          <select className="field" value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <span className="text-10.5 text-faint">{MODES.find((m) => m.id === mode)!.hint}</span>
        </div>
        {mode === "custom" && (
          <div className="flex items-center gap-10 flex-wrap">
            {STAGES.map((s) => (
              <label key={s.id} className="flex items-center gap-4"><input type="checkbox" checked={custom.has(s.id)}
                onChange={() => { const n = new Set(custom); if (n.has(s.id)) n.delete(s.id); else n.add(s.id); setCustom(n); }} />{s.label}</label>
            ))}
          </div>
        )}
        <div className="flex items-center gap-10 flex-wrap text-11 text-dim">
          {stages.includes("voice") && <label className="flex items-center gap-4" title="Voice and mix only the first N videos (blank = all)">
            dub the first <input className="field font-mono w-[48px]" value={dubLimit} onChange={(e) => setDubLimit(e.target.value.replace(/\D/g, ""))} placeholder="all" /></label>}
          {stages.includes("voice") && <label className="flex items-center gap-4">takes per line
            <input className="field font-mono w-[36px]" value={takes} onChange={(e) => setTakes(e.target.value.replace(/\D/g, ""))} /></label>}
          {stages.includes("transcribe") && <label className="flex items-center gap-4" title="YouTube videos: also take YouTube's captions for the first N, to compare with Whisper">
            YouTube captions for <input className="field font-mono w-[40px]" value={captions} onChange={(e) => setCaptions(e.target.value.replace(/\D/g, ""))} />
            , align <input className="field font-mono w-[40px]" value={alignCaptions} onChange={(e) => setAlignCaptions(e.target.value.replace(/\D/g, ""))} /></label>}
          <span className="flex-1" />
          <Button variant="primary" disabled={busy || !videos.length || !stages.length || !where} onClick={() => void send()}>
            <Play size={12} />Run {videos.length} video{videos.length === 1 ? "" : "s"}</Button>
        </div>
        {msg && <div className="text-11">{msg}</div>}
        {(runs.data ?? []).length > 0 && (
          <div className="border border-border rounded-3 divide-y divide-border">
            {(runs.data ?? []).map((r) => <RunRow key={r.run} r={r} state={state} onOpened={() => { void runs.reload(); onOpened(); }} />)}
          </div>
        )}
      </div>
    </Panel>
  );
}

export function RunRow({ r, state, onOpened }: { r: RunInfo; state: AppState | null; onOpened: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const dev = state?.roots.find((x) => x.id === r.root);
  const last = r.stages?.[r.stages.length - 1];
  const done = last && r.done ? r.done[last] : 0;
  return (
    <div className="px-8 py-6 flex flex-col gap-4">
      <div className="flex items-center gap-8 flex-wrap text-11">
        {dev?.kind === "colab" ? <Cloud size={12} className="text-accent" /> : <Cpu size={12} className="text-accent" />}
        <span className="font-mono text-10.5">{r.run}</span>
        <Tag tone={stateTone(r.state)}>{r.state ?? "queued"}</Tag>
        <span className="text-dim">{r.videos} videos · {(r.stages ?? []).join(" → ")}</span>
        {r.note && <span className="text-faint truncate max-w-[260px]">{r.note}</span>}
        {!!r.failed && <Tag tone="bad">{r.failed} failed</Tag>}
        <span className="flex-1" />
        {r.has_results && <Button disabled={busy} onClick={async () => {
          setBusy(true);
          try { const x = await api.openRun(r.root, r.run); setMsg(`Opened: ${x.lines} lines in ${x.works.length} work(s); media stay on the device.`); onOpened(); }
          catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
        }}><Download size={11} />Open results</Button>}
      </div>
      {r.videos ? <Progress value={(done ?? 0) / r.videos} tone="good" /> : null}
      {r.has_results && (
        <div className="text-10 text-dim">
          {r.opening ? "Bringing the newest results into the app…"
            : r.opened_at && r.results_at && r.opened_at >= r.results_at ? `In the app: results saved ${new Date(r.results_at * 1000).toLocaleTimeString()}`
            : "New results on the device: they come into the app once Drive has synced them (about a minute)."}
        </div>
      )}
      {r.done && <div className="text-10 font-mono text-faint">{(r.stages ?? []).map((s) => `${s} ${r.done![s] ?? 0}/${r.videos}`).join(" · ")}</div>}
      {r.report?.captions?.length ? (
        <div className="text-10 font-mono text-dim">
          captions vs Whisper: {r.report.captions.map((c) => `${c.video.slice(0, 24)} WER ${c.captions_raw?.wer ?? "–"}` +
            (c.captions_aligned ? `, timing ${c.captions_raw?.timing_median_s ?? "–"}s raw → ${c.captions_aligned.timing_median_s ?? "–"}s aligned` : "")).join(" · ")}
        </div>
      ) : null}
      {msg && <div className="text-10.5">{msg}</div>}
    </div>
  );
}
