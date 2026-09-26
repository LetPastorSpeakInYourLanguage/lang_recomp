import { useCallback, useEffect, useRef, useState } from "react";

export interface Worker { worker_id: string; online: boolean; age_s: number; current_job: string | null; stages: string[]; device?: string }
export interface Task { id: string; project_id: string; kind: string; state: string; note: string; progress: number; error: string | null; started: number; finished: number | null }
export interface Root { id: string; name: string; kind: "colab" | "local"; path: string }
export interface RootState extends Root { active: boolean; reachable: boolean; online: boolean; workers: Worker[] }
export interface AppState { roots: RootState[]; active: string; drive: boolean; root: string | null; workers: Worker[]; tasks: Task[] }
export interface Settings { roots: Root[]; active: string; aligners: Record<string, string>; keep_words: string[] }
export interface HubModel { id: string; downloads: number; likes: number; ctc_likely: boolean; tagged_language: boolean; family: string[] }
export interface AlignerCheck {
  ok: boolean; reason: string; repo?: string; architectures?: string[]; license?: string | null; downloads?: number;
  coverage?: number | null; missing?: string[]; vocab_size?: number; gated?: boolean;
}

export interface Project {
  id: string; name: string; source: string; src_lang: string; tgt_lang: string;
  max_speakers: number | null; clip_start: number | null; clip_end: number | null; duration: number | null;
  created: number;
  /** the series this source belongs to (null = standalone), its place in it, and its YouTube id */
  series_id: string | null; position: number | null; origin_id: string | null; published: string | null;
  counts: { sentences: number; translated: number; translated_by_lang: Record<string, number>; reviewed: number; chapters: number;
    characters: number; genders_set: number; kept: number };
  /** target languages, primary first */
  targets: string[];
  analysis: Record<"separate" | "asr" | "diarize", string | null>;
  import: Task | null;
  meta: Record<string, unknown>;
}

export type SeriesKind = "show" | "channel" | "speaker" | "course" | "news" | "other";
export interface Series {
  id: string; name: string; kind: SeriesKind; feed_url: string | null; src_lang: string; targets: string[];
  settings: { max_speakers?: number | null }; created: number;
  /** what the series and one of its sources are called, e.g. "Channel" / "video" */
  label: string; unit: string;
  counts?: { sources: number; duration: number };
  sources?: Project[];
}
export interface NewVideo { name: string; source: string; clip_start?: number | null; clip_end?: number | null; max_speakers?: number | null }

export interface Job { id: string; stage: string; role: string; root: string; created: number; state: string | null; progress: number | null; error: string | null; result: Record<string, unknown> | null; elapsed_s: number | null; heartbeat: number | null }

export interface Sample { id: number; start: number; end: number; text: string; energy_db: number | null }
export interface Character { label: string; name: string; gender: string | null; important: number; color: number; talk_s: number; sentences: number; samples: Sample[] }

export interface Take {
  take_id: number; sentence_id: number; job_id: string; take: number; text: string; sim: number | null; cer: number | null;
  dur: number | null; dur_s: number | null; asr: string | null; chosen: number; stale: boolean;
}
export interface VoiceLine extends Sentence { takes: Take[] }
export interface VoiceState {
  lines: VoiceLine[]; jobs: Job[]; engine: { model: string; steps: number; speed: number; takes: number }; rate: number | null; lang: string;
}

export interface MixParams { duck_db: number; keep_nonspeech: boolean; nonspeech_db: number; keep_extras: boolean; max_stretch: number; hard_stretch: number; loudness_follow: boolean }
export interface FitLine {
  id: number; start: number; end: number; factor: number; status: "fits" | "borrowed" | "stretched" | "squeezed" | "overflow";
  slot_start: number; slot_end: number; dur: number; overlap_s: number; speaker: string | null; gain_db: number; tr: string; src: string; take_id: number;
}
export interface MixState {
  params: MixParams; defaults: MixParams; has_mix: boolean; mix_mtime: number | null;
  summary: { rendered_at: number; duration: number; lines: FitLine[]; counts: Record<string, number>; missing: { id: number; start: number; en: string }[] } | null;
  lang: string; export: { mp4: string; at: number } | null; tasks: Task[];
}

export interface Budget { syllables: number; est_s: number; slot_s: number; ratio: number | null; max_syllables: number }
export interface Sentence {
  id: number; speaker: string | null; start: number; end: number; slot_s: number; text: string;
  /** translation into `lang` */
  lang: string; tr: string; tr_locked: number; tr_provenance: "machine" | "human" | "reviewed" | null;
  /** id of the chapter holding the line; `chapter_head` marks the first line of a later chapter */
  chapter: number; chapter_head: number; reviewed: number; budget: Budget | null;
  /** effective: the person's choice, else the interjection suggestion */
  mode: "dub" | "keep"; mode_set: "dub" | "keep" | null; mode_suggested: "dub" | "keep";
}

/** Runs from `start` to the next chapter's start; the first opens the clip. */
export interface Chapter { id: number; index: number; title: string; start: number; end: number; lines: number }

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  state: () => req<AppState>("GET", "/api/state"),
  projects: () => req<Project[]>("GET", "/api/projects"),
  project: (p: string) => req<Project>("GET", `/api/projects/${p}`),
  create: (b: NewVideo & { src_lang?: string; tgt_lang?: string }) => req<Project>("POST", "/api/projects", b),
  seriesKinds: () => req<{ kind: SeriesKind; label: string; unit: string }[]>("GET", "/api/series/kinds"),
  seriesList: () => req<Series[]>("GET", "/api/series"),
  series: (s: string) => req<Series>("GET", `/api/series/${s}`),
  createSeries: (b: { name: string; kind: SeriesKind; src_lang: string; targets: string[]; feed_url?: string | null; settings?: Series["settings"] }) =>
    req<Series>("POST", "/api/series", b),
  patchSeries: (s: string, b: Partial<Pick<Series, "name" | "kind" | "src_lang" | "targets" | "feed_url" | "settings">>) =>
    req<Series>("PATCH", `/api/series/${s}`, b),
  addSource: (s: string, b: NewVideo & { origin_id?: string | null; published?: string | null }) =>
    req<Project>("POST", `/api/series/${s}/sources`, b),
  deleteSeries: (s: string) => req<{ released: number }>("DELETE", `/api/series/${s}`),
  orderSeries: (s: string, ids: string[]) => req<Project[]>("PUT", `/api/series/${s}/order`, { ids }),
  attachProject: (p: string, series_id: string | null) => req<Project>("PUT", `/api/projects/${p}/series`, { series_id }),
  analyze: (p: string, root?: string) => req("POST", `/api/projects/${p}/analyze`, { root }),
  settings: () => req<Settings>("GET", "/api/settings"),
  saveSettings: (s: Settings) => req<Settings>("PUT", "/api/settings", s),
  searchAligners: (language: string, q = "") =>
    req<HubModel[]>("GET", `/api/aligners/search?language=${encodeURIComponent(language)}&q=${encodeURIComponent(q)}`),
  checkAligner: (repo: string, language: string) =>
    req<AlignerCheck>("GET", `/api/aligners/check?repo=${encodeURIComponent(repo)}&language=${encodeURIComponent(language)}`),
  realign: (p: string, root?: string) => req<{ align: string; diarize: string; model: string }>("POST", `/api/projects/${p}/realign`, { root }),
  ingest: (p: string) => req<{ sentences: number; characters: number }>("POST", `/api/projects/${p}/ingest`),
  jobs: (p: string) => req<{ colab: Job[]; local: Task[] }>("GET", `/api/projects/${p}/jobs`),
  log: (p: string, j: string) => req<{ log: string }>("GET", `/api/projects/${p}/jobs/${j}/log`),
  characters: (p: string) => req<Character[]>("GET", `/api/projects/${p}/characters`),
  patchCharacter: (p: string, label: string, b: Partial<{ name: string; gender: string; important: boolean }>) =>
    req("PATCH", `/api/projects/${p}/characters/${label}`, b),
  merge: (p: string, source: string, into: string) => req("POST", `/api/projects/${p}/characters/merge`, { source, into }),
  sentences: (p: string, lang?: string) =>
    req<Sentence[]>("GET", `/api/projects/${p}/sentences${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`),
  patchSentence: (p: string, id: number, b: Partial<{ text: string; speaker: string; lang: string; tr: string; tr_locked: boolean; reviewed: boolean;
    mode: "dub" | "keep" | "auto" }>) =>
    req<Sentence>("PATCH", `/api/projects/${p}/sentences/${id}`, b),
  chapters: (p: string) => req<Chapter[]>("GET", `/api/projects/${p}/chapters`),
  toggleChapter: (p: string, at: number) =>
    req<{ added?: number; removed?: number }>("POST", `/api/projects/${p}/chapters/toggle`, { at }),
  renameChapter: (p: string, id: number, title: string) => req<Chapter>("PATCH", `/api/projects/${p}/chapters/${id}`, { title }),
  mergeNext: (p: string, id: number) => req<{ kept: number; removed: number }>("POST", `/api/projects/${p}/sentences/${id}/merge_next`),
  split: (p: string, id: number, word_index: number) =>
    req<{ first: number; second: number }>("POST", `/api/projects/${p}/sentences/${id}/split`, { word_index }),
  voice: (p: string, lang: string) => req<VoiceState>("GET", `/api/projects/${p}/voice?lang=${encodeURIComponent(lang)}`),
  queueVoice: (p: string, b: { root?: string; ids?: number[]; takes?: number; lang?: string }) =>
    req<{ job: string; lines: number; root: string }>("POST", `/api/projects/${p}/voice`, b),
  chooseTake: (p: string, take_id: number) => req("POST", `/api/projects/${p}/voice/choose`, { take_id }),
  takeUrl: (p: string, take_id: number) => `/api/projects/${p}/takes/${take_id}`,
  mix: (p: string, lang: string) => req<MixState>("GET", `/api/projects/${p}/mix?lang=${encodeURIComponent(lang)}`),
  mixParams: (p: string, b: Partial<MixParams>) => req<MixParams>("PUT", `/api/projects/${p}/mix/params`, b),
  renderMix: (p: string, lang: string) => req<{ task: string }>("POST", `/api/projects/${p}/mix/render`, { lang }),
  exportMix: (p: string, lang: string) => req<{ task: string }>("POST", `/api/projects/${p}/mix/export`, { lang }),
  openExport: (p: string) => req("POST", `/api/projects/${p}/mix/open`),
  mixAudio: (p: string, name: "mix" | "dub", v: number | null, lang: string) =>
    `/api/projects/${p}/mix/audio/${name}?lang=${encodeURIComponent(lang)}&v=${v ?? 0}`,
  languages: () => req<{ code: string; name: string; iso3: string; script: string }[]>("GET", "/api/languages"),
  addLanguage: (p: string, lang: string) => req<{ targets: string[] }>("POST", `/api/projects/${p}/languages`, { lang }),
  /** `chapter` is a chapter id; omitted = every chapter */
  translate: (p: string, lang: string, chapter?: number, force = false) =>
    req<{ task: string }>("POST", `/api/projects/${p}/translate`, { chapter, force, lang }),
  media: (p: string, name: "video" | "audio" | "vocals" | "background") => `/api/projects/${p}/media/${name}`,
};

/** Fetch now and every `ms` while mounted; `reload()` refetches on demand. */
export function usePoll<T>(fn: () => Promise<T>, deps: unknown[], ms = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void reload();
    if (!ms) return;
    const t = setInterval(() => void reload(), ms);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, reload, setData };
}

export const fmtTime = (s: number | null | undefined) => {
  if (s == null) return "–";
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
};

export const parseTime = (v: string): number | null => {
  const t = v.trim();
  if (!t) return null;
  const parts = t.split(":").map(Number);
  if (parts.some(isNaN)) return null;
  return parts.reduce((acc, x) => acc * 60 + x, 0);
};
