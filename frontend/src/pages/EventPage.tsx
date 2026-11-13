import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, errorMessage } from "../api";
import { useAuth } from "../auth";
import SeatMap, { SeatLegend } from "../components/SeatMap";
import type { SeatState } from "../components/SeatMap";
import { formatDateTime, formatDuration, formatPrice, toMillis } from "../format";
import { useNow, usePolling } from "../hooks";
import type { Availability, Booking, EventDetail, Hold } from "../types";

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

function sectionOf(seat: string): string {
  return seat.split("-")[0];
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
      // The server read its clock roughly halfway through the round trip.
      setClockOffset(toMillis(a.server_time) - (sentAt + Date.now()) / 2);
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

  const stateOf = useCallback(
    (id: string): SeatState => {
      if (sets.sold.has(id)) return "sold";
      if (sets.mine.has(id)) return "mine";
      if (sets.held.has(id)) return "held";
      if (sets.selected.has(id)) return "selected";
      return "available";
    },
    [sets],
  );

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

  const priceOf = useMemo(() => {
    const prices = new Map(event?.sections.map((s) => [s.code, s.price_cents]));
    return (seats: string[]) => seats.reduce((sum, s) => sum + (prices.get(sectionOf(s)) ?? 0), 0);
  }, [event]);

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

  if (loadError) return <p className="alert alert-error">{loadError}</p>;
  if (!event) return <p className="muted">Loading…</p>;

  return (
    <div className="event-page">
      <section className="event-head">
        <h1>{event.title}</h1>
        <p className="muted">
          {event.venue} · {event.city} · {formatDateTime(event.starts_at)}
        </p>
        {event.description && <p>{event.description}</p>}
        <ul className="prices">
          {event.sections.map((s) => (
            <li key={s.code}>
              <strong>{s.code}</strong> {s.name}: {formatPrice(s.price_cents)}
            </li>
          ))}
        </ul>
      </section>

      {!salesOpen && (
        <div className="countdown">
          Sales open in <strong>{formatDuration((salesOpenAt - serverNow) / 1000)}</strong>
          <span className="muted"> ({formatDateTime(event.sales_open_at)})</span>
        </div>
      )}

      <div className="event-body">
        <div>
          <SeatLegend />
          {!availability && <p className="muted">Loading seat availability…</p>}
          <SeatMap
            sections={event.sections}
            stateOf={stateOf}
            onToggle={toggle}
            disabled={!salesOpen || !availability || activeHold !== null || busy}
          />
        </div>

        <aside className="card panel">
          {notice && <p className={`alert alert-${notice.kind}`}>{notice.text}</p>}
          {activeHold ? (
            <>
              <h2>Your hold</h2>
              <p>{activeHold.seats.join(", ")}</p>
              <p>
                Total <strong>{formatPrice(priceOf(activeHold.seats))}</strong>
              </p>
              {holdSecondsLeft !== null && (
                <p className={holdSecondsLeft < 60 ? "timer timer-low" : "timer"}>
                  Hold expires in {formatDuration(holdSecondsLeft)}
                </p>
              )}
              <button className="primary" onClick={pay} disabled={busy}>
                {busy ? "Processing…" : "Pay (mock)"}
              </button>
              <button onClick={release} disabled={busy}>
                Release seats
              </button>
            </>
          ) : (
            <>
              <h2>Selected seats</h2>
              {selected.length === 0 ? (
                <p className="muted">
                  {salesOpen ? `Click seats on the map (up to ${MAX_SEATS}).` : "Seats can be selected once sales open."}
                </p>
              ) : (
                <>
                  <p>{selected.join(", ")}</p>
                  <p>
                    Total <strong>{formatPrice(priceOf(selected))}</strong>
                  </p>
                </>
              )}
              <button
                className="primary"
                onClick={holdSelected}
                disabled={busy || selected.length === 0 || !salesOpen}
              >
                {busy ? "Holding…" : user ? `Hold ${selected.length || ""} seat${selected.length === 1 ? "" : "s"}` : "Log in to hold seats"}
              </button>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
