from dataclasses import dataclass

import pytest

from flashtix_common.seats import InvalidSeatId, SeatId, capacity, parse_seat_id, validate_seat_id


@dataclass
class Section:
    code: str
    rows: int
    seats_per_row: int


SECTIONS = {"A": Section("A", 5, 20), "VIP": Section("VIP", 2, 10)}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("A-1-1", SeatId("A", 1, 1)),
        ("VIP-2-10", SeatId("VIP", 2, 10)),
        ("B-50-60", SeatId("B", 50, 60)),
    ],
)
def test_parse_valid_seat_ids(value, expected):
    assert parse_seat_id(value) == expected
    assert str(expected) == value


@pytest.mark.parametrize(
    "value",
    ["", "A-1", "a-1-1", "ABCD-1-1", "A-1-1-1", "A-1000-1", "A--1-1", " A-1-1", "A-1-1 ", "A-x-1"],
)
def test_parse_rejects_malformed_ids(value):
    with pytest.raises(InvalidSeatId):
        parse_seat_id(value)


@pytest.mark.parametrize("value", ["A-01-1", "A-1-007", "A-0-0"])
def test_parse_rejects_non_canonical_or_zero_padded_ids(value):
    if value == "A-0-0":  # canonical spelling, but out of range: caught by validate_seat_id
        assert parse_seat_id(value) == SeatId("A", 0, 0)
        with pytest.raises(InvalidSeatId):
            validate_seat_id(value, SECTIONS)
        return
    with pytest.raises(InvalidSeatId, match="non-canonical"):
        parse_seat_id(value)


def test_validate_against_layout():
    assert validate_seat_id("A-5-20", SECTIONS) == SeatId("A", 5, 20)
    assert validate_seat_id("VIP-1-1", SECTIONS) == SeatId("VIP", 1, 1)


@pytest.mark.parametrize("value", ["A-6-1", "A-1-21", "VIP-3-1", "B-1-1", "A-0-5"])
def test_validate_rejects_seats_outside_the_layout(value):
    with pytest.raises(InvalidSeatId):
        validate_seat_id(value, SECTIONS)


def test_capacity_is_sum_of_rows_times_seats():
    assert capacity(SECTIONS.values()) == 5 * 20 + 2 * 10
    assert capacity([]) == 0
