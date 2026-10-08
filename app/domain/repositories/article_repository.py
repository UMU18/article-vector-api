"""Repository interface for article persistence.

Implemented by ``app.infrastructure.database.repositories`` (SQLAlchemy) and by
in-memory fakes in the unit test suite. Business logic depends only on this
abstraction, never on SQLAlchemy directly (clean architecture).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.article import Article


class ArticleRepository(ABC):
    """Persistence port for the ``Article`` aggregate."""

    @abstractmethod
    def save(self, article: Article) -> Article:
        """Insert a new article and return it with DB-generated audit fields."""

    @abstractmethod
    def get_by_id(self, article_id: uuid.UUID) -> Article | None:
        """Fetch an article by primary key, or ``None`` when missing."""

    @abstractmethod
    def mark_processing(
        self,
        article_id: uuid.UUID,
        *,
        retry_count: int = 0,
    ) -> Article | None:
        """Transition an article into ``processing`` and clear stale errors."""

    @abstractmethod
    def mark_completed(
        self,
        article_id: uuid.UUID,
        *,
        embedding_id: uuid.UUID,
        processed_at: datetime,
        retry_count: int = 0,
    ) -> Article | None:
        """Transition an article into ``completed`` with its embedding reference."""

    @abstractmethod
    def mark_failed(
        self,
        article_id: uuid.UUID,
        *,
        error_message: str,
        retry_count: int | None = None,
    ) -> Article | None:
        """Transition an article into ``failed`` with a persistent error message."""

    @abstractmethod
    def count(self) -> int:
        """Total number of articles (used by the seeder smoke output)."""