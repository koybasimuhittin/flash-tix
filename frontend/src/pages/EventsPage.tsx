import { Clock, MapPin, Search } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, errorMessage } from "@/api";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatPrice } from "@/format";
import type { EventSummary } from "@/types";

const monthFmt = new Intl.DateTimeFormat("en-GB", { month: "short" });
const dayFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" });
const opensFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

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
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="font-poster text-5xl sm:text-6xl">Upcoming events</h1>
          <p className="mt-2 text-muted-foreground">Tickets go fast. Pick your seats the moment sales open.</p>
        </div>
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={search} role="search">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9 sm:w-56"
              placeholder="Artist or event"
              aria-label="Search events"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
            />
          </div>
          <Input
            className="sm:w-40"
            placeholder="City"
            aria-label="City"
            value={cityInput}
            onChange={(e) => setCityInput(e.target.value)}
          />
          <Button type="submit">Search</Button>
        </form>
      </div>

      {error && (
        <Alert variant="error" className="mt-8">
          {error}
        </Alert>
      )}
      {events === null && !error && <p className="mt-10 text-muted-foreground">Loading events…</p>}
      {events?.length === 0 && (
        <div className="mt-10 rounded-xl border border-dashed border-border p-10 text-center">
          <p className="font-semibold">No events match your search.</p>
          <p className="mt-1 text-sm text-muted-foreground">Try another city, or clear the search to see everything.</p>
        </div>
      )}

      {/* The lineup: one row per event, read like a poster's date list. */}
      {events && events.length > 0 && (
        <ul className="mt-10 divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
          {events.map((ev) => {
            const starts = new Date(ev.starts_at);
            const onSale = Date.parse(ev.sales_open_at) <= now;
            return (
              <li key={ev.id}>
                <Link
                  to={`/events/${ev.id}`}
                  className="event-card grid grid-cols-[4.5rem_1fr] items-center gap-x-5 gap-y-3 p-4 transition-colors hover:bg-muted/60 sm:grid-cols-[4.5rem_1fr_auto_auto] sm:p-5"
                >
                  <div className="flex flex-col items-center rounded-lg bg-ink py-2 text-white">
                    <span className="text-xs text-stub">{monthFmt.format(starts)}</span>
                    <span className="font-poster tabular text-3xl">{dayFmt.format(starts)}</span>
                  </div>
                  <div className="min-w-0">
                    <h2 className="font-poster truncate text-2xl sm:text-3xl">{ev.title}</h2>
                    <p className="mt-1 flex items-center gap-4 text-sm text-muted-foreground">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <MapPin className="size-3.5 shrink-0" />
                        <span className="truncate">{`${ev.venue}, ${ev.city}`}</span>
                      </span>
                      <span className="hidden shrink-0 items-center gap-1.5 sm:flex">
                        <Clock className="size-3.5" />
                        {timeFmt.format(starts)}
                      </span>
                    </p>
                  </div>
                  {/* One line on phones; two grid columns from sm up. */}
                  <div className="col-start-2 flex items-center gap-3 sm:contents">
                    <div>
                      {onSale ? (
                        <Badge variant="accent">On sale</Badge>
                      ) : (
                        <Badge variant="outline">Opens {opensFmt.format(new Date(ev.sales_open_at))}</Badge>
                      )}
                    </div>
                    <p className="text-sm sm:text-right">
                      <span className="text-muted-foreground">from </span>
                      <span className="tabular font-bold">{formatPrice(ev.min_price_cents)}</span>
                    </p>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
