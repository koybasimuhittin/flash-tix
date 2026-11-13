import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SEAT_UNIQUE_CONSTRAINT = "uq_booking_seats_event_seat"


# Postgres advisory lock taken by init_schema; unique per service.
SCHEMA_LOCK_KEY = 1003


class Base(DeclarativeBase):
    pass


class Booking(Base):
    """A confirmed purchase. Event and buyer fields are snapshots: the ticket PDF and the
    daily report must not depend on other services' current data."""

    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger)
    user_email: Mapped[str] = mapped_column(Text)
    user_name: Mapped[str] = mapped_column(Text)
    event_id: Mapped[int] = mapped_column(BigInteger)
    event_title: Mapped[str] = mapped_column(Text)
    event_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="confirmed")
    seat_count: Mapped[int] = mapped_column(Integer)
    total_price_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )

    seats: Mapped[list["BookingSeat"]] = relationship(
        back_populates="booking", lazy="selectin", order_by="BookingSeat.id"
    )


class BookingSeat(Base):
    __tablename__ = "booking_seats"
    # The final oversell guarantee: whatever Redis says, a seat is sold at most once.
    __table_args__ = (UniqueConstraint("event_id", "seat_id", name=SEAT_UNIQUE_CONSTRAINT),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    event_id: Mapped[int] = mapped_column(BigInteger)
    seat_id: Mapped[str] = mapped_column(Text)
    section_name: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)

    booking: Mapped[Booking] = relationship(back_populates="seats")


Index("ix_bookings_user_created", Booking.user_id, Booking.created_at.desc())
Index("ix_bookings_created", Booking.created_at)  # daily report scans one day
