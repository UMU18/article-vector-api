"""Repository interface for the search result cache (Redis in production)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class CacheRepository(ABC):
    """Minimal key/value cache port with per-entry TTL."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Return the cached string value or ``None`` on miss."""

    @abstractmethod
    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store a value with an expiry in seconds."""