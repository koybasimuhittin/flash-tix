"""The Lua scripts against a real Redis (127.0.0.1:6380, database 15). Skipped without it."""

import random
import socket

import pytest

from booking_svc.holds import (
    SOLD_MARKER_TTL_SECONDS,
    HoldStore,
    hold_hash_key,
    hold_zset_key,
    sold_key,
    sold_loaded_key,
)
from flashtix_common.redis import make_redis

# Database 15, not the dev stack's 0, so tests never mix with local data.
TEST_REDIS_URL = "redis://127.0.0.1:6380/15"


def reachable(address: tuple[str, int]) -> bool:
    try:
        with socket.create_connection(address, timeout=1):
            return True
    except OSError:
        return False


def new_event_id() -> int:
    return random.randint(1_000_000_000, 2_000_000_000)


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not reachable(("127.0.0.1", 6380)), reason="local redis on 127.0.0.1:6380 not running"
    ),
]

NOW = 1_000_000
LATER = NOW + 600_000


@pytest.fixture
async def store():
    redis = make_redis(TEST_REDIS_URL)
    yield HoldStore(redis)
    await redis.aclose()


@pytest.fixture
def event() -> int:
    return new_event_id()


async def test_hold_grants_all_requested_seats(store, event):
    assert await store.hold(event, 1, ["A-1-1", "A-1-2"], NOW, LATER) == []
    sold, held, mine = await store.availability(event, 1, NOW)
    assert (sold, sorted(held), sorted(mine)) == ([], ["A-1-1", "A-1-2"], ["A-1-1", "A-1-2"])


async def test_hold_is_all_or_nothing(store, event):
    assert await store.hold(event, 2, ["A-1-2"], NOW, LATER) == []
    # User 1 wants A-1-1 and A-1-2; A-1-2 is taken, so user 1 gets neither.
    assert await store.hold(event, 1, ["A-1-1", "A-1-2"], NOW, LATER) == ["A-1-2"]
    _, held, mine = await store.availability(event, 1, NOW)
    assert (held, mine) == (["A-1-2"], [])


async def test_sold_seats_conflict(store, event):
    await store.mark_sold(event, ["B-1-1"])
    assert await store.hold(event, 1, ["B-1-1", "B-1-2"], NOW, LATER) == ["B-1-1"]


async def test_rehold_own_seat_refreshes_expiry(store, event):
    await store.hold(event, 1, ["A-1-1"], NOW, LATER)
    assert await store.hold(event, 1, ["A-1-1"], NOW + 10, LATER + 10) == []
    assert await store.redis.zscore(hold_zset_key(event), "A-1-1") == LATER + 10


async def test_expired_holds_free_the_seat_and_are_cleaned_up(store, event):
    await store.hold(event, 2, ["A-1-1"], NOW, NOW + 1_000)
    # Not visible as held once expired, even before any cleanup ran.
    assert (await store.availability(event, 1, NOW + 1_000))[1] == []
    assert await store.hold(event, 1, ["A-1-1"], NOW + 2_000, LATER) == []
    assert await store.redis.hget(hold_hash_key(event), "A-1-1") == "1"


async def test_release_only_touches_your_own_holds(store, event):
    await store.hold(event, 1, ["A-1-1"], NOW, LATER)
    await store.hold(event, 2, ["A-1-2"], NOW, LATER)
    assert await store.release(event, 1, ["A-1-1", "A-1-2"]) == 1
    _, held, _ = await store.availability(event, 1, NOW)
    assert held == ["A-1-2"]


async def test_verify_reports_missing_seats(store, event):
    await store.hold(event, 1, ["A-1-1"], NOW, LATER)
    await store.hold(event, 2, ["A-1-2"], NOW, LATER)
    await store.hold(event, 1, ["A-1-3"], NOW, NOW + 500)  # expires before the check
    missing = await store.verify(event, 1, ["A-1-1", "A-1-2", "A-1-3", "A-1-4"], NOW + 500, 0)
    assert missing == ["A-1-2", "A-1-3", "A-1-4"]


async def test_verify_extends_short_holds_to_the_grace_window(store, event):
    await store.hold(event, 1, ["A-1-1", "A-1-2"], NOW, NOW + 5_000)
    await store.redis.zadd(hold_zset_key(event), {"A-1-2": NOW + 90_000})
    assert await store.verify(event, 1, ["A-1-1", "A-1-2"], NOW, NOW + 30_000) == []
    zset = hold_zset_key(event)
    assert await store.redis.zscore(zset, "A-1-1") == NOW + 30_000  # extended
    assert await store.redis.zscore(zset, "A-1-2") == NOW + 90_000  # already longer: kept


async def test_verify_extends_nothing_when_a_seat_is_missing(store, event):
    await store.hold(event, 1, ["A-1-1"], NOW, NOW + 5_000)
    assert await store.verify(event, 1, ["A-1-1", "A-1-9"], NOW, NOW + 30_000) == ["A-1-9"]
    assert await store.redis.zscore(hold_zset_key(event), "A-1-1") == NOW + 5_000


async def test_mark_sold_moves_seats_from_held_to_sold(store, event):
    await store.hold(event, 1, ["A-1-1", "A-1-2"], NOW, LATER)
    await store.mark_sold(event, ["A-1-1", "A-1-2"])
    sold, held, mine = await store.availability(event, 1, NOW)
    assert (sold, held, mine) == (["A-1-1", "A-1-2"], [], [])
    assert await store.redis.hlen(hold_hash_key(event)) == 0


async def test_sold_cache_is_rebuilt_from_the_database(store, event):
    calls = []

    async def load(event_id: int) -> list[str]:
        calls.append(event_id)
        return ["C-1-1", "C-1-2"]

    await store.ensure_sold_loaded(event, load)
    await store.ensure_sold_loaded(event, load)  # marker present: no second load
    assert calls == [event]
    assert sorted(await store.redis.smembers(sold_key(event))) == ["C-1-1", "C-1-2"]

    await store.redis.delete(sold_key(event), sold_loaded_key(event))  # Redis lost its data
    await store.ensure_sold_loaded(event, load)
    assert calls == [event, event]
    assert await store.hold(event, 1, ["C-1-1"], NOW, LATER) == ["C-1-1"]


async def test_unloaded_lists_only_events_without_a_sold_cache(store, event):
    other = event + 1

    async def load(event_id: int) -> list[str]:
        return []

    await store.ensure_sold_loaded(event, load)
    assert await store.unloaded([event, other]) == [other]


async def test_sold_cache_marker_expires(store, event):
    async def load(event_id: int) -> list[str]:
        return []

    await store.ensure_sold_loaded(event, load)  # e.g. an id that belongs to no event
    assert 0 < await store.redis.ttl(sold_loaded_key(event)) <= SOLD_MARKER_TTL_SECONDS
