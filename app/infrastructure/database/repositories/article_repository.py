"""SQLAlchemy implementation of the ``ArticleRepository`` port."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities.article import Article, ArticleStatus
from app.domain.repositories.article_repository import ArticleRepository
from app.infrastructure.database.models import ArticleModel


class SqlAlchemyArticleRepository(ArticleRepository):
    """Session-backed repository; each write commits immediately so the API
    can return ``202`` with confidence that the row is durable.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, article_id: uuid.UUID) -> Article | None:
        model = self._session.get(ArticleModel, article_id)
        return self._to_entity(model) if model is not None else None

    def count(self) -> int:
        stmt = select(func.count()).select_from(ArticleModel)
        return int(self._session.scalar(stmt) or 0)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save(self, article: Article) -> Article:
        model = ArticleModel(
            id=article.id,
            title=article.title,
            content=article.content,
            author=article.author,
            status=article.status,
        )

        self._session.add(model)
        self._session.commit()
        self._session.refresh(model)

        return self._to_entity(model)

    def mark_processing(
        self,
        article_id: uuid.UUID,
        *,
        retry_count: int = 0,
    ) -> Article | None:
        return self._update(
            article_id,
            status=ArticleStatus.PROCESSING,
            error_message=None,
            retry_count=retry_count,
        )

    def mark_completed(
        self,
        article_id: uuid.UUID,
        *,
        embedding_id: uuid.UUID,
        processed_at: datetime,
        retry_count: int = 0,
    ) -> Article | None:
        return self._update(
            article_id,
            status=ArticleStatus.COMPLETED,
            embedding_id=embedding_id,
            processed_at=processed_at,
            retry_count=retry_count,
            error_message=None,
        )

    def mark_failed(
        self,
        article_id: uuid.UUID,
        *,
        error_message: str,
        retry_count: int | None = None,
    ) -> Article | None:
        return self._update(
            article_id,
            status=ArticleStatus.FAILED,
            error_message=error_message,
            retry_count=retry_count,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _update(
        self,
        article_id: uuid.UUID,
        **fields,
    ) -> Article | None:
        model = self._session.get(ArticleModel, article_id)

        if model is None:
            return None

        for name, value in fields.items():
            # ``error_message=None`` intentionally clears the column;
            # every other ``None`` means "do not touch this field".
            if value is not None or name == "error_message":
                setattr(model, name, value)

        self._session.commit()
        self._session.refresh(model)

        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: ArticleModel) -> Article:
        return Article(
            id=model.id,
            title=model.title,
            content=model.content,
            author=model.author,
            status=model.status,
            embedding_id=model.embedding_id,
            error_message=model.error_message,
            retry_count=model.retry_count,
            created_at=model.created_at,
            updated_at=model.updated_at,
            processed_at=model.processed_at,
        )