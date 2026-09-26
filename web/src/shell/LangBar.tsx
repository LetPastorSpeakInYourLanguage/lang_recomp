import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Project } from "../api";
import { Button } from "../ui";

const key = (pid: string) => `lb-lang-${pid}`;

/** The target language this screen works in: per project, remembered, defaulting to
 *  the project's primary target. */
export function useLang(project: Project): [string, (l: string) => void] {
  const read = () => {
    try {
      const v = localStorage.getItem(key(project.id));
      if (v && project.targets?.includes(v)) return v;
    } catch { /* storage unavailable */ }
    return project.tgt_lang;
  };
  const [lang, setLang] = useState(read);
  useEffect(() => setLang(read()), [project.id, project.targets?.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (l: string) => {
    try { localStorage.setItem(key(project.id), l); } catch { /* ignore */ }
    setLang(l);
  };
  return [lang, set];
}

let catalogue: { code: string; name: string }[] | null = null;
export const langName = (code: string) => catalogue?.find((l) => l.code === code)?.name ?? code;

/** Load the language names once; re-renders the caller when they arrive (for langName). */
export function useLangNames() {
  const [, setList] = useState(catalogue ?? []);
  useEffect(() => {
    if (!catalogue) void api.languages().then((l) => { catalogue = l; setList(l); });
  }, []);
}

/** Target-language chips, plus adding a language to the project. */
export default function LangBar({ project, lang, onChange, onAdded, counts }: {
  project: Project; lang: string; onChange: (l: string) => void; onAdded: () => void; counts?: Record<string, number>;
}) {
  const [adding, setAdding] = useState(false);
  const [list, setList] = useState(catalogue ?? []);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!catalogue) void api.languages().then((l) => { catalogue = l; setList(l); });
  }, []);

  async function add() {
    setErr(null);
    try {
      const c = code.trim().toLowerCase();
      await api.addLanguage(project.id, c);
      setAdding(false);
      setCode("");
      onAdded();
      onChange(c);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="flex items-center gap-6 flex-wrap">
      <span className="label">Into</span>
      {(project.targets ?? [project.tgt_lang]).map((t) => (
        <button key={t} onClick={() => onChange(t)} title={langName(t)}
          className={`h-24 px-8 rounded-3 border text-11 flex items-center gap-5 ${t === lang ? "bg-accent border-accent text-white" : "bg-panel border-border2 text-dim hover:bg-panel3"}`}>
          <span className="font-mono">{t}</span>
          <span className="hidden sm:inline">{langName(t)}</span>
          {counts && <span className={`font-mono text-9.5 ${t === lang ? "opacity-80" : "text-faint"}`}>{counts[t] ?? 0}</span>}
        </button>
      ))}
      {adding ? (
        <span className="flex items-center gap-5">
          <input list="lb-langs" className="field w-[160px]" autoFocus value={code} onChange={(e) => setCode(e.target.value)}
            placeholder="code, e.g. om" onKeyDown={(e) => { if (e.key === "Enter") void add(); if (e.key === "Escape") setAdding(false); }} />
          <datalist id="lb-langs">
            {list.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </datalist>
          <Button variant="primary" onClick={() => void add()} disabled={!code.trim()}>Add</Button>
          <Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
          {err && <span className="text-10.5 text-bad">{err}</span>}
        </span>
      ) : (
        <Button variant="ghost" onClick={() => setAdding(true)} title="Translate this project into another language too">
          <Plus size={12} />Add language
        </Button>
      )}
    </div>
  );
}
