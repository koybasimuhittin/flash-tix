import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from booking_svc.catalog_client import CatalogClient, CatalogUnavailable, EventInfo, EventNotFound
from booking_svc.config import BookingSettings
from booking_svc.events import EventPublisher, build_payload, publish_with_retries
from booking_svc.holds import HoldStore
from booking_svc.models import Booking, BookingSeat
from booking_svc.schemas import AvailabilityOut, BookingOut, HoldIn, HoldOut, PurchaseIn
from booking_svc.seats import SeatRequestError, check_seat_request, check_seats_exist, price_seats
from booking_svc.storage import TicketStorage, ticket_name
from flashtix_common.logging import request_id_var
from flashtix_common.security import Principal, get_optional_principal, get_principal


@dataclass
class BookingState:
    """Everything the routes need, created in the lifespan and kept at `app.state.booking`
    (namespaced so the monolith can hold every service's state side by side).

    Routes open a DB session only around their queries, never across Redis, catalog or
    payment waits, so a pooled connection is never held idle."""

    settings: BookingSettings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    holds: HoldStore
    catalog: CatalogClient
    publisher: EventPublisher
    storage: TicketStorage


router = APIRouter(prefix="/api/booking", tags=["booking"])


def get_state(request: Request) -> BookingState:
    return request.app.state.booking


def now_ms() -> int:
    return int(time.time() * 1000)


def _error(status_code: int, code: str, seats: list[str] | None = None) -> HTTPException:
    detail: dict = {"code": code}
    if seats is not None:
        detail["seats"] = seats
    return HTTPException(status_code, detail=detail)


async def _sold_seats(
    state: BookingState, event_id: int, among: list[str] | None = None
) -> list[str]:
    async with state.sessionmaker() as session:
        stmt = select(BookingSeat.seat_id).where(BookingSeat.event_id == event_id)
        if among is not None:
            stmt = stmt.where(BookingSeat.seat_id.in_(among))
        return list((await session.scalars(stmt)).all())


async def _ensure_sold_loaded(state: BookingState, event_id: int) -> None:
    async def load(event: int) -> list[str]:
        return await _sold_seats(state, event)

    await state.holds.ensure_sold_loaded(event_id, load)


async def _validated_event(state: BookingState, body: HoldIn) -> EventInfo:
    """Checks shared by hold and purchase: seat count/duplicates, event exists, seats exist
    in its layout, and sales are open."""
    try:
        check_seat_request(body.seats, state.settings.max_seats_per_booking)
        event = await state.catalog.get_event(body.event_id)
        check_seats_exist(event, body.seats)
    except SeatRequestError as exc:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, exc.seats) from exc
    except EventNotFound as exc:
        raise _error(status.HTTP_404_NOT_FOUND, "EVENT_NOT_FOUND") from exc
    except CatalogUnavailable as exc:
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, "CATALOG_UNAVAILABLE") from exc
    if datetime.now(UTC) < event.sales_open_at:
        raise _error(status.HTTP_403_FORBIDDEN, "SALES_NOT_OPEN")
    return event


async def _booking_out(state: BookingState, booking: Booking) -> BookingOut:
    out = BookingOut.model_validate(booking)
    out.ticket_ready = await state.storage.exists(ticket_name(booking.id))
    return out


# Route order matters: every static path (/events/…, /holds…, /purchase, /me, and later
# /stats and /reports/{date}) is registered before /{booking_id}, which would otherwise
# capture them and answer 422.


@router.get("/events/{event_id}/availability", response_model=AvailabilityOut)
async def availability(
    event_id: int,
    principal: Principal | None = Depends(get_optional_principal),
    state: BookingState = Depends(get_state),
) -> AvailabilityOut:
    """Polled every ~3 s by every viewer of the seat map, so it reads Redis only."""
    await _ensure_sold_loaded(state, event_id)
    sold, held, mine = await state.holds.availability(
        event_id, principal.user_id if principal else None, now_ms()
    )
    return AvailabilityOut(
        event_id=event_id, server_time=datetime.now(UTC), sold=sold, held=held, my_holds=mine
    )


@router.post("/holds", response_model=HoldOut)
async def hold_seats(
    body: HoldIn,
    principal: Principal = Depends(get_principal),
    state: BookingState = Depends(get_state),
) -> HoldOut:
    event = await _validated_event(state, body)
    await _ensure_sold_loaded(state, event.id)
    now = now_ms()
    expires_at_ms = now + state.settings.hold_ttl_seconds * 1000
    conflicts = await state.holds.hold(event.id, principal.user_id, body.seats, now, expires_at_ms)
    if conflicts:
        raise _error(status.HTTP_409_CONFLICT, "SEATS_UNAVAILABLE", conflicts)
    return HoldOut(
        event_id=event.id,
        seats=body.seats,
        expires_at=datetime.fromtimestamp(expires_at_ms / 1000, UTC),
    )


@router.post("/holds/release", status_code=status.HTTP_204_NO_CONTENT)
async def release_seats(
    body: HoldIn,
    principal: Principal = Depends(get_principal),
    state: BookingState = Depends(get_state),
) -> Response:
    await state.holds.release(body.event_id, principal.user_id, body.seats)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/purchase", status_code=status.HTTP_201_CREATED, response_model=BookingOut)
async def purchase(
    body: PurchaseIn,
    background: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    state: BookingState = Depends(get_state),
) -> BookingOut:
    settings = state.settings
    event = await _validated_event(state, body)

    # 1. The buyer must still hold every seat; valid holds are stretched to a grace window
    #    so they can't lapse during payment and the DB transaction.
    now = now_ms()
    grace_until_ms = now + settings.purchase_grace_seconds * 1000
    missing = await state.holds.verify(event.id, principal.user_id, body.seats, now, grace_until_ms)
    if missing:
        raise _error(status.HTTP_409_CONFLICT, "HOLD_EXPIRED", missing)

    # 2. Mock payment provider.
    if settings.mock_payment_latency_ms:
        await asyncio.sleep(settings.mock_payment_latency_ms / 1000)

    # 3. One transaction for the booking and its seats. UNIQUE(event_id, seat_id) rejects a
    #    seat that was sold in the meantime (e.g. a hold expired and someone else bought it).
    priced = price_seats(event, body.seats)
    booking = Booking(
        user_id=principal.user_id,
        user_email=principal.email,
        user_name=principal.name,
        event_id=event.id,
        event_title=event.title,
        event_starts_at=event.starts_at,
        venue=event.venue,
        city=event.city,
        seat_count=len(priced),
        total_price_cents=sum(seat.price_cents for seat in priced),
        seats=[
            BookingSeat(
                event_id=event.id,
                seat_id=seat.seat_id,
                section_name=seat.section_name,
                price_cents=seat.price_cents,
            )
            for seat in priced
        ],
    )
    try:
        async with state.sessionmaker() as session, session.begin():
            session.add(booking)
    except IntegrityError as exc:
        # Redis said the seats were held, the database says sold: bring Redis back in line.
        taken = await _sold_seats(state, event.id, among=body.seats)
        if taken:
            await state.holds.mark_sold(event.id, taken)
        raise _error(status.HTTP_409_CONFLICT, "SEATS_ALREADY_SOLD", taken) from exc

    # 4. Only after commit: seats leave the hold structures and join the sold cache.
    await state.holds.mark_sold(event.id, body.seats)

    # 5. Ticket generation is asynchronous; publishing must never fail the purchase.
    background.add_task(
        publish_with_retries, state.publisher, build_payload(booking, request_id_var.get())
    )
    return BookingOut.model_validate(booking)


@router.get("/me", response_model=list[BookingOut])
async def my_bookings(
    principal: Principal = Depends(get_principal),
    state: BookingState = Depends(get_state),
) -> list[BookingOut]:
    async with state.sessionmaker() as session:
        bookings = (
            await session.scalars(
                select(Booking)
                .where(Booking.user_id == principal.user_id)
                .order_by(Booking.created_at.desc())
                .limit(50)
            )
        ).all()
    return [await _booking_out(state, booking) for booking in bookings]


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(
    booking_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    state: BookingState = Depends(get_state),
) -> BookingOut:
    async with state.sessionmaker() as session:
        booking = await session.get(Booking, booking_id)
    if booking is None or booking.user_id != principal.user_id:
        # 404 rather than 403 for other users' bookings: don't confirm that an id exists.
        raise _error(status.HTTP_404_NOT_FOUND, "BOOKING_NOT_FOUND")
    return await _booking_out(state, booking)
