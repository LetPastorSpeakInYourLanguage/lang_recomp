import { GitMerge, Star, Users } from "lucide-react";
import { useState } from "react";
import { api, fmtTime, usePoll, type Character, type Project } from "../api";
import { Button, Empty, Panel, PlayButton, Segmented, SpeakerDot, Tag } from "../ui";

type Src = "vocals" | "audio";

export default function Characters({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const { data, reload, setData } = usePoll(() => api.characters(project.id), [project.id]);
  const [src, setSrc] = useState<Src>("vocals");
  const chars = data ?? [];

  async function patch(c: Character, b: Partial<{ name: string; gender: string; important: boolean }>) {
    setData(chars.map((x) => (x.label === c.label ? { ...x, ...b, important: b.important === undefined ? x.important : Number(b.important) } : x)));
    await api.patchCharacter(project.id, c.label, b);
    onChanged();
  }

  async function merge(source: Character, into: string) {
    const target = chars.find((c) => c.label === into);
    if (!target || !confirm(`Merge "${source.name}" into "${target.name}"? All of ${source.name}'s lines move to ${target.name}.`)) return;
    await api.merge(project.id, source.label, into);
    await reload();
    onChanged();
  }

  if (data && !chars.length) {
    return <Empty icon={<Users size={28} />} title="No characters yet">Load the analysis results first (Analysis & jobs). Each voice the diarizer finds becomes a character here.</Empty>;
  }

  const missing = chars.filter((c) => !c.gender).length;
  return (
    <div className="p-16 max-w-[1200px] mx-auto w-full flex flex-col gap-12">
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1 min-w-[280px]">
          <div className="text-15 font-semibold">Who is speaking?</div>
          <div className="text-11.5 text-dim">
            Name each voice, set its gender (it picks the Amharic verb forms and the fallback voice), and star the characters that need a dub.
            Samples run from each person's quietest line to their most animated one.
          </div>
        </div>
        {missing > 0 ? <Tag tone="warn">{missing} without gender</Tag> : <Tag tone="good">all genders set</Tag>}
        <Segmented<Src> value={src} onChange={setSrc} options={[{ value: "vocals", label: "Voice only" }, { value: "audio", label: "Original mix" }]} />
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(360px,1fr))] gap-12">
        {chars.map((c) => (
          <Panel key={c.label} className={c.important ? "" : "opacity-60"}
            title={
              <div className="flex items-center gap-7 normal-case tracking-normal">
                <SpeakerDot color={c.color} />
                <input defaultValue={c.name} onBlur={(e) => e.target.value.trim() && e.target.value !== c.name && void patch(c, { name: e.target.value.trim() })}
                  onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                  className="bg-transparent border border-transparent hover:border-border2 focus:border-accent rounded-2 px-4 h-22 text-13 font-semibold text-text outline-none min-w-0 flex-1" />
                <Tag>{c.label}</Tag>
              </div>
            }
            actions={
              <button onClick={() => void patch(c, { important: !c.important })} title={c.important ? "Needs a dub" : "Extra — not dubbed"}
                className={`bg-transparent border-0 p-2 ${c.important ? "text-warn" : "text-faint"}`}>
                <Star size={14} fill={c.important ? "currentColor" : "none"} />
              </button>
            }>
            <div className="p-12 flex flex-col gap-10">
              <div className="flex items-center gap-10 flex-wrap">
                <Segmented value={c.gender as "female" | "male" | null} onChange={(g) => void patch(c, { gender: g })}
                  options={[{ value: "female", label: "Female" }, { value: "male", label: "Male" }]} />
                <span className="text-10.5 font-mono text-dim">{fmtTime(c.talk_s)} talk · {c.sentences} lines</span>
              </div>

              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="label">Tone samples</span>
                  <span className="text-9.5 text-faint">quiet → animated</span>
                </div>
                <div className="flex flex-col border border-border rounded-3 divide-y divide-border">
                  {c.samples.map((s) => (
                    <div key={s.id} className="flex items-center gap-8 px-8 py-5">
                      <PlayButton src={api.media(project.id, src)} start={s.start} end={s.end} k={`c-${s.id}-${src}`} />
                      <EnergyBar db={s.energy_db} />
                      <span className="text-11.5 truncate flex-1" title={s.text}>{s.text}</span>
                      <span className="text-9.5 font-mono text-faint">{(s.end - s.start).toFixed(1)}s</span>
                    </div>
                  ))}
                  {!c.samples.length && <div className="px-8 py-6 text-11 text-faint">No clean lines long enough to sample.</div>}
                </div>
              </div>

              {chars.length > 1 && (
                <div className="flex items-center gap-6">
                  <GitMerge size={12} className="text-faint" />
                  <span className="text-11 text-dim">Same person as</span>
                  <select className="field flex-1" defaultValue="" onChange={(e) => { if (e.target.value) void merge(c, e.target.value); e.target.value = ""; }}>
                    <option value="">choose to merge…</option>
                    {chars.filter((o) => o.label !== c.label).map((o) => <option key={o.label} value={o.label}>{o.name}</option>)}
                  </select>
                </div>
              )}
            </div>
          </Panel>
        ))}
      </div>
      <div className="text-10.5 text-faint">
        A voice split across two cards (same person, two clusters) — merge them. One card holding two people — fix individual lines in the Transcript.
        <Button variant="ghost" onClick={() => void reload()}>Refresh</Button>
      </div>
    </div>
  );
}

function EnergyBar({ db }: { db: number | null }) {
  const v = db == null ? 0 : Math.max(0, Math.min(1, (db + 36) / 26));
  return (
    <div className="w-36 h-6 bg-panel3 rounded-full overflow-hidden flex-none" title={db != null ? `${db} dB` : ""}>
      <div className="h-full bg-accent" style={{ width: `${Math.round(v * 100)}%`, opacity: 0.4 + v * 0.6 }} />
    </div>
  );
}
