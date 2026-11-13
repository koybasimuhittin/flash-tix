import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, downloadFile, errorMessage } from "../api";
import { formatDateTime } from "../format";
import { usePolling } from "../hooks";
import type { EventStats, EventSummary } from "../types";

/** The stats endpoint accepts at most 100 ids per call. */
const STATS_BATCH = 100;
const STATS_POLL_MS = 5000;

/** Reports cover one Europe/Istanbul calendar day. */
const REPORT_TZ = "Europe/Istanbul";
const DAY_MS = 86_400_000;

/** YYYY-MM-DD in Istanbul, `daysAgo` days before now (Istanbul has no DST). */
function istanbulDate(daysAgo: number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: REPORT_TZ }).format(Date.now() - daysAgo * DAY_MS);
}

export default function OrganizerPage() {
  const [events, setEvents] = useState<EventSummary[] | null>(null);
  const [stats, setStats] = useState<Map<number, EventStats>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<EventSummary[]>("/api/events/mine")
      .then(setEvents)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  // One stats request for all events (not one per event, which would hit the rate limit).
  const loadStats = useCallback(async () => {
    if (!events?.length) return;
    try {
      const next = new Map<number, EventStats>();
      for (let i = 0; i < events.length; i += STATS_BATCH) {
        const ids = events.slice(i, i + STATS_BATCH).map((e) => e.id);
        const rows = await api.get<EventStats[]>(`/api/booking/stats?event_ids=${ids.join(",")}`);
        rows.forEach((row) => next.set(row.event_id, row));
      }
      setStats(next);
      setStatsError(null);
    } catch (err) {
      setStatsError(`Could not load sales numbers: ${errorMessage(err)}`);
    }
  }, [events]);

  usePolling(loadStats, STATS_POLL_MS, Boolean(events?.length));

  return (
    <>
      <div className="page-head">
        <h1>My events</h1>
        <Link to="/organizer/new" className="button primary">
          + Create event
        </Link>
      </div>
      {error && <p className="alert alert-error">{error}</p>}
      {statsError && <p className="alert alert-error">{statsError}</p>}
      {events === null && !error && <p className="muted">Loading…</p>}
      {events?.length === 0 && <p className="muted">You have not created any events yet.</p>}
      {events && events.length > 0 && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Starts</th>
                <th>Sales open</th>
                <th className="num">Sold</th>
                <th className="num">Held</th>
                <th className="num">Capacity</th>
                <th>Sold %</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const s = stats.get(ev.id);
                const pct = s && ev.capacity ? Math.round((s.sold / ev.capacity) * 100) : 0;
                return (
                  <tr key={ev.id}>
                    <td>
                      <Link to={`/events/${ev.id}`}>{ev.title}</Link>
                      <div className="muted small">
                        {ev.venue} · {ev.city}
                      </div>
                    </td>
                    <td>{formatDateTime(ev.starts_at)}</td>
                    <td>{formatDateTime(ev.sales_open_at)}</td>
                    <td className="num">{s ? s.sold : "…"}</td>
                    <td className="num">{s ? s.held : "…"}</td>
                    <td className="num">{ev.capacity}</td>
                    <td>
                      <div className="bar" title={`${pct}%`}>
                        <div style={{ width: `${pct}%` }} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ReportDownload />
    </>
  );
}

function ReportDownload() {
  // The scheduled report runs at 03:00 for the previous day, so yesterday is the newest one.
  const [date, setDate] = useState(() => istanbulDate(1));
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await downloadFile(`/api/booking/reports/${date}`, `report-${date}.csv`);
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof ApiError && err.status === 404 ? `No report for ${date}.` : errorMessage(err),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card report" onSubmit={submit}>
      <h2>Daily sales report</h2>
      <p className="muted small">
        CSV produced by the daily-report Cloud Function each night at 03:00 for the previous day (days are
        Europe/Istanbul).
      </p>
      <div className="inline">
        <input type="date" required value={date} max={istanbulDate(0)} onChange={(e) => setDate(e.target.value)} />
        <button className="primary" disabled={busy || !date}>
          {busy ? "Downloading…" : "Download CSV"}
        </button>
      </div>
      {message && <p className={`alert alert-${message.kind}`}>{message.text}</p>}
    </form>
  );
}
