/** Parses an API timestamp (ISO 8601 with an explicit UTC offset) to epoch ms. */
export function toMillis(iso: string): number {
  return Date.parse(iso);
}

/**
 * Server clock minus local clock, in ms. The server read its clock roughly halfway through
 * the round trip, so compare against the midpoint between sending and receiving.
 */
export function clockOffset(serverTimeIso: string, sentAt: number, receivedAt: number): number {
  return toMillis(serverTimeIso) - (sentAt + receivedAt) / 2;
}

export function formatPrice(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 3725 s → "1:02:05", 65 s → "1:05". Rounds down, so a fresh 600 s hold shows 10:00, not 10:01. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  if (days > 0) return `${days}d ${h}h ${m}m`;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${sec}`;
  return `${m}:${sec}`;
}

export interface CountdownParts {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
}

/** Splits a countdown into whole days, hours, minutes and seconds (rounded down, never negative). */
export function countdownParts(totalSeconds: number): CountdownParts {
  const s = Math.max(0, Math.floor(totalSeconds));
  return {
    days: Math.floor(s / 86400),
    hours: Math.floor((s % 86400) / 3600),
    minutes: Math.floor((s % 3600) / 60),
    seconds: s % 60,
  };
}
