import logging
import time
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncEngine

from worker_svc.config import WorkerSettings
from worker_svc.files import LocalFiles
from worker_svc.reports import fetch_rows, report_day, report_name, to_csv
from worker_svc.tickets import BookingConfirmed, render_pdf, ticket_name

logger = logging.getLogger("worker_svc")


@dataclass
class WorkerState:
    """Created in the lifespan and kept at `app.state.worker`."""

    settings: WorkerSettings
    engine: AsyncEngine  # read-only reporting role
    files: LocalFiles


router = APIRouter(tags=["worker"])


def get_state(request: Request) -> WorkerState:
    return request.app.state.worker


@router.post("/tickets", status_code=status.HTTP_204_NO_CONTENT)
async def create_ticket(
    booking: BookingConfirmed, state: WorkerState = Depends(get_state)
) -> Response:
    """Called by booking-service after a purchase. A malformed event is rejected with 422 (the
    caller logs it and does not retry); a storage failure is a 5xx, so the caller retries.
    Sending the same booking twice just rewrites the same file."""
    started = time.perf_counter()
    pdf = await run_in_threadpool(render_pdf, booking)  # CPU work off the event loop
    await run_in_threadpool(state.files.write, ticket_name(booking.booking_id), pdf)
    logger.info(
        "ticket rendered",
        extra={
            "booking_id": str(booking.booking_id),
            "seat_count": len(booking.seats),
            "render_ms": round((time.perf_counter() - started) * 1000, 1),
            "bytes": len(pdf),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reports/daily")
async def daily_report(
    day: str | None = Query(None, alias="date", description="YYYY-MM-DD; default yesterday"),
    state: WorkerState = Depends(get_state),
) -> dict:
    try:
        report_date = report_day(day)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "INVALID_DATE"}
        ) from exc
    started = time.perf_counter()
    rows = await fetch_rows(state.engine, report_date)
    name = report_name(report_date)
    await run_in_threadpool(state.files.write, name, to_csv(rows))
    summary = {
        "date": report_date.isoformat(),
        "object": name,
        "events": len(rows),
        "bookings": sum(row[2] for row in rows),
        "seats": sum(row[3] for row in rows),
        "revenue_cents": sum(row[4] for row in rows),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    logger.info("report written", extra=summary)
    return summary
