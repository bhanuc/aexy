"""Redis client for caching and rate limiting."""

import redis.asyncio as redis

from mailagent.config import get_settings

settings = get_settings()

redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global redis_client
    if redis_client is not None:
        await redis_client.close()
        redis_client = None


async def check_redis_connection() -> bool:
    """Check if Redis connection is healthy."""
    try:
        client = await get_redis()
        await client.ping()
        return True
    except Exception:
        return False


class RateLimiter:
    """Rate limiter using Redis sliding window."""

    def __init__(self, client: redis.Redis):
        self.client = client

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Check if request is within rate limit.

        Returns:
            Tuple of (allowed, remaining_requests)
        """
        import time

        now = time.time()
        window_start = now - window_seconds

        pipe = self.client.pipeline()

        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Count current entries
        pipe.zcard(key)

        # Add current request
        pipe.zadd(key, {str(now): now})

        # Set expiry
        pipe.expire(key, window_seconds)

        results = await pipe.execute()
        current_count = results[1]

        allowed = current_count < limit
        remaining = max(0, limit - current_count - 1) if allowed else 0

        return allowed, remaining

    async def get_status(self, key: str, limit: int, window_seconds: int) -> dict:
        """Get current rate limit status."""
        import time

        now = time.time()
        window_start = now - window_seconds

        await self.client.zremrangebyscore(key, 0, window_start)
        current_count = await self.client.zcard(key)

        return {
            "limit": limit,
            "remaining": max(0, limit - current_count),
            "reset_at": int(now + window_seconds),
        }
