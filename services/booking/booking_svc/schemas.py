import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Hard cap against huge bodies; the real per-booking limit (MAX_SEATS_PER_BOOKING) is a
# setting, checked in the route so its error carries a domain code.
SeatList = list[str]


class HoldIn(BaseModel):
    event_id: int = Field(gt=0)
    seats: SeatList = Field(min_length=1, max_length=100)


class Payment(BaseModel):
    method: Literal["mock"]


class PurchaseIn(HoldIn):
    payment: Payment


class HoldOut(BaseModel):
    event_id: int
    seats: list[str]
    expires_at: datetime


class AvailabilityOut(BaseModel):
    event_id: int
    server_time: datetime
    sold: list[str]
    held: list[str]  # every unexpired hold, including the caller's
    my_holds: list[str]


class SeatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seat_id: str
    section_name: str
    price_cents: int


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: int
    event_title: str
    event_starts_at: datetime
    venue: str
    city: str
    status: str
    seat_count: int
    total_price_cents: int
    created_at: datetime
    seats: list[SeatOut]
    ticket_ready: bool = False


class EventStatsOut(BaseModel):
    event_id: int
    sold: int
    held: int
