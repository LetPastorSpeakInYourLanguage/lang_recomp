import { useCallback, useEffect, useRef, useState } from "react";

export interface Worker { worker_id: string; online: boolean; age_s: number; current_job: string | null; stages: string[]; device?: string }
export interface Task { id: string; project_id: string; kind: string; state: string; note: string; progress: number; error: string | null; started: number; finished: number | null }
export interface Root { id: string; name: string; kind: "colab" | "local" | "bucket" | "folder"; path: string; bucket?: string }
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
  /** the work this source belongs to (a series, or its own single work), its place in it, and its YouTube id */
  series_id: string | null; position: number | null; origin_id: string | null; published: string | null;
  /** its own hidden single-source work (a standalone video), not a series; uid = portable identity */
  standalone: boolean; uid: string;
  counts: { sentences: number; translated: number; translated_by_lang: Record<string, number>; reviewed: number; chapters: number;
    characters: number; genders_set: number; kept: number; linked: number };
  /** target languages, primary first */
  targets: string[];
  analysis: Record<"separate" | "asr" | "diarize", string | null>;
  import: Task | null;
  meta: Record<string, unknown>;
}

export type SeriesKind = "show" | "channel" | "speaker" | "course" | "news" | "other" | "single";  // single: a standalone video's own work
export interface Series {
  id: string; name: string; kind: SeriesKind; feed_url: string | null; src_lang: string; targets: string[];
  settings: { max_speakers?: number | null }; created: number;
  /** what the series and one of its sources are called, e.g. "Channel" / "video" */
  label: string; unit: string;
  counts?: { sources: number; duration: number };
  sources?: Project[];
}
export interface FeedEntry { id: string; title: string; url: string; duration: number | null; section: string; live: boolean; added: boolean }
export type ClipKind = "clip" | "intro" | "opener" | "outro" | "jingle" | "recurring";
export interface ClipLine { id: number; source_id: string; start: number; end: number; speaker: string | null; text: string; tr: string }
export interface Clip {
  id: number; series_id: string | null; source_id: string; source_name?: string; title: string; kind: ClipKind; note: string;
  rev: number; segments: { source_id: string; start: number; end: number }[]; duration: number; recurring: boolean;
  collections: number[]; deleted: number; lines?: ClipLine[];
  /** recurring parts only: how many occurrences are in each state */
  occurrences?: Record<OccurrenceStatus, number>;
  /** languages whose mix of the source is rendered → its mtime (for cache-busting) */
  mixed?: Record<string, number>;
}
export type OccurrenceStatus = "proposed" | "confirmed" | "rejected";
export interface Occurrence { id: number; clip_id: number; source_id: string; source_name: string | null; start: number; end: number; score: number; status: OccurrenceStatus }
export interface PartCandidate {
  origin: { source_id: string; source_name?: string; start: number; end: number };
  members: { source_id: string; source_name?: string; start: number; end: number; score: number }[];
  sources: number; of: number; kind: ClipKind; duration: number;
}
export interface PackageInfo {
  format: string; version: number; exported_at: number; note: string; media: "none" | "opus" | "flac"; languages: string[];
  work: { uid: string; name: string; kind: SeriesKind; src_lang: string; targets: string[] }; sources: number;
  /** the local id of the same work, if it is already in this library */
  here: string | null;
}
export interface ImportReport {
  created: boolean; work: string; sources: { added: string[]; matched: string[] }; lines: number;
  characters: { added: number; matched: number }; clips: { added: number; matched: number };
  translations: Record<string, { written: number; kept_here: number; conflicts: number }>; fetching: string[]; notes: string[];
}
export interface Collection { id: number; name: string; items: number; deleted: number }
export interface BulkStatus {
  jobs: { id: string; state: string | null; progress: number | null; note: string | null; error: string | null; result: Record<string, number> | null }[];
  videos: { done: number; loaded: number; failed: number; queued: number; not_sent: number };
  failures: { id: string; name: string; error: string }[];
}
export interface LibraryInfo {
  id: string; uid: string; name: string; root_id: string; path: string; src_lang: string; targets: string[]; kind: string;
  created: number; scanned: number | null; counts?: { works: number; videos: number };
}
export interface LibraryVideo {
  id: string; name: string; lang: string; group: string | null; subtitles: boolean; subtitles_other: string[];
  lines: number; dubbed: string[]; duration: number | null; size: number | null;
}
export interface LibraryWork {
  id: string; name: string; kind: string; standalone: boolean; speakers: string[]; videos: LibraryVideo[];
  languages: string[]; with_subtitles: number; processed: number; dubbed: number;
}
export type Stage = "fetch" | "transcribe" | "translate" | "voice" | "mix";
export interface RunInfo {
  run: string; name?: string; job?: string | null; root: string; state: string | null; progress?: number | null; note?: string | null;
  stages?: Stage[]; videos?: number; works?: number; done?: Record<Stage, number>; failed?: number; saved?: string[];
  has_results?: boolean; results_at?: number | null; opened_at?: number | null; opening?: boolean; created?: number; finished?: number | null; timings?: Record<string, number>;
  report?: { captions: { video: string; kind: string; captions_raw?: CapCompare; captions_aligned?: CapCompare }[] } | null;
}
export interface CapCompare { words: number; wer: number; timing_median_s: number | null; timing_p90_s: number | null }
export interface NewVideo { name: string; source: string; clip_start?: number | null; clip_end?: number | null; max_speakers?: number | null }

export interface Job { id: string; stage: string; role: string; root: string; created: number; state: string | null; progress: number | null; error: string | null; result: Record<string, unknown> | null; elapsed_s: number | null; heartbeat: number | null }

export interface Sample { id: number; start: number; end: number; text: string; energy_db: number | null }
/** A voice in one source (its diarizer label) and the work character it is. */
export interface Character {
  label: string; uid: string; character_uid: string; name: string; gender: string | null; important: number; color: number;
  role: string; notes: string; names: Record<string, string>; auto: number;
  /** "proposed" = the voice sounds like this character; a person confirms or says who it is */
  status: "proposed" | "confirmed"; score: number | null;
  /** how many other sources of the work this character appears in */
  elsewhere: number;
  matches: { uid: string; name: string; score: number }[];
  talk_s: number; sentences: number; samples: Sample[];
}
export interface CastMember {
  uid: string; series_id: string; name: string; gender: string | null; role: string; notes: string; color: number; important: number;
  auto: number; names: Record<string, string>; talk_s: number;
  appearances: { source_id: string; source_name: string; label: string; status: "proposed" | "confirmed"; score: number | null; talk_s: number }[];
}

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
  /** title of the recurring part whose take this is, when reused from its origin */
  linked?: string | null;
}
export interface MixState {
  params: MixParams; defaults: MixParams; has_mix: boolean; mix_mtime: number | null;
  summary: { rendered_at: number; duration: number; lines: FitLine[]; counts: Record<string, number>; missing: { id: number; start: number; en: string }[] } | null;
  lang: string; export: { mp4: string; at: number } | null; tasks: Task[];
}

export interface Budget { syllables: number; est_s: number; slot_s: number; ratio: number | null; max_syllables: number }
export interface TranslationOption {
  kind: "google" | "short_a" | "short_b"; text: string; source_text: string; need: number | null; sim: number | null;
}

export interface Sentence {
  id: number; speaker: string | null; start: number; end: number; slot_s: number; text: string;
  /** translation into `lang` */
  lang: string; tr: string; tr_locked: number; tr_provenance: "machine" | "human" | "reviewed" | "linked" | null;
  /** inside a confirmed recurring part: translated and voiced once, at its origin */
  linked: { clip_id: number; title: string; kind: ClipKind; source_id: string; source_name: string | null; line_id: number | null } | null;
  /** id of the chapter holding the line; `chapter_head` marks the first line of a later chapter */
  chapter: number; chapter_head: number; reviewed: number; budget: Budget | null;
  /** predicted speed-up the line needs in its window (neighbours included); tight = over the mix's hardest squeeze */
  fit: { need: number; tight: boolean } | null;
  /** when the translation was too long: Google's own and Google's translation of shorter English */
  options: TranslationOption[];
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
  seriesFeed: (s: string, limit = 100) => req<{ title: string; channel: string | null; entries: FeedEntry[] }>("GET", `/api/series/${s}/feed?limit=${limit}`),
  addFromFeed: (s: string, items: Pick<FeedEntry, "id" | "title" | "url">[], clip: { clip_start?: number | null; clip_end?: number | null } = {}, remote = false) =>
    req<{ added: string[]; skipped: { id: string; reason: string }[] }>("POST", `/api/series/${s}/feed/add`, { items, ...clip, remote }),
  bulkStatus: (s: string) => req<BulkStatus>("GET", `/api/series/${s}/bulk`),
  bulkQueue: (s: string, b: { root?: string; batch?: number; height?: number } = {}) =>
    req<{ jobs: string[]; videos: number; root: string }>("POST", `/api/series/${s}/bulk`, b),
  bulkLoad: (s: string) => req<{ loaded: string[]; errors: { id: string; error: string }[] }>("POST", `/api/series/${s}/bulk/load`),
  bulkRetry: (s: string) => req<{ jobs: string[]; videos: number }>("POST", `/api/series/${s}/bulk/retry`),
  clips: (q: { series?: string; source?: string; collection?: number; kind?: ClipKind; deleted?: boolean; lang?: string } = {}) =>
    req<Clip[]>("GET", `/api/clips?${new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString()}`),
  createClip: (b: { source_id: string; title: string; kind?: ClipKind; note?: string; first_line?: number; last_line?: number; chapter_id?: number; start?: number; end?: number }) =>
    req<Clip>("POST", "/api/clips", b),
  patchClip: (id: number, b: Partial<Pick<Clip, "title" | "kind" | "note">>) => req<Clip>("PATCH", `/api/clips/${id}`, b),
  removeClip: (id: number) => req<Clip>("DELETE", `/api/clips/${id}`),
  restoreClip: (id: number) => req<Clip>("POST", `/api/clips/${id}/restore`),
  setClipCollections: (id: number, collection_ids: number[]) => req<{ collection_ids: number[] }>("PUT", `/api/clips/${id}/collections`, { collection_ids }),
  searchClip: (id: number) => req<Occurrence[]>("POST", `/api/clips/${id}/search`),
  occurrences: (id: number) => req<Occurrence[]>("GET", `/api/clips/${id}/occurrences`),
  setOccurrence: (id: number, status: OccurrenceStatus) => req<Occurrence>("PATCH", `/api/occurrences/${id}`, { status }),
  confirmAll: (id: number) => req<{ confirmed: number }>("POST", `/api/clips/${id}/occurrences/confirm_all`),
  discover: (s: string, min_s = 8) => req<PartCandidate[]>("GET", `/api/series/${s}/discover?min_s=${min_s}`),
  collections: (deleted = false) => req<Collection[]>("GET", `/api/collections?deleted=${deleted}`),
  createCollection: (name: string) => req<Collection>("POST", "/api/collections", { name }),
  renameCollection: (id: number, name: string) => req<Collection>("PATCH", `/api/collections/${id}`, { name }),
  archiveCollection: (id: number) => req<Collection>("DELETE", `/api/collections/${id}`),
  restoreCollection: (id: number) => req<Collection>("POST", `/api/collections/${id}/restore`),
  exportWork: (s: string, b: { langs: string[]; media: "none" | "opus" | "flac"; takes: boolean; note: string }) =>
    req<{ name: string; path: string; size: number }>("POST", `/api/series/${s}/export`, b),
  exportUrl: (name: string) => `/api/exports/${encodeURIComponent(name)}`,
  openExports: () => req("POST", "/api/exports/open"),
  inspectPackage: (path: string) => req<PackageInfo>("POST", "/api/import/inspect", { path }),
  importPackage: (path: string, fetch = true) => req<ImportReport>("POST", "/api/import", { path, fetch }),
  libraries: () => req<LibraryInfo[]>("GET", "/api/libraries"),
  createLibrary: (b: { name: string; root: string; path: string; src_lang: string; targets: string[]; kind: string }) =>
    req<LibraryInfo>("POST", "/api/libraries", b),
  library: (id: string) => req<LibraryInfo & { works: LibraryWork[] }>("GET", `/api/libraries/${id}`),
  scanLibrary: (id: string) => req<{ works: number; new_works: number; videos: number; new_videos: number }>("POST", `/api/libraries/${id}/scan`),
  loadSubtitles: (id: string, only?: string[]) => req<{ loaded: number; failed: { id: string; error: string }[] }>(
    "POST", `/api/libraries/${id}/load_subtitles`, { only }),
  createRun: (b: { videos: string[]; root: string; stages?: Stage[]; options?: Record<string, unknown>; name?: string; owner?: string }) =>
    req<{ run: string; job?: string | null; dir?: string | null; root: string; videos: number; works: number; stages: Stage[] }>("POST", "/api/runs", b),
  runs: (owner: string) => req<RunInfo[]>("GET", `/api/runs?owner=${encodeURIComponent(owner)}`),
  rootRuns: (root: string) => req<{ runs: RunInfo[]; last_sync: number | null; syncing: boolean }>("GET", `/api/roots/${encodeURIComponent(root)}/runs`),
  syncRoot: (root: string) => req<{ task: string }>("POST", `/api/roots/${encodeURIComponent(root)}/sync`),
  openRun: (root: string, run: string) => req<{ works: string[]; sources: { added: string[]; matched: string[] }; lines: number; notes: string[] }>(
    "POST", `/api/runs/${root}/${run}/open`),
  deleteSeries: (s: string) => req<{ released: number }>("DELETE", `/api/series/${s}`),
  orderSeries: (s: string, ids: string[]) => req<Project[]>("PUT", `/api/series/${s}/order`, { ids }),
  attachProject: (p: string, series_id: string | null) => req<Project>("PUT", `/api/projects/${p}/series`, { series_id }),
  retryImport: (p: string) => req<{ task: string }>("POST", `/api/projects/${p}/import`),
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
  confirmCharacter: (p: string, label: string) => req("POST", `/api/projects/${p}/characters/${label}/confirm`),
  linkCharacter: (p: string, label: string, character_uid: string | null) =>
    req("POST", `/api/projects/${p}/characters/${label}/link`, { character_uid }),
  cast: (s: string) => req<CastMember[]>("GET", `/api/series/${s}/cast`),
  patchCast: (uid: string, b: Partial<{ name: string; gender: string; important: boolean; role: string; notes: string }>) =>
    req<CastMember>("PATCH", `/api/cast/${uid}`, b),
  castName: (uid: string, lang: string, name: string) => req<CastMember>("PUT", `/api/cast/${uid}/names/${lang}`, { name }),
  bank: (uid: string) => req<{
    rows: { source_id: string; source_name: string | null; line_id: number; start: number; end: number; text: string; role: "bank" | "heldout" | "excluded"; manual: number }[];
    candidates: { source_id: string; source_name: string | null; id: number; start: number; end: number; text: string; secs: number; clean: boolean }[];
  }>("GET", `/api/cast/${uid}/bank`),
  rebuildBank: (uid: string) => req("POST", `/api/cast/${uid}/bank/rebuild`),
  pinBank: (uid: string, source_id: string, line_id: number, role: "bank" | "heldout" | "excluded") =>
    req("PUT", `/api/cast/${uid}/bank`, { source_id, line_id, role }),
  bankAudio: (uid: string, source_id: string, line_id: number) => `/api/cast/${uid}/bank/${source_id}/${line_id}`,
  mergeCast: (uid: string, into: string) => req<CastMember>("POST", `/api/cast/${uid}/merge`, { into }),
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
