import { useEffect, useState } from "react";

/**
 * One shared audio element plays any [start, end) slice of a project's media. Every
 * "play this line" button in the app goes through it, so starting one clip always
 * stops the last and there is exactly one thing making sound.
 */
const el = new Audio();
el.preload = "auto";
let stopAt = Infinity;
let current: string | null = null;
const listeners = new Set<(key: string | null) => void>();

function emit() {
  listeners.forEach((l) => l(current));
}

el.addEventListener("timeupdate", () => {
  if (el.currentTime >= stopAt) stop();
});
el.addEventListener("ended", () => stop());

export function play(src: string, start: number, end: number, key: string) {
  if (current === key && !el.paused) return stop();
  if (!el.src.endsWith(src)) el.src = src;
  stopAt = end;
  current = key;
  const go = () => {
    el.currentTime = start;
    void el.play();
  };
  if (el.readyState >= 1) go();
  else el.addEventListener("loadedmetadata", go, { once: true });
  emit();
}

export function stop() {
  el.pause();
  current = null;
  stopAt = Infinity;
  emit();
}

/** Which clip key is playing now (for the play/stop icon on each button). */
export function usePlaying(): string | null {
  const [k, setK] = useState<string | null>(current);
  useEffect(() => {
    listeners.add(setK);
    return () => void listeners.delete(setK);
  }, []);
  return k;
}
