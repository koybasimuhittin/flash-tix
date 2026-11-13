import { AlertCircle, Download, Loader2, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, downloadFile, errorMessage } from "@/api";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/format";
import { usePolling } from "@/hooks";
import type { EventStats, EventSummary } from "@/types";

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
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-poster text-5xl">My events</h1>
          <p className="mt-2 text-muted-foreground">Sales update every few seconds while this page is open.</p>
        </div>
        <Button asChild>
          <Link to="/organizer/new">
            <Plus /> Create event
          </Link>
        </Button>
      </div>

      <div className="mt-6 flex flex-col gap-2">
        {error && <Alert variant="error">{error}</Alert>}
        {statsError && (
          <Alert variant="error">
            <AlertCircle /> {statsError}
          </Alert>
        )}
      </div>
      {events === null && !error && <p className="mt-8 text-muted-foreground">Loading events…</p>}
      {events?.length === 0 && (
        <div className="mt-8 rounded-xl border border-dashed border-border p-10 text-center">
          <p className="font-semibold">No events yet.</p>
          <p className="mt-1 text-sm text-muted-foreground">Create your first event to start selling seats.</p>
        </div>
      )}
      {events && events.length > 0 && (
        <div className="mt-6 rounded-xl border border-border bg-card px-2 py-1">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Event</TableHead>
                <TableHead>Starts</TableHead>
                <TableHead>Sales open</TableHead>
                <TableHead className="text-right">Sold</TableHead>
                <TableHead className="text-right">Held</TableHead>
                <TableHead className="text-right">Capacity</TableHead>
                <TableHead className="w-40">Sold %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((ev) => {
                const s = stats.get(ev.id);
                const pct = s && ev.capacity ? Math.round((s.sold / ev.capacity) * 100) : 0;
                return (
                  <TableRow key={ev.id}>
                    <TableCell>
                      <Link to={`/events/${ev.id}`} className="font-semibold underline-offset-4 hover:underline">
                        {ev.title}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {ev.venue}, {ev.city}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(ev.starts_at)}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(ev.sales_open_at)}</TableCell>
                    <TableCell className="tabular num text-right font-semibold">{s ? s.sold : "…"}</TableCell>
                    <TableCell className="tabular num text-right">{s ? s.held : "…"}</TableCell>
                    <TableCell className="tabular num text-right">{ev.capacity}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" title={`${pct}%`}>
                          <div className="h-full rounded-full bg-sold transition-[width] duration-700" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="tabular w-9 text-right text-xs text-muted-foreground">{pct}%</span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <ReportDownload />
    </div>
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
    <form className="report mt-8 max-w-lg rounded-xl border border-border bg-card p-5" onSubmit={submit}>
      <h2 className="font-poster text-2xl">Daily sales report</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        A CSV of every booking made that day, generated each night at 03:00 for the day before (Istanbul time).
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="report-date">Day</Label>
          <Input
            id="report-date"
            type="date"
            required
            className="w-44"
            value={date}
            max={istanbulDate(0)}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        <Button type="submit" variant="outline" disabled={busy || !date}>
          {busy ? <Loader2 className="animate-spin" /> : <Download />}
          {busy ? "Downloading…" : "Download CSV"}
        </Button>
      </div>
      {message && (
        <Alert variant={message.kind} className="alert mt-3">
          {message.text}
        </Alert>
      )}
    </form>
  );
}
