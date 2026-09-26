import { Check, FolderCog, Moon, Sun } from "lucide-react";
import { useState } from "react";
import type { Project } from "../api";
import { go, type Screen } from "../router";

const STEPS: { screen: Screen; label: string }[] = [
  { screen: "overview", label: "Analyze" },
  { screen: "characters", label: "Characters" },
  { screen: "transcript", label: "Transcript" },
  { screen: "translate", label: "Translate" },
  { screen: "voice", label: "Voice" },
  { screen: "mix", label: "Mix" },
];

/** Which pipeline steps count as finished, from the project's own counters. */
function doneSteps(p: Project): Set<Screen> {
  const s = new Set<Screen>();
  const c = p.counts;
  if (c.sentences > 0) s.add("overview");
  if (c.characters > 0 && c.genders_set === c.characters) s.add("characters");
  if (c.sentences > 0 && c.reviewed === c.sentences) s.add("transcript");
  if (c.sentences > 0 && c.translated === c.sentences) s.add("translate");
  return s;
}

export default function TopBar({ project, screen, settingsOpen }: { project: Project | null; screen: Screen; settingsOpen: boolean }) {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "light");
  const toggle = () => {
    const t = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("lb-theme", t); } catch { /* private mode */ }
    setTheme(t);
  };
  const done = project ? doneSteps(project) : new Set<Screen>();
  return (
    <div className="bg-top text-topfg flex items-center gap-12 px-10 h-38 flex-none min-w-0 overflow-hidden">
      <button onClick={() => go(null)} className="flex items-center gap-8 flex-none bg-transparent border-0 text-current p-0">
        <div className="w-18 h-18 bg-white text-top text-9.5 font-bold flex items-center justify-center tracking-tight rounded-2">LB</div>
        <div className="text-12 font-semibold tracking-wide whitespace-nowrap">
          Lang-Bridge <span className="opacity-60 font-normal hidden sm:inline">EN → አማርኛ</span>
        </div>
      </button>

      {project && (
        <>
          <span className="opacity-40">/</span>
          <span className="text-11.5 font-medium whitespace-nowrap overflow-hidden text-ellipsis max-w-[220px]">{project.name}</span>
          <nav className="flex-1 flex justify-center min-w-0">
            <ol className="flex items-center gap-2 m-0 p-0 list-none">
              {STEPS.map((st, i) => {
                const on = st.screen === screen;
                return (
                  <li key={st.screen} className="flex items-center gap-2">
                    {i > 0 && <span className="w-12 h-px bg-topline2 hidden lg:block" />}
                    <button onClick={() => go(project.id, st.screen)}
                      className={`h-24 px-8 rounded-3 text-11 flex items-center gap-5 border ${on ? "bg-topsel text-top border-transparent font-semibold" : "bg-transparent text-current border-transparent hover:bg-topfill"}`}>
                      <span className={`w-14 h-14 rounded-full text-9.5 font-mono flex items-center justify-center flex-none ${done.has(st.screen) ? "bg-good text-white" : on ? "bg-top text-topfg" : "border border-topline2"}`}>
                        {done.has(st.screen) ? <Check size={9} strokeWidth={3} /> : i + 1}
                      </span>
                      <span className="hidden md:inline">{st.label}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </>
      )}
      {!project && <div className="flex-1" />}

      <button onClick={() => { location.hash = "#/settings"; }} title="Job folders & workers" aria-label="Settings"
        className={`border border-topline2 h-24 px-8 rounded-3 text-11 flex items-center gap-5 flex-none ${settingsOpen ? "bg-topsel text-top" : "bg-topfill2 text-current"}`}>
        <FolderCog size={12} /><span className="opacity-70 hidden lg:inline">Folders</span>
      </button>

      <button onClick={toggle} title="Toggle theme" aria-label="Toggle theme"
        className="border border-topline2 bg-topfill2 text-current h-24 px-8 rounded-3 text-11 flex items-center gap-5 flex-none">
        {theme === "dark" ? <Moon size={12} /> : <Sun size={12} />}
        <span className="opacity-70 hidden lg:inline">{theme === "dark" ? "Dark" : "Light"}</span>
      </button>
    </div>
  );
}
