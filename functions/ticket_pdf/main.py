"""ticket-pdf: renders the PDF ticket of a confirmed booking.

In the cloud a Pub/Sub push subscription calls this HTTP function; locally booking-service's
HttpPushPublisher POSTs the very same push envelope. A 2xx response acks the message and any
other status makes Pub/Sub retry (and finally dead-letter it), so only real failures (e.g.
storage unavailable) return 5xx. Malformed messages are acked with 204 and logged at ERROR, so a
poison message is not retried forever.
"""

import base64
import io
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import functions_framework
import reportlab
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


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": "ticket-pdf",
            "msg": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, default=str)


logger = logging.getLogger("ticket_pdf")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
logger.handlers[:] = [_handler]
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
logger.propagate = False


class InvalidMessage(ValueError):
    """The request is not a valid booking.confirmed v1 push message."""


def decode_envelope(envelope: object) -> dict:
    """Push envelope → validated v1 payload. Raises InvalidMessage for anything malformed."""
    try:
        payload = json.loads(base64.b64decode(envelope["message"]["data"], validate=True))
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidMessage(f"not a push envelope with JSON data: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidMessage("payload is not a JSON object")
    if payload.get("type") != "booking.confirmed" or payload.get("version") != 1:
        raise InvalidMessage(
            f"unsupported event {payload.get('type')!r} v{payload.get('version')!r}"
        )
    try:
        # The booking id becomes a file / object name, so only a real UUID is accepted.
        payload["booking_id"] = str(uuid.UUID(str(payload["booking_id"])))
        event = payload["event"]
        datetime.fromisoformat(event["starts_at"])
        for key in ("title", "venue", "city"):
            str(event[key])
        str(payload["buyer_name"])
        if not payload["seats"]:
            raise InvalidMessage("booking has no seats")
        for seat in payload["seats"]:
            str(seat["seat_id"]), str(seat["section_name"]), int(seat["price_cents"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidMessage(f"missing or invalid field: {exc}") from exc
    return payload


def format_price(cents: int) -> str:
    return f"TRY {cents / 100:,.2f}"


def qr_content(booking_id: str, seat_id: str) -> str:
    return f"FLASHTIX|{booking_id}|{seat_id}"


def render_pdf(payload: dict) -> bytes:
    """One A6 landscape page per seat, each with its own QR code."""
    event = payload["event"]
    starts = datetime.fromisoformat(event["starts_at"]).astimezone(DISPLAY_TZ)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.setTitle(f"FlashTix ticket {payload['booking_id']}")
    for seat in payload["seats"]:
        pdf.setFont("Vera-Bold", 13)
        pdf.drawString(8 * mm, PAGE_HEIGHT - 14 * mm, str(event["title"])[:42])
        pdf.setFont("Vera", 8.5)
        lines = [
            f"{starts:%d %b %Y, %H:%M} (Istanbul time)",
            f"{event['venue']}, {event['city']}",
            "",
            f"Section: {seat['section_name']}",
            f"Seat: {seat['seat_id']}",
            f"Price: {format_price(int(seat['price_cents']))}",
            f"Name: {payload['buyer_name']}",
            "",
            f"Booking {payload['booking_id']}",
        ]
        y = PAGE_HEIGHT - 23 * mm
        for line in lines:
            pdf.drawString(8 * mm, y, line)
            y -= 5 * mm
        qr = QrCodeWidget(qr_content(payload["booking_id"], seat["seat_id"]))
        x0, y0, x1, y1 = qr.getBounds()
        drawing = Drawing(
            QR_SIZE, QR_SIZE, transform=[QR_SIZE / (x1 - x0), 0, 0, QR_SIZE / (y1 - y0), 0, 0]
        )
        drawing.add(qr)
        renderPDF.draw(drawing, pdf, PAGE_WIDTH - QR_SIZE - 6 * mm, 8 * mm)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


_gcs_client = None


def save(name: str, data: bytes) -> None:
    """STORAGE_BACKEND=local writes to the shared folder, gcs to the bucket."""
    if os.environ.get("STORAGE_BACKEND", "local") == "gcs":
        global _gcs_client
        if _gcs_client is None:
            from google.cloud import storage  # imported lazily: local mode needs no credentials

            _gcs_client = storage.Client()
        blob = _gcs_client.bucket(os.environ["GCS_BUCKET"]).blob(name)
        blob.upload_from_string(data, content_type="application/pdf")
        return
    path = Path(os.environ.get("LOCAL_STORAGE_DIR", "/data/storage")) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename: booking-service checks "file exists" and must never serve half a PDF.
    partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    partial.write_bytes(data)
    os.replace(partial, path)


@functions_framework.http
def handle_push(request):
    if request.method == "GET":  # local container healthcheck; Pub/Sub always POSTs
        return ("ok", 200)
    envelope = request.get_json(silent=True)
    attributes = (
        (envelope or {}).get("message", {}).get("attributes", {})
        if isinstance(envelope, dict)
        else {}
    )
    request_id = attributes.get("request_id")
    try:
        payload = decode_envelope(envelope)
    except InvalidMessage as exc:
        logger.error(
            "invalid message acked", extra={"fields": {"error": str(exc), "request_id": request_id}}
        )
        return ("", 204)

    started = time.perf_counter()
    pdf = render_pdf(payload)
    render_ms = round((time.perf_counter() - started) * 1000, 1)
    save(f"tickets/{payload['booking_id']}.pdf", pdf)
    logger.info(
        "ticket rendered",
        extra={
            "fields": {
                "booking_id": payload["booking_id"],
                "seat_count": len(payload["seats"]),
                "render_ms": render_ms,
                "bytes": len(pdf),
                "request_id": request_id or payload.get("request_id"),
            }
        },
    )
    return ("", 204)
