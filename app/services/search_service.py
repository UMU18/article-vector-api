"""Search application service - vector search with Redis caching.

Flow:

query -> normalise -> Redis lookup

hit -> return cached response

miss -> embed query -> Qdrant similarity search -> build response
     -> store in Redis (TTL = SEARCH_CACHE_TTL, default 300 s)

The cache is *best effort*: Redis failures are logged and skipped so search
remains available when the cache is down.
"""

from __future__ import annotations

import json

from app.core.exceptions import DependencyUnavailableError, ValidationAppError
from app.core.logging import get_logger
from app.domain.repositories.cache_repository import CacheRepository
from app.domain.repositories.vector_repository import VectorRepository
from app.services.embedding_service import EmbeddingService, normalize_text


logger = get_logger(__name__)

CACHE_KEY_PREFIX = "article-search:"


class SearchService:
    """Vector search orchestration with a normalized-key cache."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_repository: VectorRepository,
        cache: CacheRepository,
        cache_ttl: int = 300,
        top_k: int = 10,
    ) -> None:
        self._embedding_service = embedding_service
        self._vector_repository = vector_repository
        self._cache = cache
        self._cache_ttl = cache_ttl
        self._top_k = top_k

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str) -> dict:
        """Return ``{"query": ..., "results": [...]}`` response."""
        normalized = normalize_text(query)

        if not normalized:
            raise ValidationAppError("Search query must not be empty")

        cache_key = self.cache_key(normalized)

        cached = self._cache_get(cache_key)

        if cached is not None:
            logger.info(
                "search.cache.hit",
                extra={"query": normalized},
            )

            payload = json.loads(cached)
            # payload["query"] = query

            # Echo the caller's original query.
            return payload

        logger.info(
            "search.cache.miss",
            extra={"query": normalized},
        )

        vector = self._embedding_service.generate_query_embedding(
            normalized
        )

        points = self._vector_repository.search(
            vector,
            self._top_k,
        )

        results = [
            {
                "article_id": point.payload.get("article_id"),
                "title": point.payload.get("title"),
                "author": point.payload.get("author"),
                "score": round(point.score, 4),
            }
            for point in points
            if point.payload.get("article_id")
        ]

        response = {
            "query": query,
            "results": results,
        }

        self._cache_set(
            cache_key,
            json.dumps(response),
        )

        logger.info(
            "search.completed",
            extra={
                "query": normalized,
                "status": "ok",
            },
        )

        return response

    # ------------------------------------------------------------------
    # Cache helpers (best effort by design)
    # ------------------------------------------------------------------

    @staticmethod
    def cache_key(normalized_query: str) -> str:
        """Return ``article-search:{normalized_query}`` cache key."""
        return f"{CACHE_KEY_PREFIX}{normalized_query}"

    def _cache_get(self, key: str) -> str | None:
        try:
            return self._cache.get(key)
        except Exception as exc:  # noqa: BLE001 - cache must never break search
            logger.warning(
                "search.cache.unavailable",
                extra={"error": str(exc)},
            )
            return None

    def _cache_set(self, key: str, value: str) -> None:
        try:
            self._cache.set(
                key,
                value,
                self._cache_ttl,
            )
        except Exception as exc:  # noqa: BLE001 - cache must never break search
            logger.warning(
                "search.cache.unavailable",
                extra={"error": str(exc)},
            )


def raise_dependency_unavailable(
    original: Exception,
) -> DependencyUnavailableError:
    """Helper kept for explicit translation at the edges."""
    return DependencyUnavailableError(
        f"Dependency unavailable: {original}"
    )