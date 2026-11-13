"""Seat ids are derived from section layouts, never stored.

A seat id is `{section_code}-{row}-{seat}`, 1-based, e.g. `A-3-12`. catalog-service uses
`capacity`; booking-service validates every seat a user holds or buys with `validate_seat_id`.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

SEAT_ID_PATTERN = re.compile(r"^([A-Z]{1,3})-(\d{1,3})-(\d{1,3})$")


class InvalidSeatId(ValueError):
    pass


class SectionShape(Protocol):
    code: str
    rows: int
    seats_per_row: int


@dataclass(frozen=True)
class SeatId:
    section: str
    row: int
    seat: int

    def __str__(self) -> str:
        return f"{self.section}-{self.row}-{self.seat}"


def parse_seat_id(value: str) -> SeatId:
    match = SEAT_ID_PATTERN.match(value)
    if match is None:
        raise InvalidSeatId(f"malformed seat id: {value!r}")
    seat = SeatId(match[1], int(match[2]), int(match[3]))
    # Only the canonical spelling is accepted: "A-01-1" would otherwise be a second id for
    # seat A-1-1 and slip past the (event_id, seat_id) uniqueness guarantees.
    if str(seat) != value:
        raise InvalidSeatId(f"non-canonical seat id: {value!r} (use {seat})")
    return seat


def validate_seat_id(value: str, sections: Mapping[str, SectionShape]) -> SeatId:
    """Parse `value` and check it exists in the event's layout (`sections` keyed by code)."""
    seat = parse_seat_id(value)
    section = sections.get(seat.section)
    if section is None:
        raise InvalidSeatId(f"unknown section in seat id: {value!r}")
    if not (1 <= seat.row <= section.rows and 1 <= seat.seat <= section.seats_per_row):
        raise InvalidSeatId(f"seat id out of range for section {section.code}: {value!r}")
    return seat


def capacity(sections: Iterable[SectionShape]) -> int:
    return sum(section.rows * section.seats_per_row for section in sections)
