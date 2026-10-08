"""Redis-backed implementation of the ``CacheRepository`` port."""

from __future__ import annotations

from functools import lru_cache

import redis

from app.core.config import get_settings
from app.domain.repositories.cache_repository import CacheRepository


class RedisCache(CacheRepository):
    """Thin wrapper around redis-py with decoded (str) responses."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        print(f"REDIS SET: {key}")
        self._client.set(key, value, ex=ttl_seconds)


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis:
    """Process-wide Redis client.

    Short socket timeouts ensure the cache is treated as best-effort
    and never blocks the API for long.
    """
    settings = get_settings()

    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


@lru_cache(maxsize=1)
def get_cache() -> CacheRepository:
    """Return the process-wide cache repository."""
    return RedisCache(get_redis_client())