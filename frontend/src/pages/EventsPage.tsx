import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, errorMessage } from "../api";
import { formatDateTime, formatPrice } from "../format";
import type { EventSummary } from "../types";

export default function EventsPage() {
  const [params, setParams] = useSearchParams();
  const city = params.get("city") ?? "";
  const q = params.get("q") ?? "";
  const [cityInput, setCityInput] = useState(city);
  const [qInput, setQInput] = useState(q);
  const [events, setEvents] = useState<EventSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const query = new URLSearchParams({ limit: "50" });
    if (city) query.set("city", city);
    if (q) query.set("q", q);
    let cancelled = false;
    setError(null);
    api
      .get<EventSummary[]>(`/api/events?${query}`)
      .then((list) => !cancelled && setEvents(list))
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [city, q]);

  function search(e: FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams();
    if (cityInput.trim()) next.set("city", cityInput.trim());
    if (qInput.trim()) next.set("q", qInput.trim());
    setParams(next);
  }

  const now = Date.now();
  return (
    <>
      <h1>Upcoming events</h1>
      <form className="filters" onSubmit={search}>
        <input placeholder="Search events" value={qInput} onChange={(e) => setQInput(e.target.value)} />
        <input placeholder="City" value={cityInput} onChange={(e) => setCityInput(e.target.value)} />
        <button className="primary">Search</button>
      </form>
      {error && <p className="alert alert-error">{error}</p>}
      {events === null && !error && <p className="muted">Loading…</p>}
      {events?.length === 0 && <p className="muted">No events found.</p>}
      <div className="grid">
        {events?.map((ev) => {
          const onSale = Date.parse(ev.sales_open_at) <= now;
          return (
            <Link key={ev.id} to={`/events/${ev.id}`} className="card event-card">
              <span className={`badge ${onSale ? "badge-green" : "badge-amber"}`}>
                {onSale ? "On sale" : `Sales open ${formatDateTime(ev.sales_open_at)}`}
              </span>
              <h2>{ev.title}</h2>
              <p className="muted">
                {ev.venue} · {ev.city}
              </p>
              <p>{formatDateTime(ev.starts_at)}</p>
              <p>
                From <strong>{formatPrice(ev.min_price_cents)}</strong> · {ev.capacity} seats
              </p>
            </Link>
          );
        })}
      </div>
    </>
  );
}
