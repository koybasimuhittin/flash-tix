"""Cache-aside for catalog reads, with version numbers for cheap, race-free invalidation.

- Detail: `catalog:v1:event:{id}:{event_version}` → response JSON.
- List:   `catalog:v1:events:{list_version}:{sha1(normalized query)}` → response JSON.
- A write INCRs the event's version and the list version. Every key embeds the version it was
  built under, so old entries stop being read at once (no SCAN, no key tracking) and simply
  expire with their TTL.
- Readers fetch the version *before* the database. If a write lands in between, the reader
  stores its now-stale body under the old version, which nobody reads any more; a plain
  "delete the key" invalidation could instead be overwritten by that late write.

Redis failures never fail a request: when the version can't be read the cache is skipped and
the database answers; a failed invalidation leaves entries stale for at most one TTL.

Known limits: when a popular entry expires under heavy load, every request that misses at
that moment queries the database (cache stampede). booking-service also caches event data
in-process for CATALOG_EVENT_CACHE_TTL_SECONDS, so a schedule change can take that long to
reach seat holds.
"""

import hashlib
import json
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("catalog_svc.cache")

LIST_VERSION_KEY = "catalog:v1:list_version"


def event_version_key(event_id: int) -> str:
    return f"catalog:v1:event_version:{event_id}"


def detail_key(event_id: int, version: int) -> str:
    return f"catalog:v1:event:{event_id}:{version}"


def normalize_list_query(city: str | None, q: str | None, limit: int, offset: int) -> dict:
    """Equivalent queries (case, surrounding whitespace, empty filters) share one cache entry."""
    return {
        "city": (city or "").strip().lower() or None,
        "q": (q or "").strip().lower() or None,
        "limit": limit,
        "offset": offset,
    }


def list_key(version: int, query: dict) -> str:
    canonical = json.dumps(query, sort_keys=True, separators=(",", ":"))
    return f"catalog:v1:events:{version}:{hashlib.sha1(canonical.encode()).hexdigest()}"


class CatalogCache:
    def __init__(self, redis: Redis, ttl_seconds: int, enabled: bool) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled

    async def get(self, key: str) -> str | None:
        try:
            return await self.redis.get(key)
        except RedisError:
            logger.warning("cache read failed", extra={"key": key}, exc_info=True)
            return None

    async def set(self, key: str, value: str) -> None:
        try:
            await self.redis.set(key, value, ex=self.ttl_seconds)
        except RedisError:
            logger.warning("cache write failed", extra={"key": key}, exc_info=True)

    async def _version(self, key: str) -> int | None:
        """None when Redis can't be read: the caller then skips the cache altogether."""
        try:
            return int(await self.redis.get(key) or 0)
        except RedisError:
            logger.warning("cache read failed", extra={"key": key}, exc_info=True)
            return None

    async def list_version(self) -> int | None:
        return await self._version(LIST_VERSION_KEY)

    async def event_version(self, event_id: int) -> int | None:
        return await self._version(event_version_key(event_id))

    async def invalidate(self, event_id: int) -> None:
        """Call after a write commits. Runs even when caching is disabled, so turning the
        cache back on never serves entries from before the switch."""
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(event_version_key(event_id))
                pipe.incr(LIST_VERSION_KEY)
                await pipe.execute()
        except RedisError:
            logger.warning(
                "cache invalidation failed; entries stay stale until their TTL",
                extra={"event_id": event_id},
                exc_info=True,
            )
