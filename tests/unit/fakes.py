"""Reusable in-memory fakes for unit tests.

These implement the *domain* repository ports so services, the worker state
machine and the FastAPI application can be exercised without PostgreSQL,
RabbitMQ, Redis or Qdrant.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain.entities.article import Article, ArticleStatus
from app.domain.repositories.article_repository import ArticleRepository
from app.domain.repositories.cache_repository import CacheRepository
from app.domain.repositories.vector_repository import (
    VectorPoint,
    VectorRepository,
)


class FakeArticleRepository(ArticleRepository):
    """In-memory article store mirroring the real state transitions."""

    def __init__(
        self,
        articles: list[Article] | None = None,
    ) -> None:
        self._articles: dict[uuid.UUID, Article] = {
            article.id: article
            for article in (articles or [])
        }

    def save(self, article: Article) -> Article:
        self._articles[article.id] = article
        return article

    def get_by_id(
        self,
        article_id: uuid.UUID,
    ) -> Article | None:
        return self._articles.get(article_id)

    def mark_processing(
        self,
        article_id: uuid.UUID,
        *,
        retry_count: int = 0,
    ) -> Article | None:
        article = self._articles.get(article_id)

        if article is None:
            return None

        article.status = ArticleStatus.PROCESSING
        article.error_message = None
        article.retry_count = retry_count

        return article

    def mark_completed(
        self,
        article_id: uuid.UUID,
        *,
        embedding_id: uuid.UUID,
        processed_at: datetime,
        retry_count: int = 0,
    ) -> Article | None:
        article = self._articles.get(article_id)

        if article is None:
            return None

        article.status = ArticleStatus.COMPLETED
        article.embedding_id = embedding_id
        article.processed_at = processed_at
        article.retry_count = retry_count
        article.error_message = None

        return article

    def mark_failed(
        self,
        article_id: uuid.UUID,
        *,
        error_message: str,
        retry_count: int | None = None,
    ) -> Article | None:
        article = self._articles.get(article_id)

        if article is None:
            return None

        article.status = ArticleStatus.FAILED
        article.error_message = error_message

        if retry_count is not None:
            article.retry_count = retry_count

        return article

    def count(self) -> int:
        return len(self._articles)


class FakeTaskPublisher:
    """Records every published article id instead of touching RabbitMQ."""

    def __init__(self) -> None:
        self.published: list[str] = []

    def publish_processing(
        self,
        article_id: str,
    ) -> str | None:
        self.published.append(article_id)
        return f"task-{len(self.published)}"


class StubEmbeddingService:
    """Scriptable embedding service: returns a fixed vector or raises."""

    def __init__(
        self,
        vector: list[float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.vector = vector or [1.0] * 128
        self.error = error
        self.calls: list[str] = []

    def generate(
        self,
        text: str,
    ) -> list[float]:
        self.calls.append(text)

        if self.error is not None:
            raise self.error

        return self.vector

    def generate_with_timeout(
        self,
        text: str,
    ) -> list[float]:
        return self.generate(text)

    def generate_query_embedding(
        self,
        text: str,
    ) -> list[float]:
        return self.generate(text)


class FakeVectorRepository(VectorRepository):
    """In-memory vector store; can be forced to fail for resilience tests.

    Mirrors the real infrastructure contract: failures are translated into
    ``DependencyUnavailableError`` (HTTP 503 / worker transient error).
    """

    def __init__(
        self,
        *,
        fail: bool = False,
        points: list[VectorPoint] | None = None,
    ) -> None:
        self.fail = fail
        self.upserts: list[
            tuple[str, list[float], dict]
        ] = []
        self.search_calls: int = 0
        self._points = list(points or [])

    def _raise_if_failing(self) -> None:
        if self.fail:
            from app.core.exceptions import DependencyUnavailableError

            raise DependencyUnavailableError(
                "Vector store unavailable: qdrant is down"
            )

    def ensure_collection(self) -> None:
        self._raise_if_failing()

    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> None:
        self._raise_if_failing()

        self.upserts.append(
            (point_id, vector, payload)
        )

    def search(
        self,
        vector: list[float],
        limit: int,
    ) -> list[VectorPoint]:
        self.search_calls += 1

        self._raise_if_failing()

        return self._points[:limit]


class FakeCache(CacheRepository):
    """In-memory TTL cache that records keys and TTLs for assertions."""

    def __init__(
        self,
        *,
        fail: bool = False,
        preloaded: dict[str, str] | None = None,
    ) -> None:
        self.fail = fail
        self.store: dict[str, str] = dict(
            preloaded or {}
        )
        self.ttls: dict[str, int] = {}
        self.set_calls: int = 0

    def get(
        self,
        key: str,
    ) -> str | None:
        if self.fail:
            raise RuntimeError("redis is down")

        return self.store.get(key)

    def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int,
    ) -> None:
        if self.fail:
            raise RuntimeError("redis is down")

        self.store[key] = value
        self.ttls[key] = ttl_seconds
        self.set_calls += 1


class FakeDeadLetterPublisher:
    """Records dead-letter envelopes instead of publishing to RabbitMQ."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def publish(
        self,
        *,
        article_id: str,
        task_id: str | None,
        error: str,
        retry_count: int = 0,
    ) -> None:
        self.messages.append(
            {
                "article_id": article_id,
                "task_id": task_id,
                "error": error,
                "retry_count": retry_count,
            }
        )