from redis.asyncio import Redis


def make_redis(url: str) -> Redis:
    """One client (with its own connection pool) per process; close it in the lifespan."""
    return Redis.from_url(url, decode_responses=True)
