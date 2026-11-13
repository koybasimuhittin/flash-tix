import { useCallback, useState } from "react";
import { api, errorMessage, downloadFile } from "../api";
import { formatDateTime, formatPrice } from "../format";
import { usePolling } from "../hooks";
import type { Booking } from "../types";

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
    <>
      <h1>My bookings</h1>
      {error && <p className="alert alert-error">{error}</p>}
      {bookings === null && !error && <p className="muted">Loading…</p>}
      {bookings?.length === 0 && <p className="muted">You have no bookings yet.</p>}
      <div className="bookings">
        {bookings?.map((b) => (
          <div key={b.id} className="card booking">
            <div>
              <h2>{b.event_title}</h2>
              <p className="muted">
                {b.venue} · {b.city} · {formatDateTime(b.event_starts_at)}
              </p>
              <p>
                {b.seats ? b.seats.map((s) => s.seat_id).join(", ") : `${b.seat_count} seats`} ·{" "}
                {formatPrice(b.total_price_cents)}
              </p>
              <p className="muted small">
                Booked {formatDateTime(b.created_at)} · #{b.id.slice(0, 8)}
              </p>
            </div>
            {b.ticket_ready ? (
              <button className="primary" onClick={() => download(b)} disabled={downloading === b.id}>
                {downloading === b.id ? "Downloading…" : "Download ticket (PDF)"}
              </button>
            ) : (
              <span className="badge badge-amber">Generating ticket…</span>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
