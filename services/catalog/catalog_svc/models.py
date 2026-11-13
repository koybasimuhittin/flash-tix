from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Postgres advisory lock taken by init_schema; unique per service.
SCHEMA_LOCK_KEY = 1002


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_starts_at", "starts_at"),
        Index("ix_events_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    venue: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sales_open_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(BigInteger)  # auth user id; no FK across services
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Seats are derived from sections, never stored (see flashtix_common.seats).
    sections: Mapped[list["Section"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="Section.sort_order",
        lazy="selectin",
    )


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("event_id", "code"),
        CheckConstraint("rows BETWEEN 1 AND 50", name="ck_sections_rows"),
        CheckConstraint("seats_per_row BETWEEN 1 AND 60", name="ck_sections_seats_per_row"),
        CheckConstraint("price_cents >= 0", name="ck_sections_price"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    seats_per_row: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)

    event: Mapped[Event] = relationship(back_populates="sections")
