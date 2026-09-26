import { Check, GitMerge, Library, Plus, RefreshCw, Share2, Star, Users, X } from "lucide-react";
import { useState } from "react";
import { api, fmtTime, usePoll, type CastMember } from "../api";
import { go, goSeries, goShare } from "../router";
import { langName, useLangNames } from "../shell/LangBar";
import { Button, Empty, Panel, PlayButton, Segmented, SpeakerDot, Tag } from "../ui";

/** The cast of a work: characters that belong to the series (or a standalone video's
 *  own work), not to one video — where they appear, their names in each language,
 *  and the voice bank their cloned voice is made from. */
export default function Cast({ id }: { id: string }) {
  useLangNames();
  const work = usePoll(() => api.series(id), [id]);
  const cast = usePoll(() => api.cast(id), [id]);
  if (work.error) return <Empty icon={<Users size={28} />} title="No such work">{work.error}</Empty>;
  if (!work.data || !cast.data) return <div className="p-16 text-11.5 text-faint">Loading…</div>;
  const w = work.data;
  const reload = () => void cast.reload();
  const people = cast.data;
  const proposed = people.reduce((n, c) => n + c.appearances.filter((a) => a.status === "proposed").length, 0);

  return (
    <div className="p-16 max-w-[1200px] mx-auto w-full flex flex-col gap-12">
      <div className="flex items-center gap-10 flex-wrap">
        <div className="flex-1 min-w-[280px]">
          <div className="text-15 font-semibold flex items-center gap-8"><Users size={15} className="text-accent" />Cast · {w.name}</div>
          <div className="text-11.5 text-dim">
            Characters belong to the {w.kind === "single" ? "video's work" : "series"}, not to one {w.unit}: a name, gender or dub setting
            set here holds everywhere they appear, and travels when the work is shared. Voices that sound alike across {w.unit}s are
            proposed; nothing is linked until you confirm.
          </div>
        </div>
        {proposed > 0 && <Tag tone="warn">{proposed} to confirm</Tag>}
        {w.kind !== "single" && <Button onClick={() => goSeries(id)}><Library size={12} />{w.name}</Button>}
        <Button onClick={() => goShare(id)}><Share2 size={12} />Share</Button>
      </div>
      {!people.length && <Empty icon={<Users size={26} />} title="No characters yet">They appear when a {w.unit}'s analysis results are loaded.</Empty>}
      {people.map((c) => <Member key={c.uid} c={c} all={people} targets={w.targets} onChanged={reload} />)}
    </div>
  );
}

function Member({ c, all, targets, onChanged }: { c: CastMember; all: CastMember[]; targets: string[]; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  async function patch(b: Parameters<typeof api.patchCast>[1]) { await api.patchCast(c.uid, b); onChanged(); }
  async function act(p: Promise<unknown>) { await p; onChanged(); }
  return (
    <Panel className={c.important ? "" : "opacity-70"}
      title={<div className="flex items-center gap-7 normal-case tracking-normal">
        <SpeakerDot color={c.color} />
        <input defaultValue={c.name} key={c.name} onBlur={(e) => e.target.value.trim() && e.target.value !== c.name && void patch({ name: e.target.value.trim() })}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="bg-transparent border border-transparent hover:border-border2 focus:border-accent rounded-2 px-4 h-22 text-13 font-semibold text-text outline-none min-w-0 w-[200px]" />
        <span className="text-10.5 font-mono text-faint">{fmtTime(c.talk_s)} · {c.appearances.length} {c.appearances.length === 1 ? "appearance" : "appearances"}</span>
        {c.auto ? <Tag>unnamed</Tag> : null}
      </div>}
      actions={<button onClick={() => void patch({ important: !c.important })} title={c.important ? "Needs a dub" : "Extra — not dubbed"}
        className={`bg-transparent border-0 p-2 ${c.important ? "text-warn" : "text-faint"}`}><Star size={14} fill={c.important ? "currentColor" : "none"} /></button>}>
      <div className="p-12 grid grid-cols-[1fr_1fr] max-lg:grid-cols-1 gap-14">
        <div className="flex flex-col gap-8">
          <div className="flex items-center gap-8 flex-wrap">
            <Segmented value={c.gender as "female" | "male" | null} onChange={(g) => void patch({ gender: g })}
              options={[{ value: "female", label: "Female" }, { value: "male", label: "Male" }]} />
            <input className="field flex-1 min-w-[140px]" defaultValue={c.role} key={`r${c.role}`} placeholder="role, e.g. presenter"
              onBlur={(e) => e.target.value !== c.role && void patch({ role: e.target.value })} />
          </div>
          <textarea className="field h-auto py-4 resize-none" rows={2} defaultValue={c.notes} key={`n${c.notes}`}
            placeholder="notes for translators and voice actors (how they speak, who they address…)"
            onBlur={(e) => e.target.value !== c.notes && void patch({ notes: e.target.value })} />
          <div className="grid grid-cols-[90px_1fr] gap-x-8 gap-y-4 items-center text-11">
            {targets.map((t) => (
              <label key={t} className="contents">
                <span className="text-dim">Name in {langName(t)}</span>
                <input className="field" lang={t} defaultValue={c.names[t] ?? ""} key={`${t}${c.names[t] ?? ""}`} placeholder={c.name}
                  onBlur={(e) => e.target.value !== (c.names[t] ?? "") && void act(api.castName(c.uid, t, e.target.value))} />
              </label>
            ))}
          </div>
          {all.length > 1 && (
            <div className="flex items-center gap-6 text-11">
              <GitMerge size={12} className="text-faint" /><span className="text-dim">Same person as</span>
              <select className="field flex-1" defaultValue="" onChange={(e) => {
                const into = all.find((o) => o.uid === e.target.value);
                if (into && confirm(`Merge "${c.name}" into "${into.name}"? Every appearance moves to ${into.name}.`)) void act(api.mergeCast(c.uid, into.uid));
                e.target.value = "";
              }}>
                <option value="">choose to merge…</option>
                {all.filter((o) => o.uid !== c.uid).map((o) => <option key={o.uid} value={o.uid}>{o.name}</option>)}
              </select>
            </div>
          )}
        </div>
        <div className="flex flex-col gap-8">
          <div className="label">Appears in</div>
          <div className="border border-border rounded-3 divide-y divide-border">
            {c.appearances.map((a) => (
              <div key={`${a.source_id}-${a.label}`} className="flex items-center gap-6 px-8 py-5 text-11">
                <button className="bg-transparent border-0 p-0 text-text hover:text-accent truncate flex-1 text-left" onClick={() => go(a.source_id, "characters")}>
                  <Library size={10} className="inline mr-4 text-faint" />{a.source_name}</button>
                <span className="font-mono text-9.5 text-faint">{a.label} · {fmtTime(a.talk_s)}</span>
                {a.status === "proposed" ? (
                  <>
                    <Tag tone="warn">sounds alike{a.score != null ? ` ${a.score.toFixed(2)}` : ""}</Tag>
                    <Button variant="ghost" title="Yes, it's them" onClick={() => void act(api.confirmCharacter(a.source_id, a.label))}><Check size={11} /></Button>
                    <Button variant="ghost" title="Not them: a character of its own" onClick={() => void act(api.linkCharacter(a.source_id, a.label, null))}><X size={11} /></Button>
                  </>
                ) : <Tag tone="good">confirmed</Tag>}
              </div>
            ))}
          </div>
          <button className="bg-transparent border-0 p-0 text-11 text-accent text-left" onClick={() => setOpen(!open)}>
            {open ? "Hide the voice bank" : "Voice bank — the lines the cloned voice is made from"}</button>
          {open && <Bank uid={c.uid} />}
        </div>
      </div>
    </Panel>
  );
}

function Bank({ uid }: { uid: string }) {
  const b = usePoll(() => api.bank(uid), [uid]);
  const [more, setMore] = useState(false);
  if (!b.data) return <div className="text-11 text-faint">Loading…</div>;
  const pin = async (source_id: string, line_id: number, role: "bank" | "heldout" | "excluded") => { await api.pinBank(uid, source_id, line_id, role); await b.reload(); };
  const bank = b.data.rows.filter((r) => r.role === "bank");
  const secs = bank.reduce((n, r) => n + r.end - r.start, 0);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-8 text-10.5 text-dim">
        <span className="flex-1">{secs.toFixed(1)} s from {new Set(bank.map((r) => r.source_id)).size} source(s); held-out lines judge likeness.</span>
        <Button variant="ghost" onClick={async () => { await api.rebuildBank(uid); await b.reload(); }}><RefreshCw size={11} />Rebuild</Button>
      </div>
      <div className="border border-border rounded-3 divide-y divide-border">
        {b.data.rows.map((r) => (
          <div key={`${r.source_id}-${r.line_id}`} className={`flex items-center gap-6 px-8 py-4 text-11 ${r.role === "excluded" ? "opacity-45" : ""}`}>
            <PlayButton src={api.bankAudio(uid, r.source_id, r.line_id)} start={0} end={9999} k={`bank-${uid}-${r.source_id}-${r.line_id}`} size={18} />
            <span className="truncate flex-1" title={r.text}>{r.text}</span>
            <span className="text-9.5 text-faint truncate max-w-[110px]">{r.source_name}</span>
            <select className="field h-20 text-10" value={r.role} onChange={(e) => void pin(r.source_id, r.line_id, e.target.value as "bank" | "heldout" | "excluded")}>
              <option value="bank">bank</option><option value="heldout">held out</option><option value="excluded">excluded</option>
            </select>
            {r.manual ? <Tag>pinned</Tag> : null}
          </div>
        ))}
        {!b.data.rows.length && <div className="px-8 py-6 text-11 text-faint">No bank yet: it needs a confirmed appearance whose vocals are loaded.</div>}
      </div>
      {b.data.candidates.length > 0 && (
        <button className="bg-transparent border-0 p-0 text-10.5 text-accent text-left" onClick={() => setMore(!more)}>
          {more ? "Hide other lines" : `${b.data.candidates.length} other usable lines`}</button>
      )}
      {more && (
        <div className="border border-border rounded-3 divide-y divide-border max-h-[220px] overflow-y-auto">
          {b.data.candidates.map((c) => (
            <div key={`${c.source_id}-${c.id}`} className="flex items-center gap-6 px-8 py-4 text-11">
              <PlayButton src={api.media(c.source_id, "vocals")} start={c.start} end={c.end} k={`cand-${c.source_id}-${c.id}`} size={18} />
              <span className="truncate flex-1" title={c.text}>{c.text}</span>
              <span className="text-9.5 text-faint">{c.secs.toFixed(1)}s</span>
              <Button variant="ghost" title="Add to the bank" onClick={() => void pin(c.source_id, c.id, "bank")}><Plus size={11} /></Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
