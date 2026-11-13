"""PDF tickets: one A6 landscape page per seat, each with its own QR code."""

import io
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import reportlab
from pydantic import BaseModel, Field
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A6, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

DISPLAY_TZ = ZoneInfo("Europe/Istanbul")
PAGE_WIDTH, PAGE_HEIGHT = landscape(A6)
QR_SIZE = 38 * mm

# Bitstream Vera ships with reportlab and, unlike the built-in Helvetica, covers Turkish letters
# (ş, ğ, İ, ı), which buyer names often contain.
_FONT_DIR = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Vera", str(_FONT_DIR / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Vera-Bold", str(_FONT_DIR / "VeraBd.ttf")))


class TicketEvent(BaseModel):
    id: int
    title: str
    venue: str
    city: str
    starts_at: datetime


class TicketSeat(BaseModel):
    seat_id: str
    section_name: str
    price_cents: int


class BookingConfirmed(BaseModel):
    """The `booking.confirmed` event (v1) that booking-service sends after a purchase."""

    type: Literal["booking.confirmed"]
    version: Literal[1]
    booking_id: uuid.UUID  # becomes the file name, so only a real UUID is accepted
    buyer_name: str
    event: TicketEvent
    seats: list[TicketSeat] = Field(min_length=1)
    request_id: str | None = None


def ticket_name(booking_id: uuid.UUID) -> str:
    return f"tickets/{booking_id}.pdf"


def format_price(cents: int) -> str:
    return f"TRY {cents / 100:,.2f}"


def qr_content(booking_id: uuid.UUID, seat_id: str) -> str:
    return f"FLASHTIX|{booking_id}|{seat_id}"


def render_pdf(booking: BookingConfirmed) -> bytes:
    event = booking.event
    starts = event.starts_at.astimezone(DISPLAY_TZ)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.setTitle(f"FlashTix ticket {booking.booking_id}")
    for seat in booking.seats:
        pdf.setFont("Vera-Bold", 13)
        pdf.drawString(8 * mm, PAGE_HEIGHT - 14 * mm, event.title[:42])
        pdf.setFont("Vera", 8.5)
        lines = [
            f"{starts:%d %b %Y, %H:%M} (Istanbul time)",
            f"{event.venue}, {event.city}",
            "",
            f"Section: {seat.section_name}",
            f"Seat: {seat.seat_id}",
            f"Price: {format_price(seat.price_cents)}",
            f"Name: {booking.buyer_name}",
            "",
            f"Booking {booking.booking_id}",
        ]
        y = PAGE_HEIGHT - 23 * mm
        for line in lines:
            pdf.drawString(8 * mm, y, line)
            y -= 5 * mm
        qr = QrCodeWidget(qr_content(booking.booking_id, seat.seat_id))
        x0, y0, x1, y1 = qr.getBounds()
        drawing = Drawing(
            QR_SIZE, QR_SIZE, transform=[QR_SIZE / (x1 - x0), 0, 0, QR_SIZE / (y1 - y0), 0, 0]
        )
        drawing.add(qr)
        renderPDF.draw(drawing, pdf, PAGE_WIDTH - QR_SIZE - 6 * mm, 8 * mm)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
