import { Activity, AudioLines, Bookmark, Clapperboard, FileText, FolderPlus, Languages, Library, Users } from "lucide-react";
import type { ReactNode } from "react";
import { fmtTime, type Project, type Series } from "../api";
import { go, goClips, goSeries, type Screen } from "../router";
import { Tag } from "../ui";

export default function Sidebar({ projects, series, project, screen, openSeries, clipsOpen }: {
  projects: Project[]; series: Series[]; project: Project | null; screen: Screen; openSeries: string | null; clipsOpen: boolean;
}) {
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
        <span className="label">Library</span>
        <button onClick={() => go(null)} title="Library: new series or video" className="text-dim hover:text-accent bg-transparent border-0 p-2">
          <FolderPlus size={14} />
        </button>
      </div>
      <button onClick={() => goClips()} style={{ borderLeftColor: clipsOpen ? "var(--accent)" : "transparent" }}
        className={`w-full text-left border-0 border-l-2 pl-10 pr-12 py-4 flex items-center gap-6 text-11.5 ${clipsOpen ? "bg-sel font-semibold text-text" : "bg-transparent text-dim hover:bg-panel3"}`}>
        <Bookmark size={11} className="text-accent" />Clips & collections
      </button>
      <div className="overflow-y-auto max-h-[38%] pb-6">
        {series.map((s) => {
          const mine = projects.filter((p) => p.series_id === s.id).sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
          const on = openSeries === s.id;
          return (
            <div key={s.id}>
              <button onClick={() => goSeries(s.id)} style={{ borderLeftColor: on ? "var(--accent)" : "transparent" }}
                className={`w-full text-left border-0 border-l-2 pl-10 pr-12 py-4 flex items-center gap-6 ${on ? "bg-sel" : "bg-transparent hover:bg-panel3"}`}>
                <Library size={11} className="text-accent flex-none" />
                <span className={`text-11.5 whitespace-nowrap overflow-hidden text-ellipsis flex-1 ${on ? "font-semibold" : "text-text"}`}>{s.name}</span>
                <span className="text-9.5 font-mono text-faint">{mine.length}</span>
              </button>
              {/* a long series shows its first videos (and the open one); the rest are on its page */}
              {mine.filter((p, i) => i < 8 || project?.id === p.id).map((p) => <ProjectRow key={p.id} p={p} on={project?.id === p.id} screen={screen} indent />)}
              {mine.length > 8 && (
                <button onClick={() => goSeries(s.id)} className="w-full text-left border-0 bg-transparent pl-26 pr-12 py-3 text-10.5 text-accent hover:bg-panel3">
                  {mine.length - 8} more…</button>
              )}
            </div>
          );
        })}
        {series.length > 0 && projects.some((p) => p.standalone) && <div className="label px-12 pt-8 pb-2">Standalone</div>}
        {projects.filter((p) => p.standalone).map((p) => <ProjectRow key={p.id} p={p} on={project?.id === p.id} screen={screen} />)}
        {projects.length === 0 && series.length === 0 && <div className="px-12 py-6 text-11 text-faint">Nothing yet.</div>}
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

function ProjectRow({ p, on, screen, indent }: { p: Project; on: boolean; screen: Screen; indent?: boolean }) {
  return (
    <button onClick={() => go(p.id, on ? screen : "overview")}
      style={{ borderLeftColor: on ? "var(--accent)" : "transparent" }}
      className={`w-full text-left border-0 border-l-2 ${indent ? "pl-26" : "pl-10"} pr-12 py-5 flex flex-col ${on ? "bg-sel" : "bg-transparent hover:bg-panel3"}`}>
      <span className={`text-12 whitespace-nowrap overflow-hidden text-ellipsis ${on ? "font-semibold" : "text-dim"}`}>{p.name}</span>
      <span className="text-9.5 font-mono text-faint">{p.src_lang}→{(p.targets ?? [p.tgt_lang]).join(",")} · {fmtTime(p.duration)} · {p.counts.sentences} lines</span>
    </button>
  );
}
