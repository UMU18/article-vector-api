"""Article application service - ingestion use case."""

from __future__ import annotations

import uuid

from app.core.exceptions import ArticleNotFoundError
from app.core.logging import get_logger
from app.domain.entities.article import Article
from app.domain.repositories.article_repository import ArticleRepository


logger = get_logger(__name__)


class ArticleTaskPublisherProtocol:
    """Structural protocol so the service stays infrastructure-agnostic."""

    def publish_processing(self, article_id: str) -> str | None:
        raise NotImplementedError


class ArticleService:
    """Orchestrates article creation, persistence and async dispatch."""

    def __init__(
        self,
        repository: ArticleRepository,
        task_publisher: ArticleTaskPublisherProtocol,
    ) -> None:
        self._repository = repository
        self._task_publisher = task_publisher

    def create_article(
        self,
        *,
        title: str,
        content: str,
        author: str,
    ) -> Article:
        """Persist a new ``pending`` article and publish its processing task.

        Returns immediately with the persisted entity - embedding happens
        asynchronously, which is why the API responds with HTTP 202.
        """
        article = Article(
            title=title.strip(),
            content=content.strip(),
            author=author.strip(),
        )

        saved = self._repository.save(article)

        self._task_publisher.publish_processing(str(saved.id))

        logger.info(
            "article.created",
            extra={
                "article_id": str(saved.id),
                "status": saved.status.value,
            },
        )

        return saved

    def get_article(self, article_id: uuid.UUID) -> Article:
        """Fetch an article or raise ``ArticleNotFoundError`` (HTTP 404)."""
        article = self._repository.get_by_id(article_id)

        if article is None:
            raise ArticleNotFoundError()

        return article

    def get_article_status(self, article_id: uuid.UUID) -> Article:
        """Fetch processing status details or raise ``ArticleNotFoundError``."""
        return self.get_article(article_id)