import { CheckCircle2, Loader, Search, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { api, type AlignerCheck, type HubModel } from "../api";
import { Button, Panel, Tag } from "../ui";

/** Forced-alignment model per language: any Hugging Face CTC model whose
 *  vocabulary covers the language's characters. Search the Hub, vet, assign. */
export default function Aligners({ value, onChange }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  const [lang, setLang] = useState("am");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<HubModel[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, AlignerCheck | "busy">>({});
  const rows = Object.entries(value);

  async function find() {
    setBusy(true);
    setErr(null);
    try { setResults(await api.searchAligners(lang.trim().toLowerCase(), q.trim())); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  async function check(repo: string, language: string) {
    const key = `${language}:${repo}`;
    setChecks((c) => ({ ...c, [key]: "busy" }));
    try {
      const r = await api.checkAligner(repo, language);
      setChecks((c) => ({ ...c, [key]: r }));
    } catch (e) {
      setChecks((c) => ({ ...c, [key]: { ok: false, reason: (e as Error).message } }));
    }
  }

  const verdict = (repo: string, language: string) => {
    const c = checks[`${language}:${repo}`];
    if (!c) return <Button variant="ghost" onClick={() => void check(repo, language)}>Check</Button>;
    if (c === "busy") return <Loader size={12} className="animate-spin text-dim" />;
    return (
      <span className={`flex items-center gap-4 text-10.5 ${c.ok ? "text-good" : "text-bad"}`} title={c.reason}>
        {c.ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
        {c.ok ? `can align${c.coverage != null ? ` · covers ${Math.round(c.coverage * 100)}%` : ""}` : c.reason.slice(0, 70)}
        {c.license && <Tag>{c.license}</Tag>}
      </span>
    );
  };

  return (
    <Panel title="Word aligners (per language)">
      <div className="px-12 pt-10 text-11 text-dim">
        After transcription, each word is pinned to the audio by a CTC model of that language, which fixes word timings and
        speaker-boundary words. Any Hugging Face model built for CTC with a character vocabulary works, including ones whisperX does not list.
      </div>
      <table className="w-full border-collapse text-11.5 mt-8">
        <thead>
          <tr className="text-left text-9.5 uppercase tracking-label text-faint">
            <th className="px-12 py-5 font-semibold border-b border-border w-[90px]">Language</th>
            <th className="px-12 py-5 font-semibold border-b border-border">Model (Hugging Face repo)</th>
            <th className="px-12 py-5 font-semibold border-b border-border">Check</th>
            <th className="border-b border-border w-[30px]" />
          </tr>
        </thead>
        <tbody>
          {rows.map(([l, repo]) => (
            <tr key={l} className="border-b border-border last:border-0">
              <td className="px-12 py-5 font-mono">{l}</td>
              <td className="px-12 py-5">
                <input className="field w-full font-mono" value={repo} onChange={(e) => onChange({ ...value, [l]: e.target.value })} />
              </td>
              <td className="px-12 py-5">{verdict(repo, l)}</td>
              <td className="pr-8">
                <button title="Remove" onClick={() => { const v = { ...value }; delete v[l]; onChange(v); }}
                  className="bg-transparent border-0 text-faint hover:text-bad p-2"><Trash2 size={12} /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="border-t border-border px-12 py-10 flex flex-col gap-8">
        <div className="flex items-center gap-8 flex-wrap">
          <span className="label">Find on Hugging Face</span>
          <input className="field w-[70px] font-mono" value={lang} onChange={(e) => setLang(e.target.value)} placeholder="am" title="ISO 639-1 code, e.g. am, om, ti, sw" />
          <input className="field flex-1 min-w-[160px]" value={q} onChange={(e) => setQ(e.target.value)} placeholder="optional words, e.g. wav2vec2, ethio"
            onKeyDown={(e) => e.key === "Enter" && void find()} />
          <Button onClick={() => void find()} disabled={busy || !lang.trim()}><Search size={12} />{busy ? "Searching…" : "Search"}</Button>
        </div>
        {err && <div className="text-11 text-bad">{err}</div>}
        {results && (
          <div className="border border-border rounded-3 divide-y divide-border max-h-[340px] overflow-y-auto">
            {results.map((m) => (
              <div key={m.id} className="flex items-center gap-8 px-8 py-5 text-11.5">
                <a href={`https://huggingface.co/${m.id}`} target="_blank" rel="noreferrer" className="font-mono truncate flex-1 min-w-0">{m.id}</a>
                {m.ctc_likely ? <Tag tone="accent">{m.family.join(" · ") || "ctc"}</Tag> : <Tag>not CTC</Tag>}
                <span className="text-10 font-mono text-faint w-[80px] text-right">{m.downloads.toLocaleString()} dl</span>
                <div className="w-[260px] flex justify-end">{verdict(m.id, lang.trim().toLowerCase())}</div>
                <Button onClick={() => onChange({ ...value, [lang.trim().toLowerCase()]: m.id })}>Use for {lang.trim().toLowerCase()}</Button>
              </div>
            ))}
            {!results.length && <div className="px-8 py-6 text-11 text-faint">No speech-recognition models found.</div>}
          </div>
        )}
      </div>
    </Panel>
  );
}
