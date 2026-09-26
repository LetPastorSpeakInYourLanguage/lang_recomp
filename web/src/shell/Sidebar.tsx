import { Activity, AudioLines, Clapperboard, FileText, FolderPlus, Languages, Users } from "lucide-react";
import type { ReactNode } from "react";
import { fmtTime, type Project } from "../api";
import { go, type Screen } from "../router";
import { Tag } from "../ui";

export default function Sidebar({ projects, project, screen }: { projects: Project[]; project: Project | null; screen: Screen }) {
  const c = project?.counts;
  const items: { screen: Screen; label: string; icon: ReactNode; count?: string; locked?: boolean }[] = [
    { screen: "overview", label: "Analysis & jobs", icon: <Activity size={13} /> },
    { screen: "characters", label: "Characters", icon: <Users size={13} />, count: c ? `${c.characters}` : "" },
    { screen: "transcript", label: "Transcript", icon: <FileText size={13} />, count: c ? `${c.reviewed}/${c.sentences}` : "" },
    { screen: "translate", label: "Translate", icon: <Languages size={13} />, count: c ? `${c.translated}/${c.sentences}` : "" },
    { screen: "voice", label: "Voice", icon: <AudioLines size={13} /> },
    { screen: "mix", label: "Mix & export", icon: <Clapperboard size={13} /> },
  ];
  return (
    <div className="w-230 bg-panel border-r border-border flex flex-col flex-none min-h-0">
      <div className="px-12 pt-10 pb-6 flex items-center justify-between">
        <span className="label">Projects</span>
        <button onClick={() => go(null)} title="New project" className="text-dim hover:text-accent bg-transparent border-0 p-2">
          <FolderPlus size={14} />
        </button>
      </div>
      <div className="overflow-y-auto max-h-[38%] pb-6">
        {projects.map((p) => {
          const on = project?.id === p.id;
          return (
            <button key={p.id} onClick={() => go(p.id, on ? screen : "overview")}
              style={{ borderLeftColor: on ? "var(--accent)" : "transparent" }}
              className={`w-full text-left border-0 border-l-2 pl-10 pr-12 py-5 flex flex-col ${on ? "bg-sel" : "bg-transparent hover:bg-panel3"}`}>
              <span className={`text-12 whitespace-nowrap overflow-hidden text-ellipsis ${on ? "font-semibold" : "text-dim"}`}>{p.name}</span>
              <span className="text-9.5 font-mono text-faint">{p.src_lang}→{p.tgt_lang} · {fmtTime(p.duration)} · {p.counts.sentences} lines</span>
            </button>
          );
        })}
        {projects.length === 0 && <div className="px-12 py-6 text-11 text-faint">No projects yet.</div>}
      </div>

      {project && (
        <div className="border-t border-border pt-8 flex-1 overflow-y-auto">
          <div className="label px-12 pb-4">This project</div>
          {items.map((it) => {
            const on = it.screen === screen;
            return (
              <button key={it.screen} onClick={() => go(project.id, it.screen)}
                style={{ borderLeftColor: on ? "var(--accent)" : "transparent", background: on ? "var(--sel)" : undefined }}
                className={`w-full text-left border-0 border-l-2 text-12 pl-10 pr-12 py-5 flex items-center gap-8 hover:bg-panel3 bg-transparent ${on ? "text-text font-semibold" : "text-dim"}`}>
                <span className="w-14 flex justify-center opacity-80">{it.icon}</span>
                <span className="flex-1 whitespace-nowrap">{it.label}</span>
                {it.locked ? <Tag>after voicing</Tag> : it.count && <span className={`text-9.5 font-mono ${on ? "text-accent" : "text-faint"}`}>{it.count}</span>}
              </button>
            );
          })}
        </div>
      )}
      {!project && <div className="flex-1" />}
    </div>
  );
}
