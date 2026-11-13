"""Seat holds and the sold-seat cache in Redis.

Every state change runs as a Lua script: Redis executes a script as one atomic step, so
"check every seat, then hold all or none" can't interleave with another user's request.
"""

from collections.abc import Awaitable, Callable
from importlib import resources

from redis.asyncio import Redis


def hold_zset_key(event_id: int) -> str:
    return f"hold:z:{event_id}"  # member = seat id, score = hold expiry (epoch ms)


def hold_hash_key(event_id: int) -> str:
    return f"hold:h:{event_id}"  # seat id -> user id


def sold_key(event_id: int) -> str:
    return f"sold:{event_id}"  # sold seat ids, a cache of the database


def sold_loaded_key(event_id: int) -> str:
    return f"sold:loaded:{event_id}"  # present once sold:<event> was loaded from the DB


def _script(name: str) -> str:
    return (resources.files("booking_svc") / "lua" / f"{name}.lua").read_text()


SoldLoader = Callable[[int], Awaitable[list[str]]]


class HoldStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._hold = redis.register_script(_script("hold"))
        self._verify = redis.register_script(_script("verify"))
        self._release = redis.register_script(_script("release"))
        self._mark_sold = redis.register_script(_script("mark_sold"))

    async def ensure_sold_loaded(self, event_id: int, load_sold: SoldLoader) -> None:
        """Rebuild sold:<event> from the database if Redis lost it (restart, FLUSHALL).
        Idempotent: two pods loading at once just SADD the same seats."""
        if await self.redis.exists(sold_loaded_key(event_id)):
            return
        seats = await load_sold(event_id)
        if seats:
            await self.redis.sadd(sold_key(event_id), *seats)
        await self.redis.set(sold_loaded_key(event_id), "1")

    async def hold(
        self, event_id: int, user_id: int, seats: list[str], now_ms: int, expires_at_ms: int
    ) -> list[str]:
        """Hold all seats for the user, or none. Returns the conflicting seats."""
        keys = [hold_zset_key(event_id), hold_hash_key(event_id), sold_key(event_id)]
        return await self._hold(keys=keys, args=[now_ms, expires_at_ms, user_id, *seats])

    async def verify(
        self, event_id: int, user_id: int, seats: list[str], now_ms: int, grace_until_ms: int
    ) -> list[str]:
        """Returns the seats the user does not validly hold; extends valid holds to the grace."""
        keys = [hold_zset_key(event_id), hold_hash_key(event_id)]
        return await self._verify(keys=keys, args=[now_ms, user_id, grace_until_ms, *seats])

    async def release(self, event_id: int, user_id: int, seats: list[str]) -> int:
        keys = [hold_zset_key(event_id), hold_hash_key(event_id)]
        return await self._release(keys=keys, args=[user_id, *seats])

    async def mark_sold(self, event_id: int, seats: list[str]) -> None:
        keys = [hold_zset_key(event_id), hold_hash_key(event_id), sold_key(event_id)]
        await self._mark_sold(keys=keys, args=seats)

    async def availability(
        self, event_id: int, user_id: int | None, now_ms: int
    ) -> tuple[list[str], list[str], list[str]]:
        """(sold, held, my_holds), read in one round trip. Expired holds are excluded even if
        no hold.lua has run yet to clean them up."""
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.smembers(sold_key(event_id))
            pipe.zrangebyscore(hold_zset_key(event_id), f"({now_ms}", "+inf")
            sold, held = await pipe.execute()
        my_holds: list[str] = []
        if user_id is not None and held:
            holders = await self.redis.hmget(hold_hash_key(event_id), held)
            my_holds = [seat for seat, holder in zip(held, holders, strict=True)
                        if holder == str(user_id)]  # fmt: skip
        return sorted(sold), held, my_holds
