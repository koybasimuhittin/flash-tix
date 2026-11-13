"""Request-level seat rules and pricing. Seat id syntax and layout ranges come from the shared
`flashtix_common.seats`, so catalog and booking can never disagree on what a seat is."""

from collections import Counter
from dataclasses import dataclass

from booking_svc.catalog_client import EventInfo
from flashtix_common.seats import InvalidSeatId, validate_seat_id


class SeatRequestError(Exception):
    def __init__(self, code: str, seats: list[str] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.seats = seats or []


@dataclass(frozen=True)
class PricedSeat:
    seat_id: str
    section_name: str
    price_cents: int


def check_seat_request(seats: list[str], max_seats: int) -> None:
    """Shape checks that need no event data: count and duplicates."""
    if len(seats) > max_seats:
        raise SeatRequestError("TOO_MANY_SEATS")
    duplicates = sorted(seat for seat, count in Counter(seats).items() if count > 1)
    if duplicates:
        raise SeatRequestError("DUPLICATE_SEATS", duplicates)


def check_seats_exist(event: EventInfo, seats: list[str]) -> None:
    invalid = []
    for seat in seats:
        try:
            validate_seat_id(seat, event.sections)
        except InvalidSeatId:
            invalid.append(seat)
    if invalid:
        raise SeatRequestError("INVALID_SEATS", invalid)


def price_seats(event: EventInfo, seats: list[str]) -> list[PricedSeat]:
    """Prices come from the catalog's section of each seat (seats already validated)."""
    priced = []
    for seat in seats:
        section = event.sections[validate_seat_id(seat, event.sections).section]
        priced.append(PricedSeat(seat, section.name, section.price_cents))
    return priced
