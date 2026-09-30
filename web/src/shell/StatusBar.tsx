import { Cloud, CloudOff, Cpu, Loader } from "lucide-react";
import type { AppState } from "../api";

export default function StatusBar({ state }: { state: AppState | null }) {
  const active = state?.roots.find((r) => r.active);
  const online = state?.workers.filter((w) => w.online) ?? [];
  const busy = online.find((w) => w.current_job);
  const others = state?.roots.filter((r) => !r.active && r.online) ?? [];
  const run = active?.kind === "local" ? "double-click Local-Worker.cmd" : "notebook runs are started by hand in notebooks/lang_bridge.ipynb";
  return (
    <div className="bg-top text-topfg flex items-center gap-12 px-10 h-22 text-10.5 flex-none min-w-0 overflow-hidden">
      <a href="#/settings" className="flex items-center gap-5 opacity-85 whitespace-nowrap text-current no-underline hover:opacity-100" title={state?.root ?? ""}>
        {state?.drive ? <Cloud size={11} /> : <CloudOff size={11} />}
        {state == null ? "…" : `${active?.name ?? "?"}${state.drive ? "" : " — folder not reachable"}`}
      </a>
      <span className="opacity-40">|</span>
      <span className="flex items-center gap-5 whitespace-nowrap" title="Worker on the active folder">
        <Cpu size={11} />
        {online.length ? (
          <>
            <span className="w-6 h-6 rounded-full bg-good" />
            worker online{busy ? <span className="opacity-70"> · busy: {busy.current_job?.split("-").slice(2, -1).join("-")}</span> : <span className="opacity-70"> · idle</span>}
          </>
        ) : (
          <>
            <span className="w-6 h-6 rounded-full bg-faint" />
            <span className="opacity-85">worker offline — {run} to process queued jobs</span>
          </>
        )}
      </span>
      {others.map((r) => (
        <span key={r.id} className="opacity-70 whitespace-nowrap hidden lg:inline">| {r.name}: worker online</span>
      ))}
      {!!state?.tasks.length && (
        <>
          <span className="opacity-40">|</span>
          <span className="flex items-center gap-5 whitespace-nowrap">
            <Loader size={11} className="animate-spin" />
            {state.tasks.map((t) => `${t.kind}${t.note ? `: ${t.note}` : ""}`).join(" · ")}
          </span>
        </>
      )}
      <div className="flex-1" />
      <span className="opacity-60 whitespace-nowrap hidden md:inline">Edits save as you go</span>
    </div>
  );
}
