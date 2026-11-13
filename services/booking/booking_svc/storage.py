"""Where ticket PDFs and report CSVs (written by the worker service) are read from.

STORAGE_BACKEND=local reads the folder shared with the worker.
"""

import asyncio
import datetime
import uuid
from pathlib import Path
from typing import Protocol


class TicketStorage(Protocol):
    async def exists(self, name: str) -> bool: ...

    async def read(self, name: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    async def exists(self, name: str) -> bool:
        return (self.root / name).is_file()

    async def read(self, name: str) -> bytes:
        # File I/O off the event loop (never block the event loop).
        return await asyncio.to_thread((self.root / name).read_bytes)


def make_storage(backend: str, local_dir: str) -> TicketStorage:
    if backend == "local":
        return LocalStorage(local_dir)
    raise NotImplementedError(f"STORAGE_BACKEND={backend!r} is not supported")


def report_name(day: datetime.date) -> str:
    """Built from the typed date, never from the raw path text (no traversal via the URL)."""
    return f"reports/{day.isoformat()}.csv"


def ticket_name(booking_id: uuid.UUID) -> str:
    """Object names are built from the typed booking id only, never from request text."""
    return f"tickets/{booking_id}.pdf"
