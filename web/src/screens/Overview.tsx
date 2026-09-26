import { ArrowRight, Cpu, HardDrive, RefreshCw, ScrollText } from "lucide-react";
import { useState } from "react";
import { api, fmtTime, usePoll, type AppState, type Job, type Project } from "../api";
import { go } from "../router";
import { Button, Panel, Progress, Tag, stateTone } from "../ui";

const STAGE_INFO: Record<string, string> = {
  separate: "Split voices from music & effects",
  asr: "Transcribe with word timings",
  diarize: "Find who speaks when",
  tts_bakeoff: "Voice-cloning comparison",
  ping: "Connection check",
};

export default function Overview({ project, state, onChanged }: { project: Project; state: AppState | null; onChanged: () => void }) {
  const { data, reload } = usePoll(() => api.jobs(project.id), [project.id], 4000);
  const [log, setLog] = useState<{ id: string; text: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const colab = data?.colab ?? [];
  const local = data?.local ?? [];
  const analysis = ["separate", "asr", "diarize"].map((s) => colab.find((j) => j.stage === s));
  const allDone = analysis.every((j) => j?.state === "done");
  const ingested = project.counts.sentences > 0;
  const workerOnline = !!state?.workers.some((w) => w.online);
  const importTask = local.find((t) => t.kind === "import");
  const roots = state?.roots ?? [];
  const rootName = (id: string) => roots.find((r) => r.id === id)?.name ?? id;
  const [target, setTarget] = useState<string>("");
  const where = target || state?.active || "";

  async function realign() {
    setMsg(null);
    try {
      const r = await api.realign(project.id, where);
      setMsg(`Re-aligning words with ${r.model} in ${rootName(where)}; press Reload results when it finishes.`);
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function rerun() {
    setMsg(null);
    try {
      await api.analyze(project.id, where);
      setMsg(`Analysis queued in ${rootName(where)}.`);
      void reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function ingest() {
    setMsg(null);
    try {
      const r = await api.ingest(project.id);
      setMsg(`Loaded ${r.sentences} lines and ${r.characters} characters.`);
      onChanged();
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function showLog(j: Job) {
    const r = await api.log(project.id, j.id);
    setLog({ id: j.id, text: r.log || "(no log yet)" });
  }

  return (
    <div className="p-16 max-w-[1100px] mx-auto w-full flex flex-col gap-14">
      <Panel title="Pipeline" actions={<Button variant="ghost" onClick={() => void reload()}><RefreshCw size={11} />Refresh</Button>}>
        <div className="grid grid-cols-4 max-lg:grid-cols-2">
          <Step icon={<HardDrive size={13} />} title="Import" where="this PC"
            state={importTask ? importTask.state : project.duration ? "done" : null}
            note={importTask?.state === "running" ? importTask.note : importTask?.error ?? (project.duration ? `${fmtTime(project.duration)} clip` : "")}
            progress={importTask?.state === "running" ? importTask.progress : undefined}
            action={importTask?.state === "failed" && <Button onClick={async () => { await api.retryImport(project.id); void reload(); }}>
              <RefreshCw size={11} />Try again</Button>} />
          {(["separate", "asr", "diarize"] as const).map((s, i) => {
            const j = analysis[i];
            return (
              <Step key={s} icon={<Cpu size={13} />} title={STAGE_INFO[s]} where={j ? rootName(j.root) : "not sent"} state={j?.state ?? null}
                note={j?.error ?? resultNote(s, j) ?? (j?.state === "queued" && !workerOnline ? "waiting for the Colab worker" : "")}
                progress={j?.state === "running" ? j.progress ?? 0 : undefined} />
            );
          })}
        </div>
        <div className="border-t border-border px-14 py-10 flex items-center gap-10">
          {ingested ? (
            <>
              <Tag tone="good">loaded</Tag>
              <span className="text-11.5 text-dim flex-1">{project.counts.sentences} lines · {project.counts.characters} characters. Next: confirm who the characters are.</span>
              <Button onClick={() => void ingest()} disabled={!allDone} title="Re-read the analysis outputs (keeps names and genders)">Reload results</Button>
              <Button variant="primary" onClick={() => go(project.id, "characters")}>Characters <ArrowRight size={12} /></Button>
            </>
          ) : (
            <>
              <span className="text-11.5 text-dim flex-1">
                {allDone ? "Analysis finished — load it into the project." : workerOnline ? "A worker is processing the queue." : "Jobs are queued. Start the worker for their folder (see Folders) to process them."}
              </span>
              <Button variant="primary" disabled={!allDone} onClick={() => void ingest()}>Load results</Button>
            </>
          )}
        </div>
        <div className="border-t border-border px-14 py-8 flex items-center gap-8 text-11 text-dim">
          <span>Run the analysis again on</span>
          <select className="field" value={where} onChange={(e) => setTarget(e.target.value)}>
            {roots.map((r) => <option key={r.id} value={r.id}>{r.name}{r.online ? " · worker online" : ""}</option>)}
          </select>
          <Button onClick={() => void rerun()} disabled={!where}>Queue analysis</Button>
          <Button onClick={() => void realign()} disabled={!where || !ingested} title="Pin each word to the audio with the language's aligner and redo speaker assignment; keeps the transcript">Re-align words</Button>
          <span className="text-faint">Results replace the current ones only when you press Reload results.</span>
        </div>
        {msg && <div className="px-14 pb-10 text-11 text-dim">{msg}</div>}
      </Panel>

      <Panel title={`Jobs · ${colab.length + local.length}`}>
        <table className="w-full border-collapse text-11.5">
          <thead>
            <tr className="text-left text-9.5 uppercase tracking-label text-faint">
              {["Stage", "Where", "State", "Time", "Result", ""].map((h) => <th key={h} className="px-12 py-6 font-semibold border-b border-border">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {colab.map((j) => (
              <tr key={j.id} className="border-b border-border last:border-0 align-top">
                <td className="px-12 py-6"><div className="font-medium">{j.stage}</div><div className="text-9.5 font-mono text-faint">{j.id}</div></td>
                <td className="px-12 py-6 text-dim whitespace-nowrap">{rootName(j.root)}</td>
                <td className="px-12 py-6"><Tag tone={stateTone(j.state)}>{j.state ?? "queued"}{j.state === "running" && j.progress != null ? ` ${Math.round(j.progress * 100)}%` : ""}</Tag></td>
                <td className="px-12 py-6 font-mono text-dim">{j.elapsed_s != null ? `${j.elapsed_s.toFixed(0)}s` : "–"}</td>
                <td className="px-12 py-6 text-10.5 font-mono text-dim max-w-[380px] break-words">{j.error ?? (j.result ? JSON.stringify(j.result).slice(0, 160) : "")}</td>
                <td className="px-12 py-6 text-right"><Button variant="ghost" onClick={() => void showLog(j)}><ScrollText size={11} />Log</Button></td>
              </tr>
            ))}
            {local.map((t) => (
              <tr key={t.id} className="border-b border-border last:border-0">
                <td className="px-12 py-6 font-medium">{t.kind}</td>
                <td className="px-12 py-6 text-dim">this PC</td>
                <td className="px-12 py-6"><Tag tone={stateTone(t.state)}>{t.state}</Tag></td>
                <td className="px-12 py-6 font-mono text-dim">{t.finished ? `${(t.finished - t.started).toFixed(0)}s` : "…"}</td>
                <td className="px-12 py-6 text-10.5 font-mono text-dim">{t.error ?? t.note}</td>
                <td />
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {log && (
        <Panel title={`Log · ${log.id}`} actions={<Button variant="ghost" onClick={() => setLog(null)}>Close</Button>}>
          <pre className="m-0 p-12 text-10.5 font-mono whitespace-pre-wrap max-h-[360px] overflow-auto text-dim">{log.text}</pre>
        </Panel>
      )}
    </div>
  );
}

function resultNote(stage: string, j: Job | undefined): string | null {
  const r = j?.result as Record<string, unknown> | null | undefined;
  if (!r || j?.state !== "done") return null;
  if (stage === "separate") return String(r.model ?? "");
  if (stage === "asr") return `${r.words} words · ${r.language}`;
  if (stage === "diarize") return `${(r.speakers as string[] | undefined)?.length ?? "?"} speakers`;
  return null;
}

function Step({ icon, title, where, state, note, progress, action }: {
  icon: React.ReactNode; title: string; where: string; state: string | null; note?: string | null; progress?: number; action?: React.ReactNode;
}) {
  return (
    <div className="p-12 border-r border-border last:border-r-0 flex flex-col gap-6 min-w-0">
      <div className="flex items-center gap-6 text-dim">{icon}<span className="text-9.5 uppercase tracking-label">{where}</span>
        <span className="ml-auto"><Tag tone={stateTone(state)}>{state ?? "queued"}</Tag></span></div>
      <div className="text-12 font-medium">{title}</div>
      {progress !== undefined && <Progress value={progress} />}
      <div className="text-10.5 text-faint font-mono truncate" title={note ?? ""}>{note || " "}</div>
      {action && <div>{action}</div>}
    </div>
  );
}
