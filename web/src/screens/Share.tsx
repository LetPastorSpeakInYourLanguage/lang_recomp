import { FolderOpen, PackageOpen, Share2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, usePoll } from "../api";
import { langName, useLangNames } from "../shell/LangBar";
import { Button, Empty, Panel, Segmented } from "../ui";

type Media = "none" | "opus" | "flac";

/** Share a work with another team: one .lbwork file with the language-neutral work
 *  (sources, transcript, chapters, cast and voice banks, clips) and the languages you
 *  choose. They add their own language without redoing the rest. */
export default function Share({ id }: { id: string }) {
  useLangNames();
  const w = usePoll(() => api.series(id), [id]);
  const [langs, setLangs] = useState<string[] | null>(null);
  const [media, setMedia] = useState<Media>("opus");
  const [takes, setTakes] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<{ name: string; path: string; size: number } | null>(null);
  useEffect(() => { if (w.data && langs === null) setLangs(w.data.targets); }, [w.data, langs]);
  if (w.error) return <Empty icon={<Share2 size={28} />} title="No such work">{w.error}</Empty>;
  if (!w.data || !langs) return <div className="p-16 text-11.5 text-faint">Loading…</div>;
  const d = w.data;

  async function run() {
    setBusy(true); setErr(null); setDone(null);
    try { setDone(await api.exportWork(id, { langs: langs ?? [], media, takes, note })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="p-16 max-w-[900px] mx-auto w-full flex flex-col gap-12">
      <div>
        <div className="text-15 font-semibold flex items-center gap-8"><Share2 size={15} className="text-accent" />Share · {d.name}</div>
        <div className="text-11.5 text-dim">
          Makes one file another team can open in Lang-Bridge. It always carries the work itself — every {d.unit}'s origin and clip
          range, the checked transcript, chapters, the cast with their voice banks, clips and recurring parts — so they can dub it
          into their own language without redoing any of it. Nothing about this computer travels (folders, jobs, settings).
        </div>
      </div>
      <Panel title="What to include">
        <div className="p-12 flex flex-col gap-12 text-11.5">
          <div className="flex flex-col gap-5">
            <span className="label">Languages (their translations, names, speaking rates)</span>
            <div className="flex gap-10 flex-wrap">
              {d.targets.map((t) => (
                <label key={t} className="flex items-center gap-5">
                  <input type="checkbox" checked={langs.includes(t)} onChange={() => setLangs(langs.includes(t) ? langs.filter((x) => x !== t) : [...langs, t])} />
                  <span className="font-mono">{t}</span> {langName(t)}
                </label>
              ))}
            </div>
            <span className="text-10.5 text-faint">Leave all unticked to share only the work, for a team starting a new language.</span>
          </div>
          <div className="flex flex-col gap-5">
            <span className="label">Media</span>
            <Segmented<Media> value={media} onChange={setMedia} options={[
              { value: "opus", label: "Voice stems, compact" }, { value: "flac", label: "Voice stems, lossless" }, { value: "none", label: "No media" }]} />
            <span className="text-10.5 text-faint">
              {media === "none" ? "Smallest: they fetch the videos from the origin again and separate the voices on their worker."
                : "They skip voice separation; the video itself is fetched from the origin for Transcript."}
            </span>
          </div>
          <label className="flex items-center gap-6"><input type="checkbox" checked={takes} onChange={() => setTakes(!takes)} />
            Include the chosen voice takes of the ticked languages</label>
          <label className="grid gap-4"><span className="label">Note for the other team</span>
            <input className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" /></label>
          <div className="flex items-center gap-8">
            <span className="flex-1" />
            {err && <span className="text-bad">{err}</span>}
            <Button variant="primary" disabled={busy} onClick={() => void run()}><PackageOpen size={12} />{busy ? "Packing…" : "Make the package"}</Button>
          </div>
        </div>
      </Panel>
      {done && (
        <Panel title="Ready">
          <div className="p-12 flex items-center gap-8 flex-wrap text-11.5">
            <span className="font-mono flex-1 min-w-[200px] truncate" title={done.path}>{done.name}</span>
            <span className="font-mono text-dim">{(done.size / 1e6).toFixed(1)} MB</span>
            <a className="text-accent" href={api.exportUrl(done.name)} download>Download</a>
            <Button onClick={() => void api.openExports()}><FolderOpen size={12} />Show in folder</Button>
          </div>
        </Panel>
      )}
    </div>
  );
}
