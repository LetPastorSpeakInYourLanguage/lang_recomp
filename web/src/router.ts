import { useEffect, useState } from "react";

/** Hash routes: #/ · #/s/<series> · #/p/<project>/<screen>. Hash routing keeps the static build
 *  servable by FastAPI's StaticFiles with no server-side fallback. */
export type Screen = "overview" | "characters" | "transcript" | "translate" | "voice" | "mix";
export interface Route { project: string | null; screen: Screen; settings?: boolean; series?: string }

function parse(): Route {
  if (location.hash.startsWith("#/settings")) return { project: null, screen: "overview", settings: true };
  const s = location.hash.match(/^#\/s\/([^/]+)/);
  if (s) return { project: null, screen: "overview", series: decodeURIComponent(s[1]) };
  const m = location.hash.match(/^#\/p\/([^/]+)(?:\/(\w+))?/);
  if (!m) return { project: null, screen: "overview" };
  return { project: decodeURIComponent(m[1]), screen: (m[2] as Screen) || "overview" };
}

export function useRoute(): Route {
  const [r, setR] = useState(parse);
  useEffect(() => {
    const on = () => setR(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
}

export function goSeries(series: string) {
  location.hash = `#/s/${encodeURIComponent(series)}`;
}

export function go(project: string | null, screen: Screen = "overview") {
  location.hash = project ? `#/p/${encodeURIComponent(project)}/${screen}` : "#/";
}
