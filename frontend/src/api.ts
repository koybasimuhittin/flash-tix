// Typed fetch wrapper: adds the bearer token, parses `{detail: {code, ...}}` errors
// and logs the user out when the API answers 401 to an authenticated request.
import type { User } from "./types";

const TOKEN_KEY = "flashtix.token";
const USER_KEY = "flashtix.user";
const EXPIRES_KEY = "flashtix.expires_at";

export interface Session {
  token: string;
  user: User;
}

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function loadSession(): Session | null {
  const token = storageGet(TOKEN_KEY);
  const user = storageGet(USER_KEY);
  const expiresAt = Number(storageGet(EXPIRES_KEY));
  if (!token || !user || (expiresAt && Date.now() >= expiresAt)) return null;
  try {
    return { token, user: JSON.parse(user) as User };
  } catch {
    return null;
  }
}

export function saveSession(session: Session, expiresInSeconds: number): void {
  try {
    localStorage.setItem(TOKEN_KEY, session.token);
    localStorage.setItem(USER_KEY, JSON.stringify(session.user));
    localStorage.setItem(EXPIRES_KEY, String(Date.now() + expiresInSeconds * 1000));
  } catch {
    // Private mode etc.: the session then lasts until the page reloads.
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(EXPIRES_KEY);
    // Holds remembered by the event page belong to this user; don't show them to the next one.
    Object.keys(sessionStorage)
      .filter((key) => key.startsWith("flashtix.hold."))
      .forEach((key) => sessionStorage.removeItem(key));
  } catch {
    // ignore
  }
}

let currentToken: string | null = loadSession()?.token ?? null;
let onUnauthorized: () => void = () => {};

export function setToken(token: string | null): void {
  currentToken = token;
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

/** An API error. `code` is the domain code from `detail.code` when there is one. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(describeDetail(status, detail));
    this.status = status;
    this.detail = detail;
    this.code =
      detail && typeof detail === "object" && "code" in detail
        ? String((detail as { code: unknown }).code)
        : null;
  }

  /** Seat ids attached to SEATS_UNAVAILABLE / HOLD_EXPIRED errors. */
  get seats(): string[] {
    const d = this.detail as { seats?: unknown };
    return Array.isArray(d?.seats) ? d.seats.map(String) : [];
  }
}

function describeDetail(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg, ...}]
    return detail.map((e: { msg?: string }) => e.msg ?? "invalid input").join("; ");
  }
  if (detail && typeof detail === "object" && "code" in detail) {
    return String((detail as { code: unknown }).code);
  }
  if (status === 429) return "Too many requests";
  return `Request failed (${status})`;
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (currentToken) headers.Authorization = `Bearer ${currentToken}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.ok) return res;

  // A 401 on a request that carried a token means the token is expired or invalid.
  if (res.status === 401 && headers.Authorization) onUnauthorized();
  let detail: unknown = null;
  try {
    detail = ((await res.json()) as { detail?: unknown }).detail ?? null;
  } catch {
    // Not JSON, e.g. an nginx 429 or 502 page.
  }
  throw new ApiError(res.status, detail);
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};

/**
 * Downloads a file from an endpoint that needs the Authorization header, so a plain
 * `<a href>` cannot be used: fetch → blob → object URL → click a temporary link.
 * Returns false when the server answers 202 (the file is not ready yet).
 */
export async function downloadFile(path: string, fallbackName: string): Promise<boolean> {
  const res = await send("GET", path);
  if (res.status === 202) return false;
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Give the browser a moment to start the download before freeing the blob.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return true;
}

/** Turns any error into a short message for the UI. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return "Too many requests. Slow down and try again in a moment.";
    return err.message;
  }
  if (err instanceof TypeError) return "Cannot reach the server.";
  return err instanceof Error ? err.message : String(err);
}
