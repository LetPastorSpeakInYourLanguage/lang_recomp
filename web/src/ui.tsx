import type { ReactNode } from "react";
import { Pause, Play } from "lucide-react";
import { play, usePlaying } from "./player";

/** Flush panels divided by 1px rules; mono for every value, sans for language. */
export function Panel({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`bg-panel border border-border rounded-3 ${className}`}>
      {(title || actions) && (
        <div className="flex items-center gap-8 px-12 py-7 border-b border-border min-h-[34px]">
          {title && <div className="text-10.5 uppercase tracking-widest text-dim font-semibold flex-1 min-w-0">{title}</div>}
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function Button({ children, onClick, variant = "default", disabled, title, type = "button" }: {
  children: ReactNode; onClick?: () => void; variant?: "default" | "primary" | "danger" | "ghost"; disabled?: boolean; title?: string; type?: "button" | "submit";
}) {
  const styles = {
    default: "bg-panel2 border-border2 text-text hover:bg-panel3",
    primary: "bg-accent border-accent text-white hover:bg-accent2",
    danger: "bg-badbg border-bad text-bad",
    ghost: "bg-transparent border-transparent text-dim hover:bg-panel3 hover:text-text",
  };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled}
      className={`border h-24 px-9 rounded-2 text-11 font-medium whitespace-nowrap inline-flex items-center gap-5 disabled:opacity-45 ${styles[variant]}`}>
      {children}
    </button>
  );
}

type Tone = "neutral" | "good" | "warn" | "bad" | "accent" | "cross";
export function Tag({ children, tone = "neutral", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  const tones: Record<Tone, string> = {
    neutral: "bg-panel3 text-dim border-border2",
    good: "bg-goodbg text-good border-good",
    warn: "bg-warnbg text-warn border-warn",
    bad: "bg-badbg text-bad border-bad",
    accent: "bg-soft text-accent border-accent",
    cross: "bg-crossbg text-cross border-cross",
  };
  return <span title={title} className={`inline-block border rounded-2 px-5 py-1 text-9.5 font-mono whitespace-nowrap leading-none ${tones[tone]}`}>{children}</span>;
}

export const stateTone = (s: string | null | undefined): Tone =>
  s === "done" ? "good" : s === "failed" ? "bad" : s === "running" || s === "claimed" ? "accent" : "neutral";

export function Progress({ value, tone = "accent" }: { value: number; tone?: "accent" | "good" | "warn" | "bad" }) {
  return (
    <div className="h-4 bg-panel3 rounded-full overflow-hidden">
      <div className={`h-full ${{ accent: "bg-accent", good: "bg-good", warn: "bg-warn", bad: "bg-bad" }[tone]} transition-[width] duration-300`} style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} />
    </div>
  );
}

/** Round play/stop button for a media slice, driven by the shared player. */
export function PlayButton({ src, start, end, k, size = 20 }: { src: string; start: number; end: number; k: string; size?: number }) {
  const playing = usePlaying() === k;
  return (
    <button onClick={(e) => { e.stopPropagation(); play(src, start, end, k); }} title={playing ? "Stop" : "Play"}
      style={{ width: size, height: size }}
      className={`rounded-full border flex items-center justify-center flex-none ${playing ? "bg-accent border-accent text-white" : "bg-panel border-border2 text-dim hover:text-accent hover:border-accent"}`}>
      {playing ? <Pause size={size * 0.5} /> : <Play size={size * 0.5} className="ml-1" />}
    </button>
  );
}

/** "from Intro · Episode 1": this line belongs to a recurring part dubbed at its origin. */
export function LinkedTag({ linked }: { linked: { title: string; source_name: string | null } }) {
  return <Tag tone="cross" title="Part of a confirmed recurring part: translated and voiced once, at its origin, and reused here">
    from {linked.title}{linked.source_name ? ` · ${linked.source_name}` : ""}</Tag>;
}

export function SpeakerDot({ color }: { color: number }) {
  return <span className={`inline-block w-8 h-8 rounded-full bg-s${color % 8} flex-none`} />;
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-44 px-20 gap-8 text-dim">
      {icon && <div className="text-faint">{icon}</div>}
      <div className="text-13 font-semibold text-text">{title}</div>
      {children && <div className="text-11.5 max-w-[420px] leading-relaxed">{children}</div>}
    </div>
  );
}

/** Dub this line, or keep the speaker's original voice (interjections like "wow"). */
export function ModeToggle({ mode, set, suggested, onChange }: {
  mode: "dub" | "keep"; set: "dub" | "keep" | null; suggested: "dub" | "keep"; onChange: (m: "dub" | "keep" | "auto") => void;
}) {
  return (
    <div className="inline-flex items-center gap-4">
      <div className="inline-flex border border-border2 rounded-3 overflow-hidden h-20">
        {(["dub", "keep"] as const).map((m, i) => (
          <button key={m} onClick={(e) => { e.stopPropagation(); onChange(m); }}
            title={m === "dub" ? "Dub this line in the target language" : "Keep the original voice for this line (short interjections read fine in any language)"}
            className={`px-6 text-10 ${i ? "border-l border-border2" : ""} ${mode === m ? (m === "keep" ? "bg-cross text-white" : "bg-accent text-white") : "bg-panel text-dim hover:bg-panel3"}`}>
            {m === "dub" ? "Dub" : "Keep original"}
          </button>
        ))}
      </div>
      {set === null ? (
        <span className="text-9.5 text-faint" title="Chosen automatically from the keep-word list (Folders & settings)">auto</span>
      ) : set !== suggested ? (
        <button onClick={(e) => { e.stopPropagation(); onChange("auto"); }} className="bg-transparent border-0 p-0 text-9.5 text-accent"
          title="Go back to the automatic suggestion">reset</button>
      ) : null}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T | null; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex border border-border2 rounded-3 overflow-hidden h-24">
      {options.map((o, i) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={`px-9 text-11 ${i ? "border-l border-border2" : ""} ${value === o.value ? "bg-accent text-white" : "bg-panel text-dim hover:bg-panel3"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
