import { AlertCircle, CalendarDays, Clock, Info, Loader2, MapPin } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, errorMessage } from "@/api";
import { useAuth } from "@/auth";
import SeatMap, { SeatLegend } from "@/components/SeatMap";
import { SplitFlap } from "@/components/SplitFlap";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { clockOffset as computeClockOffset, formatDateTime, formatDuration, formatPrice, toMillis } from "@/format";
import { useNow, usePolling } from "@/hooks";
import { cn } from "@/lib/utils";
import { sectionOf, seatState, totalPrice } from "@/seats";
import type { Availability, Booking, EventDetail, Hold, Section } from "@/types";

/** Same as the backend's MAX_SEATS_PER_BOOKING. */
const MAX_SEATS = 6;
const AVAILABILITY_POLL_MS = 3000;

interface ActiveHold {
  seats: string[];
  expiresAt: number | null; // null when the hold was found in my_holds after a reload
}

type Notice = { kind: "error" | "info"; text: string } | null;

/** Keeps the hold's expiry across a page reload (the availability endpoint has no expiry). */
function holdKey(eventId: number): string {
  return `flashtix.hold.${eventId}`;
}

function loadHold(eventId: number): ActiveHold | null {
  try {
    const raw = sessionStorage.getItem(holdKey(eventId));
    return raw ? (JSON.parse(raw) as ActiveHold) : null;
  } catch {
    return null;
  }
}

function storeHold(eventId: number, hold: ActiveHold | null): void {
  try {
    if (hold) sessionStorage.setItem(holdKey(eventId), JSON.stringify(hold));
    else sessionStorage.removeItem(holdKey(eventId));
  } catch {
    // ignore
  }
}

function describeError(err: unknown): string {
  if (!(err instanceof ApiError)) return errorMessage(err);
  const seats = err.seats.join(", ");
  switch (err.code) {
    case "SEATS_UNAVAILABLE":
      return `Sorry, these seats were just taken: ${seats}. Pick other seats.`;
    case "INVALID_SEATS":
      return `These seats do not exist for this event: ${seats}.`;
    case "SALES_NOT_OPEN":
      return "Sales for this event are not open yet.";
    case "HOLD_EXPIRED":
      return `Your hold expired for: ${seats}. Please select seats again.`;
    case "SEATS_ALREADY_SOLD":
      return "Some of these seats were sold to someone else. Please select seats again.";
    default:
      return errorMessage(err);
  }
}

export default function EventPage() {
  const eventId = Number(useParams().id);
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const now = useNow(250);

  const [event, setEvent] = useState<EventDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [clockOffset, setClockOffset] = useState(0); // server time − local time, ms
  const [selected, setSelected] = useState<string[]>([]);
  const [hold, setHoldState] = useState<ActiveHold | null>(() => loadHold(eventId));
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);

  const setHold = useCallback(
    (next: ActiveHold | null) => {
      storeHold(eventId, next);
      setHoldState(next);
    },
    [eventId],
  );

  useEffect(() => {
    let cancelled = false;
    api
      .get<EventDetail>(`/api/events/${eventId}`)
      .then((ev) => !cancelled && setEvent(ev))
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError && err.status === 404 ? "Event not found." : errorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  const refresh = useCallback(async () => {
    try {
      const sentAt = Date.now();
      const a = await api.get<Availability>(`/api/booking/events/${eventId}/availability`);
      setClockOffset(computeClockOffset(a.server_time, sentAt, Date.now()));
      setAvailability(a);
      // Drop selected seats that someone else has just held or bought.
      const taken = new Set([...a.sold, ...a.held]);
      setSelected((sel) => (sel.some((s) => taken.has(s)) ? sel.filter((s) => !taken.has(s)) : sel));
    } catch {
      // Keep showing the last known state; the next poll retries.
    }
  }, [eventId]);

  usePolling(refresh, AVAILABILITY_POLL_MS, Number.isFinite(eventId));

  const serverNow = now + clockOffset;
  const salesOpenAt = event ? Date.parse(event.sales_open_at) : Infinity;
  const salesOpen = serverNow >= salesOpenAt;

  // After a reload without sessionStorage, my_holds still tells us which seats we hold.
  const myHolds = useMemo(() => availability?.my_holds ?? [], [availability]);
  const activeHold: ActiveHold | null =
    hold ?? (user && myHolds.length > 0 ? { seats: myHolds, expiresAt: null } : null);
  const holdSecondsLeft = activeHold?.expiresAt != null ? (activeHold.expiresAt - serverNow) / 1000 : null;

  useEffect(() => {
    if (hold?.expiresAt != null && holdSecondsLeft !== null && holdSecondsLeft <= 0) {
      setHold(null);
      setNotice({ kind: "error", text: "Your hold expired. The seats were released." });
    }
  }, [hold, holdSecondsLeft, setHold]);

  const sets = useMemo(
    () => ({
      sold: new Set(availability?.sold ?? []),
      held: new Set(availability?.held ?? []),
      mine: new Set([...myHolds, ...(hold?.seats ?? [])]),
      selected: new Set(selected),
    }),
    [availability, myHolds, hold, selected],
  );

  const stateOf = useCallback((id: string) => seatState(id, sets), [sets]);

  const toggle = useCallback((id: string) => {
    setNotice(null);
    setSelected((sel) => {
      if (sel.includes(id)) return sel.filter((s) => s !== id);
      if (sel.length >= MAX_SEATS) {
        setNotice({ kind: "error", text: `You can select at most ${MAX_SEATS} seats.` });
        return sel;
      }
      return [...sel, id];
    });
  }, []);

  const priceOf = (seats: string[]) => totalPrice(seats, event?.sections ?? []);

  async function holdSelected() {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const res = await api.post<Hold>("/api/booking/holds", { event_id: eventId, seats: selected });
      setHold({ seats: res.seats, expiresAt: toMillis(res.expires_at) });
      setSelected([]);
    } catch (err) {
      setNotice({ kind: "error", text: describeError(err) });
      if (err instanceof ApiError && err.code === "SEATS_UNAVAILABLE") {
        const lost = new Set(err.seats);
        setSelected((sel) => sel.filter((s) => !lost.has(s)));
      }
    } finally {
      setBusy(false);
      void refresh();
    }
  }

  async function pay() {
    if (!activeHold) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.post<Booking>("/api/booking/purchase", {
        event_id: eventId,
        seats: activeHold.seats,
        payment: { method: "mock" },
      });
      setHold(null);
      navigate("/bookings");
    } catch (err) {
      setNotice({ kind: "error", text: describeError(err) });
      if (err instanceof ApiError && (err.code === "HOLD_EXPIRED" || err.code === "SEATS_ALREADY_SOLD")) {
        setHold(null);
      }
      void refresh();
    } finally {
      setBusy(false);
    }
  }

  async function release() {
    if (!activeHold) return;
    setBusy(true);
    try {
      await api.post("/api/booking/holds/release", { event_id: eventId, seats: activeHold.seats });
      setHold(null);
      setNotice({ kind: "info", text: "Seats released." });
    } catch (err) {
      setNotice({ kind: "error", text: describeError(err) });
    } finally {
      setBusy(false);
      void refresh();
    }
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-md px-4 py-16 text-center">
        <h1 className="font-poster text-3xl">{loadError}</h1>
        <Button variant="outline" className="mt-6" onClick={() => navigate("/")}>
          Back to events
        </Button>
      </div>
    );
  }
  if (!event) {
    return (
      <div className="flex justify-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading" />
      </div>
    );
  }

  const soldCount = availability?.sold.length ?? 0;
  const soldPct = event.capacity ? Math.min(100, (soldCount / event.capacity) * 100) : 0;
  const stubSeats = activeHold?.seats ?? selected;

  return (
    <>
      {/* Hero: the ink band. Before the sale it carries the split-flap countdown. */}
      <section className="bg-ink text-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 md:grid-cols-[1fr_auto] md:items-end md:py-14">
          <div className="min-w-0">
            <h1 className="font-poster text-5xl text-balance sm:text-6xl lg:text-7xl">{event.title}</h1>
            <div className="mt-5 flex flex-col gap-1.5 text-sm text-white/75 sm:flex-row sm:gap-6">
              <span className="inline-flex items-center gap-2">
                <CalendarDays className="size-4 text-stub" /> {formatDateTime(event.starts_at)}
              </span>
              <span className="inline-flex items-center gap-2">
                <MapPin className="size-4 text-stub" /> {event.venue}, {event.city}
              </span>
            </div>
            {event.description && <p className="mt-4 max-w-prose text-white/70">{event.description}</p>}
          </div>

          {salesOpen ? (
            <div className="md:w-72">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-stub">
                <span className="relative flex size-2.5">
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-stub opacity-75 motion-reduce:hidden" />
                  <span className="relative inline-flex size-2.5 rounded-full bg-stub" />
                </span>
                On sale now
              </p>
              <p className="tabular mt-2 text-3xl font-bold">
                {soldCount} <span className="text-lg font-medium text-white/60">of {event.capacity} sold</span>
              </p>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/15">
                <div className="h-full rounded-full bg-sold transition-[width] duration-700" style={{ width: `${soldPct}%` }} />
              </div>
            </div>
          ) : (
            <div>
              <p className="mb-3 text-sm text-white/75">Sales open in</p>
              <SplitFlap seconds={(salesOpenAt - serverNow) / 1000} />
              <p className="mt-3 text-xs text-white/55">{formatDateTime(event.sales_open_at)}</p>
            </div>
          )}
        </div>
      </section>

      <div className="mx-auto grid max-w-6xl grid-cols-[minmax(0,1fr)] gap-8 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="rounded-xl border border-border bg-card p-4 sm:p-6" aria-label="Seat map">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <SeatLegend />
            {!availability && (
              <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Loading seats
              </span>
            )}
          </div>
          <SeatMap
            sections={event.sections}
            stateOf={stateOf}
            onToggle={toggle}
            disabled={!salesOpen || !availability || activeHold !== null || busy}
          />
        </section>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <TicketStub
            title={activeHold ? "Your seats are held" : "Your seats"}
            seats={stubSeats}
            sections={event.sections}
            total={formatPrice(priceOf(stubSeats))}
          >
            {notice && (
              <Alert variant={notice.kind}>
                {notice.kind === "error" ? <AlertCircle /> : <Info />}
                <span>{notice.text}</span>
              </Alert>
            )}
            {activeHold ? (
              <>
                {holdSecondsLeft !== null && (
                  <p
                    className={cn(
                      "tabular inline-flex items-center gap-2 text-sm font-semibold",
                      holdSecondsLeft < 60 && "text-sold",
                    )}
                  >
                    <Clock className="size-4" /> Hold expires in {formatDuration(holdSecondsLeft)}
                  </p>
                )}
                <Button variant="accent" size="lg" onClick={pay} disabled={busy}>
                  {busy && <Loader2 className="animate-spin" />}
                  {busy ? "Processing…" : "Pay (mock)"}
                </Button>
                <Button variant="ghost" onClick={release} disabled={busy}>
                  Release seats
                </Button>
              </>
            ) : (
              <Button size="lg" onClick={holdSelected} disabled={busy || selected.length === 0 || !salesOpen}>
                {busy && <Loader2 className="animate-spin" />}
                {busy
                  ? "Holding…"
                  : user
                    ? `Hold ${selected.length || ""} seat${selected.length === 1 ? "" : "s"}`
                    : "Log in to hold seats"}
              </Button>
            )}
          </TicketStub>
          {!activeHold && selected.length === 0 && (
            <p className="mt-3 px-1 text-sm text-muted-foreground">
              {salesOpen
                ? `Pick up to ${MAX_SEATS} seats on the map. A hold keeps them for 10 minutes while you pay.`
                : "Seats can be picked once sales open."}
            </p>
          )}
        </aside>
      </div>
    </>
  );
}

/** The checkout panel, drawn as a ticket: seat lines, a perforation, then the total and actions. */
function TicketStub({
  title,
  seats,
  sections,
  total,
  children,
}: {
  title: string;
  seats: string[];
  sections: Section[];
  total: string;
  children: ReactNode;
}) {
  const byCode = new Map(sections.map((s) => [s.code, s]));
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="h-1.5 bg-stub" />
      <div className="p-5">
        <h2 className="font-poster text-2xl">{title}</h2>
        {seats.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">No seats picked yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {seats.map((seat) => {
              const section = byCode.get(sectionOf(seat));
              const [, row, number] = seat.split("-");
              return (
                <li key={seat} className="flex items-baseline justify-between gap-3">
                  <span>
                    <span className="font-semibold">{section?.name ?? sectionOf(seat)}</span>
                    <span className="text-muted-foreground">
                      , row {row}, seat {number}
                    </span>
                  </span>
                  <span className="tabular">{section ? formatPrice(section.price_cents) : ""}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="perforation-x mx-0" />
      <div className="flex flex-col gap-3 p-5">
        <div className="flex items-baseline justify-between">
          <span className="text-sm text-muted-foreground">Total</span>
          <span className="tabular text-2xl font-bold">{total}</span>
        </div>
        {children}
      </div>
    </div>
  );
}
