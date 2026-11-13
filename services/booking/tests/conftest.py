import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Async tests use anyio's pytest plugin (`@pytest.mark.anyio`) on asyncio only."""
    return "asyncio"
