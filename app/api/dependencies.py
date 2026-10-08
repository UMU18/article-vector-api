"""FastAPI dependency providers wiring services to infrastructure.

Each request gets fresh service instances built on a request-scoped
session; infrastructural singletons (embedding service, vector repository,
cache, task publisher) are cached behind ``lru_cache``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.cache.redis import get_cache
from app.infrastructure.database.repositories.article_repository import (
    SqlAlchemyArticleRepository,
)
from app.infrastructure.database.session import get_db
from app.infrastructure.messaging.task_publisher import get_task_publisher
from app.infrastructure.vector.qdrant import get_vector_repository
from app.services.article_service import ArticleService
from app.services.embedding_service import get_embedding_service
from app.services.search_service import SearchService


def get_article_service(
    session: Session = Depends(get_db),
) -> ArticleService:
    """Build ``ArticleService`` with a request-scoped repository."""
    return ArticleService(
        repository=SqlAlchemyArticleRepository(session),
        task_publisher=get_task_publisher(),
    )


def get_search_service() -> SearchService:
    """Build ``SearchService`` from cached infrastructure singletons."""
    settings = get_settings()

    return SearchService(
        embedding_service=get_embedding_service(),
        vector_repository=get_vector_repository(),
        cache=get_cache(),
        cache_ttl=settings.search_cache_ttl,
        top_k=settings.search_top_k,
    )


# ---------------------------------------------------------------------------
# Readiness check registry (used by GET /health/ready)
# ---------------------------------------------------------------------------


def _check_postgres() -> None:
    from sqlalchemy import text

    from app.infrastructure.database.session import get_engine

    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def _check_redis() -> None:
    from app.infrastructure.cache.redis import get_redis_client

    get_redis_client().ping()


def _check_rabbitmq() -> None:
    from kombu import Connection

    settings = get_settings()
    connection = Connection(
        settings.celery_broker_url,
        connect_timeout=3,
    )

    try:
        connection.connect()
    finally:
        connection.release()


def _check_qdrant() -> None:
    from qdrant_client import QdrantClient

    settings = get_settings()

    client = QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        timeout=3,
    )

    client.get_collections()


def get_dependency_checks() -> dict[str, Callable[[], None]]:
    """Map dependency name -> probe callable (raises on failure)."""
    return {
        "postgres": _check_postgres,
        "redis": _check_redis,
        "rabbitmq": _check_rabbitmq,
        "qdrant": _check_qdrant,
    }