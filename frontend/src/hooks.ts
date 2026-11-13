import { useEffect, useRef, useState } from "react";

/**
 * Calls `fn` now and then every `intervalMs` while `enabled`. A new call never starts
 * while the previous one is still running, and polling pauses while the tab is hidden.
 */
export function usePolling(fn: () => Promise<void>, intervalMs: number, enabled = true): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    let running = false;
    const tick = async () => {
      if (running || document.hidden) return;
      running = true;
      try {
        await fnRef.current();
      } finally {
        running = false;
      }
    };
    void tick();
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
}

/** The current time in ms, re-rendered every `intervalMs`. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
