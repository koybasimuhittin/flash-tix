"""Cache-aside for catalog reads, with a list version for cheap invalidation.

- Detail: `catalog:v1:event:{id}` → response JSON.
- List:   `catalog:v1:events:{list_version}:{sha1(normalized query)}` → response JSON.
- A write deletes the detail key and INCRs `catalog:v1:list_version`. Every list key embeds
  the version it was built under, so all old list entries stop being read at once (no SCAN,
  no key tracking) and simply expire with their TTL.

Redis failures never fail a request: reads fall back to the database, and a failed
invalidation leaves entries stale for at most one TTL.
"""

import hashlib
import json
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("catalog_svc.cache")

LIST_VERSION_KEY = "catalog:v1:list_version"


def detail_key(event_id: int) -> str:
    return f"catalog:v1:event:{event_id}"


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

    async def list_version(self) -> int:
        try:
            return int(await self.redis.get(LIST_VERSION_KEY) or 0)
        except RedisError:
            logger.warning("cache read failed", extra={"key": LIST_VERSION_KEY}, exc_info=True)
            return 0

    async def invalidate(self, event_id: int) -> None:
        """Call after a write commits. Runs even when caching is disabled, so turning the
        cache back on never serves entries from before the switch."""
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.delete(detail_key(event_id))
                pipe.incr(LIST_VERSION_KEY)
                await pipe.execute()
        except RedisError:
            logger.warning(
                "cache invalidation failed; entries stay stale until their TTL",
                extra={"event_id": event_id},
                exc_info=True,
            )
