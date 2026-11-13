import { CalendarDays, Download, Loader2, MapPin } from "lucide-react";
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api, downloadFile, errorMessage } from "@/api";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatDateTime, formatPrice } from "@/format";
import { usePolling } from "@/hooks";
import type { Booking } from "@/types";

const POLL_MS = 2000;

export default function BookingsPage() {
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBookings(await api.get<Booking[]>("/api/booking/me"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  // Poll every 2 s while a ticket PDF is still being generated, then stop.
  const pending = bookings === null || bookings.some((b) => !b.ticket_ready);
  usePolling(load, POLL_MS, pending);

  async function download(booking: Booking) {
    setDownloading(booking.id);
    try {
      const ready = await downloadFile(`/api/booking/${booking.id}/ticket`, `flashtix-${booking.id}.pdf`);
      if (!ready) setError("The ticket is still being generated. Try again in a few seconds.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="font-poster text-5xl">My tickets</h1>
      {error && (
        <Alert variant="error" className="mt-6">
          {error}
        </Alert>
      )}
      {bookings === null && !error && <p className="mt-8 text-muted-foreground">Loading tickets…</p>}
      {bookings?.length === 0 && (
        <div className="mt-8 rounded-xl border border-dashed border-border p-10 text-center">
          <p className="font-semibold">No tickets yet.</p>
          <p className="mt-1 text-sm text-muted-foreground">When you buy seats, your tickets show up here.</p>
          <Button asChild className="mt-5">
            <Link to="/">Find an event</Link>
          </Button>
        </div>
      )}

      <div className="mt-8 flex flex-col gap-5">
        {bookings?.map((b) => (
          <article key={b.id} className="booking flex flex-col overflow-hidden rounded-xl border border-border bg-card sm:flex-row">
            <div className="min-w-0 flex-1 p-5 sm:p-6">
              <h2 className="font-poster text-3xl">{b.event_title}</h2>
              <div className="mt-3 flex flex-col gap-1 text-sm text-muted-foreground sm:flex-row sm:gap-5">
                <span className="inline-flex items-center gap-1.5">
                  <CalendarDays className="size-4" /> {formatDateTime(b.event_starts_at)}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="size-4" /> {b.venue}, {b.city}
                </span>
              </div>
              <ul className="mt-4 flex flex-wrap gap-1.5">
                {(b.seats ?? []).map((s) => (
                  <li key={s.seat_id} className="tabular rounded-md bg-muted px-2 py-1 text-xs font-semibold">
                    {s.seat_id}
                  </li>
                ))}
                {!b.seats && <li className="text-sm">{b.seat_count} seats</li>}
              </ul>
            </div>
            <div className="perforation-x sm:hidden" />
            <div className="perforation-y hidden sm:block" />
            <div className="flex flex-col justify-between gap-4 bg-stub/15 p-5 sm:w-56 sm:p-6">
              <div>
                <p className="text-xs text-muted-foreground">Total paid</p>
                <p className="tabular text-2xl font-bold">{formatPrice(b.total_price_cents)}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Booked {formatDateTime(b.created_at)}
                </p>
              </div>
              {b.ticket_ready ? (
                <Button onClick={() => download(b)} disabled={downloading === b.id}>
                  {downloading === b.id ? <Loader2 className="animate-spin" /> : <Download />}
                  {downloading === b.id ? "Downloading…" : "Download ticket (PDF)"}
                </Button>
              ) : (
                <p className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Generating ticket…
                </p>
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
