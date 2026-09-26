import { AlertTriangle, Check, FileText, Keyboard, Merge, Pause, Play, Scissors, Split } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, fmtTime, usePoll, type Chapter, type Character, type Project, type Sentence } from "../api";
import { Empty, SpeakerDot, Tag } from "../ui";

/** A line whose words drifted: Whisper dropped punctuation/capitals there, and the
 *  speaker boundary may be off by a word. Worth a listen. */
const suspicious = (s: Sentence) => !/^[A-Z0-9"'(]/.test(s.text) || !/[.?!…]["')]?$/.test(s.text.trim());

export default function Transcript({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const sents = usePoll(() => api.sentences(project.id), [project.id]);
  const chars = usePoll(() => api.characters(project.id), [project.id]);
  const chaps = usePoll(() => api.chapters(project.id), [project.id]);
  const rows = sents.data ?? [];
  const cast = chars.data ?? [];
  const [sel, setSel] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [nowId, setNowId] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number>(Infinity);
  const listRef = useRef<HTMLDivElement>(null);
  const byLabel = useMemo(() => Object.fromEntries(cast.map((c) => [c.label, c])), [cast]);
  const chapterById = useMemo(() => Object.fromEntries((chaps.data ?? []).map((c) => [c.id, c])), [chaps.data]);

  const [note, setNote] = useState<string | null>(null);

  /** Merge a line with the next one; the merged line keeps the longer part's speaker. */
  async function mergeNext(i: number) {
    const s = rows[i];
    if (!s || i + 1 >= rows.length) return;
    await api.mergeNext(project.id, s.id);
    await Promise.all([sents.reload(), chaps.reload()]);
    setNote(`Merged line ${fmtTime(s.start)} with the next one. Its translation was cleared.`);
    onChanged();
  }

  /** Split at the caret: the words before it stay, the rest becomes a new line. */
  async function splitAt(s: Sentence, text: string, caret: number) {
    const before = text.slice(0, caret).trim();
    const wordIndex = before ? before.split(/\s+/).length : 0;
    if (wordIndex <= 0 || wordIndex >= text.trim().split(/\s+/).length) {
      setNote("Put the cursor between two words to split there.");
      return;
    }
    if (text.trim() !== s.text) await api.patchSentence(project.id, s.id, { text: text.trim() });
    await api.split(project.id, s.id, wordIndex);
    setEditing(null);
    await Promise.all([sents.reload(), chaps.reload()]);
    setNote(`Split line ${fmtTime(s.start)} after word ${wordIndex}.`);
    onChanged();
  }

  /** Start a chapter at this line, or fold the chapter it opens into the one before. */
  async function toggleChapter(s: Sentence) {
    try {
      const r = await api.toggleChapter(project.id, s.id);
      await Promise.all([sents.reload(), chaps.reload()]);
      setNote(r.added ? `New chapter from ${fmtTime(s.start)}.` : `Chapter removed; its lines joined the one before.`);
      onChanged();
    } catch (e) {
      setNote((e as Error).message);
    }
  }

  async function rename(c: Chapter, title: string) {
    if (title.trim() === c.title) return;
    await api.renameChapter(project.id, c.id, title);
    await chaps.reload();
  }

  async function patch(s: Sentence, b: Parameters<typeof api.patchSentence>[2]) {
    const updated = await api.patchSentence(project.id, s.id, b);
    sents.setData(rows.map((r) => (r.id === s.id ? updated : r)));
    onChanged();
  }

  function playLine(i: number) {
    const v = video.current;
    const s = rows[i];
    if (!v || !s) return;
    if (playing && nowId === s.id) { v.pause(); return; }
    v.currentTime = s.start;
    stopAt.current = s.end;
    void v.play();
  }

  // Follow playback: highlight the line under the playhead, stop at a line's end.
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const onTime = () => {
      const t = v.currentTime;
      if (t >= stopAt.current) { v.pause(); stopAt.current = Infinity; }
      const cur = rows.find((s) => t >= s.start && t < s.end + 0.05);
      setNowId(cur?.id ?? null);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => { v.removeEventListener("timeupdate", onTime); v.removeEventListener("play", onPlay); v.removeEventListener("pause", onPause); };
  }, [rows]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  // Keyboard: the transcript is meant to be worked through without the mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (editing !== null || (e.target as HTMLElement).closest("input,textarea,select")) return;
      const s = rows[sel];
      if (!s) return;
      const k = e.key.toLowerCase();
      if (k === "j" || e.key === "ArrowDown") { e.preventDefault(); setSel(Math.min(rows.length - 1, sel + 1)); }
      else if (k === "k" || e.key === "ArrowUp") { e.preventDefault(); setSel(Math.max(0, sel - 1)); }
      else if (e.key === " ") { e.preventDefault(); playLine(sel); }
      else if (e.key === "Enter") { e.preventDefault(); setEditing(s.id); }
      else if (k === "c") void toggleChapter(s);
      else if (k === "m") void mergeNext(sel);
      else if (k === "r") { void patch(s, { reviewed: !s.reviewed }); setSel(Math.min(rows.length - 1, sel + 1)); }
      else if (/^[1-9]$/.test(e.key) && cast[Number(e.key) - 1]) void patch(s, { speaker: cast[Number(e.key) - 1].label });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (sents.data && !rows.length) {
    return <Empty icon={<FileText size={28} />} title="No transcript yet">Load the analysis results first (Analysis & jobs).</Empty>;
  }

  const reviewed = rows.filter((r) => r.reviewed).length;
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Top band: the video, and beside it progress, messages and the keys. The lines get the rest. */}
      <div className="shrink-0 p-14 grid grid-cols-[min(46%,calc(36vh*16/9))_1fr] gap-14 border-b border-border bg-panel2">
        <video ref={video} src={api.media(project.id, "video")} controls className="w-full rounded-3 bg-black aspect-video" />
        {/* as tall as the video, no taller: the keys scroll inside it */}
        <div className="relative min-w-0"><div className="absolute inset-0 flex flex-col gap-8">
          <div className="flex items-center gap-8 text-11 text-dim">
            <span className="font-mono">{reviewed}/{rows.length} reviewed</span>
            <div className="flex-1 h-4 bg-panel3 rounded-full overflow-hidden"><div className="h-full bg-good" style={{ width: `${rows.length ? (reviewed / rows.length) * 100 : 0}%` }} /></div>
          </div>
          {note && <div className="border border-accent bg-soft rounded-3 px-10 py-6 text-11 text-text flex gap-8"><span className="flex-1">{note}</span>
            <button onClick={() => setNote(null)} className="bg-transparent border-0 text-dim p-0">×</button></div>}
          <div className="border border-border rounded-3 bg-panel p-10 text-11 text-dim flex flex-col gap-4 min-h-0 overflow-y-auto">
            <div className="flex items-center gap-6 font-semibold text-text"><Keyboard size={12} />Keys</div>
            <div className="grid grid-cols-[70px_1fr_70px_1fr] max-xl:grid-cols-[70px_1fr] gap-x-14 gap-y-2 font-mono text-10.5">
              <span>J / K</span><span className="font-sans">next / previous line</span>
              <span>Space</span><span className="font-sans">play the line</span>
              <span>Enter</span><span className="font-sans">edit text (Esc to leave)</span>
              <span>Ctrl+Enter</span><span className="font-sans">while editing: split the line at the cursor</span>
              <span>1–{Math.max(1, cast.length)}</span><span className="font-sans">set speaker: {cast.map((c, i) => `${i + 1} ${c.name}`).join(", ")}</span>
              <span>M</span><span className="font-sans">merge with the next line</span>
              <span>R</span><span className="font-sans">mark reviewed and move on</span>
              <span>C</span><span className="font-sans">start a new chapter here, or remove the one this line starts (translation context stops at chapters)</span>
            </div>
          </div>
        </div></div>
      </div>

      <div ref={listRef} className="flex-1 overflow-y-auto min-h-0 p-14 flex flex-col gap-0">
        {rows.map((s, i) => {
          const c = s.speaker ? byLabel[s.speaker] : undefined;
          const head = i === 0 || !!s.chapter_head;
          const ch = chapterById[s.chapter];
          const on = i === sel;
          return (
            <div key={s.id} data-i={i}>
              {head && (
                <div className="flex items-center gap-8 pt-10 pb-5">
                  <Scissors size={11} className="text-faint" />
                  <span className="label">Chapter {ch ? ch.index + 1 : ""}</span>
                  {ch && <ChapterTitle key={`${ch.id}:${ch.title}`} chapter={ch} onSave={(t) => void rename(ch, t)} />}
                  <div className="flex-1 h-px bg-border" />
                </div>
              )}
              <div onClick={() => setSel(i)}
                className={`grid grid-cols-[56px_150px_1fr_auto] items-start gap-8 px-8 py-6 border-l-2 rounded-r-3 ${on ? "bg-sel border-accent" : nowId === s.id ? "bg-soft border-transparent" : "border-transparent hover:bg-panel"}`}>
                <button onClick={(e) => { e.stopPropagation(); setSel(i); playLine(i); }} className="flex items-center gap-4 text-10 font-mono text-dim bg-transparent border-0 p-0 pt-2 hover:text-accent">
                  {playing && nowId === s.id ? <Pause size={10} /> : <Play size={10} />}{fmtTime(s.start)}
                </button>
                <SpeakerPick value={s.speaker} cast={cast} current={c} onChange={(label) => void patch(s, { speaker: label })} />
                {editing === s.id ? (
                  <textarea autoFocus defaultValue={s.text} rows={Math.max(1, Math.ceil(s.text.length / 70))}
                    onBlur={(e) => { const v = e.target.value.trim(); setEditing(null); if (v && v !== s.text) void patch(s, { text: v }); }}
                    onKeyDown={(e) => {
                      const t = e.target as HTMLTextAreaElement;
                      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void splitAt(s, t.value, t.selectionStart); }
                      else if (e.key === "Escape" || (e.key === "Enter" && !e.shiftKey)) { e.preventDefault(); t.blur(); }
                    }}
                    className="field h-auto py-4 text-12.5 leading-relaxed resize-none w-full" />
                ) : (
                  <div onDoubleClick={() => setEditing(s.id)} className={`text-12.5 leading-relaxed ${s.reviewed ? "text-text" : "text-text"}`}>{s.text}</div>
                )}
                <div className="flex items-center gap-5 pt-2">
                  {suspicious(s) && !s.reviewed && <span title="Unpunctuated line — the speaker boundary may be off by a word" className="text-warn"><AlertTriangle size={12} /></span>}
                  <span className="text-9.5 font-mono text-faint">{s.slot_s.toFixed(1)}s</span>
                  <button onClick={(e) => { e.stopPropagation(); setSel(i); setEditing(s.id); setNote("Place the cursor where the line should break, then press Ctrl+Enter."); }}
                    title="Split this line (cursor + Ctrl+Enter)" className="bg-transparent border-0 p-0 text-faint hover:text-accent"><Split size={12} /></button>
                  <button onClick={(e) => { e.stopPropagation(); void mergeNext(i); }} disabled={i + 1 >= rows.length}
                    title="Merge with the next line (M)" className="bg-transparent border-0 p-0 text-faint hover:text-accent disabled:opacity-30"><Merge size={12} /></button>
                  <button onClick={(e) => { e.stopPropagation(); void patch(s, { reviewed: !s.reviewed }); }} title={s.reviewed ? "Reviewed" : "Mark reviewed"}
                    className={`w-16 h-16 rounded-2 border flex items-center justify-center ${s.reviewed ? "bg-good border-good text-white" : "bg-panel border-border2 text-transparent hover:text-faint"}`}>
                    <Check size={10} strokeWidth={3} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SpeakerPick({ value, cast, current, onChange }: { value: string | null; cast: Character[]; current?: Character; onChange: (label: string) => void }) {
  return (
    <label className={`flex items-center gap-5 h-20 px-5 rounded-2 border border-border bg-panel text-11 min-w-0 relative ${current ? `text-s${current.color % 8}` : "text-faint"}`}>
      {current ? <SpeakerDot color={current.color} /> : <span className="w-8 h-8 rounded-full border border-border2" />}
      <span className="truncate font-medium flex-1">{current?.name ?? "unknown"}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} onClick={(e) => e.stopPropagation()}
        className="absolute inset-0 opacity-0 cursor-pointer">
        {!value && <option value="">unknown</option>}
        {cast.map((c) => <option key={c.label} value={c.label}>{c.name}</option>)}
      </select>
      {current && current.gender && <Tag>{current.gender[0].toUpperCase()}</Tag>}
    </label>
  );
}


/** A chapter's name, edited in place; saved when the field loses focus or on Enter. */
function ChapterTitle({ chapter, onSave }: { chapter: Chapter; onSave: (title: string) => void }) {
  const [v, setV] = useState(chapter.title);
  return (
    <input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => onSave(v)} placeholder="name this chapter"
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") (e.target as HTMLInputElement).blur(); }}
      className="bg-transparent border-0 border-b border-transparent hover:border-border2 focus:border-accent outline-none text-11 text-text px-2 py-1 min-w-0 w-[220px] placeholder:text-faint" />
  );
}
