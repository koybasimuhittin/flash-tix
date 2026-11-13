import os
import uuid
from pathlib import Path


class LocalFiles:
    """Writes into the storage folder shared with booking-service (which serves the files)."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def write(self, name: str, data: bytes) -> None:
        """Write then rename: booking-service checks "file exists" and must never serve a
        half-written file. Writing the same name again simply replaces it."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
        partial.write_bytes(data)
        os.replace(partial, path)
