"""Celery worker: asynchronous article processing with full resilience.

Pipeline per attempt:

 load article -> status=processing
 -> embedding (flaky mock, hard 5 s timeout)
 -> upsert vector to Qdrant (embedding_id = point id)
 -> status=completed (PostgreSQL)

Resilience contract:

- Transient failures (embedding API error, timeout, Qdrant down, unexpected
  errors) are retried with exact exponential backoff: 2 s, 4 s, 8 s
  (CELERY_MAX_RETRIES=3 -> 4 attempts total).
- While retries remain the article stays processing (never flips to
  failed prematurely).
- Once retries are exhausted the article is marked failed and a dead
  letter is published to the articles.dead queue (DLQ).
- Invalid embedding input is non-retryable: straight to failed + DLQ.

attempt_processing is a pure orchestration function (no Celery objects)
so the whole state machine is unit-testable with simple fakes. The Celery
task wrapper only maps the outcome to Celery semantics (retry/dead-letter).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import get_settings
from app.core.exceptions import (
    EmbeddingValidationError,
    TransientProcessingError,
)
from app.core.logging import LogContext, get_logger
from app.domain.entities.article import Article
from app.domain.repositories.article_repository import ArticleRepository
from app.domain.repositories.vector_repository import VectorRepository
from app.infrastructure.database.repositories.article_repository import (
    SqlAlchemyArticleRepository,
)
from app.infrastructure.database.session import get_session_factory
from app.infrastructure.messaging.celery_app import celery_app
from app.infrastructure.messaging.dlq import get_dlq_publisher
from app.infrastructure.vector.qdrant import get_vector_repository
from app.services.embedding_service import get_embedding_service


logger = get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Dependency wiring (monkeypatch-friendly for tests)
# ---------------------------------------------------------------------------

@contextmanager
def _worker_dependencies():
    """Yield the real dependency set for one task attempt."""
    session = get_session_factory()()

    try:
        yield {
            "repository": SqlAlchemyArticleRepository(session),
            "embedding_service": get_embedding_service(),
            "vector_repository": get_vector_repository(),
            "dlq_publisher": get_dlq_publisher(),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Core orchestration (pure, fully testable)
# ---------------------------------------------------------------------------

def attempt_processing(
    article_id: str,
    *,
    task_id: str | None,
    attempt: int,
    max_retries: int,
    repository: ArticleRepository,
    embedding_service,
    vector_repository: VectorRepository,
    dlq_publisher,
    backoff_base: int = 2,
    backoff_max: int = 60,
) -> dict:
    """Run one processing attempt and report the outcome.

    Args:
        article_id: UUID string of the article.
        task_id: Celery task id (for logs / DLQ envelope).
        attempt: 1-based attempt number (1 = first execution).
        max_retries: maximum number of retries after the first attempt
            (so attempts 1..max_retries+1 are possible).

    Returns one of:
        {"outcome": "completed", "embedding_id", "attempts"}
        {"outcome": "retry", "countdown", "error"}
        {"outcome": "dead_lettered", "error"}
        {"outcome": "skipped"} (article missing)
    """
    log_context = LogContext(
        f"task:{task_id}" if task_id else "task:unknown"
    )

    try:
        article_uuid = uuid.UUID(str(article_id))
        article: Article | None = repository.get_by_id(article_uuid)

    except Exception as exc:  # noqa: BLE001 - DB hiccups are transient
        logger.error(
            "article.processing.db_error",
            extra={
                "article_id": str(article_id),
                "error": str(exc),
            },
            exc_info=True,
        )

        return _transient_failure(
            article_id=str(article_id),
            error=f"database error: {exc}",
            attempt=attempt,
            max_retries=max_retries,
            task_id=task_id,
            repository=None,
            dlq_publisher=dlq_publisher,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )

    if article is None:
        # The article vanished (e.g. deleted); retrying makes no sense.
        logger.warning(
            "article.processing.skipped_missing",
            extra={"article_id": str(article_id)},
        )

        return {"outcome": "skipped"}

    logger.info(
        "article.processing.start",
        extra={
            "article_id": str(article.id),
            "task_id": task_id,
            "attempt": attempt,
            "status": "processing",
        },
    )

    repository.mark_processing(
        article.id,
        retry_count=attempt - 1,
    )

    try:
        vector = embedding_service.generate_with_timeout(
            article.content
        )

        embedding_id = uuid.uuid4()

        vector_repository.upsert(
            str(embedding_id),
            vector,
            payload={
                "article_id": str(article.id),
                "title": article.title,
                "author": article.author,
            },
        )

    except EmbeddingValidationError as exc:
        # Bad input will never succeed on retry -> permanent failure.
        return _permanent_failure(
            article=article,
            error=f"invalid embedding input: {exc}",
            attempt=attempt,
            task_id=task_id,
            repository=repository,
            dlq_publisher=dlq_publisher,
        )

    except Exception as exc:  # noqa: BLE001 - API error / timeout / Qdrant down
        return _transient_failure(
            article_id=str(article.id),
            error=exc,
            attempt=attempt,
            max_retries=max_retries,
            task_id=task_id,
            repository=repository,
            dlq_publisher=dlq_publisher,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )

    completed = repository.mark_completed(
        article.id,
        embedding_id=embedding_id,
        processed_at=datetime.now(timezone.utc),
        retry_count=attempt - 1,
    )

    logger.info(
        "article.processing.completed",
        extra={
            "article_id": str(article.id),
            "embedding_id": str(embedding_id),
            "attempt": attempt,
            "status": "completed",
        },
    )

    return {
        "outcome": "completed",
        "embedding_id": str(embedding_id),
        "attempts": attempt,
        "status": (
            completed.status.value
            if completed
            else "completed"
        ),
    }


def _transient_failure(
    *,
    article_id: str,
    error: Exception | str,
    attempt: int,
    max_retries: int,
    task_id: str | None,
    repository: ArticleRepository | None,
    dlq_publisher,
    backoff_base: int,
    backoff_max: int,
) -> dict:
    """Retry with exact exponential backoff, or dead-letter when exhausted."""
    error_message = (
        error
        if isinstance(error, str)
        else str(error)
    )

    if attempt > max_retries:
        logger.error(
            "article.processing.retries_exhausted",
            extra={
                "article_id": article_id,
                "task_id": task_id,
                "attempt": attempt,
                "error": error_message,
            },
        )

        if repository is not None:
            repository.mark_failed(
                uuid.UUID(article_id),
                error_message=error_message,
                retry_count=attempt - 1,
            )

        dlq_publisher.publish(
            article_id=article_id,
            task_id=task_id,
            error=error_message,
            retry_count=attempt - 1,
        )

        return {
            "outcome": "dead_lettered",
            "error": error_message,
        }

    countdown = min(
        backoff_base * (2 ** (attempt - 1)),
        backoff_max,
    )

    logger.warning(
        "article.processing.retry_scheduled",
        extra={
            "article_id": article_id,
            "task_id": task_id,
            "attempt": attempt,
            "countdown": countdown,
            "error": error_message,
        },
    )

    return {
        "outcome": "retry",
        "countdown": countdown,
        "error": error_message,
    }


def _permanent_failure(
    *,
    article: Article,
    error: str,
    attempt: int,
    task_id: str | None,
    repository: ArticleRepository,
    dlq_publisher,
) -> dict:
    """Mark failed + DLQ without any retry (non-retryable error)."""
    logger.error(
        "article.processing.permanent_failure",
        extra={
            "article_id": str(article.id),
            "task_id": task_id,
            "error": error,
        },
    )

    repository.mark_failed(
        article.id,
        error_message=error,
        retry_count=attempt - 1,
    )

    dlq_publisher.publish(
        article_id=str(article.id),
        task_id=task_id,
        error=error,
        retry_count=attempt - 1,
    )

    return {
        "outcome": "dead_lettered",
        "error": error,
    }


# ---------------------------------------------------------------------------
# Celery task wrapper
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.workers.article_worker.process_article",
    max_retries=settings.celery_max_retries,
)
def process_article(self, article_id: str) -> dict:
    """Celery task entry point; see :func:`attempt_processing`."""
    try:
        with _worker_dependencies() as deps:
            outcome = attempt_processing(
                article_id=article_id,
                task_id=self.request.id,
                attempt=self.request.retries + 1,
                max_retries=self.max_retries,
                backoff_base=2,
                backoff_max=settings.celery_retry_backoff_max,
                **deps,
            )

    except SoftTimeLimitExceeded:
        # Last-resort safety net.
        return _handle_soft_time_limit(
            article_id,
            str(self.request.id),
        )

    kind = outcome.get("outcome")

    if kind == "retry":
        # Hand control back to Celery.
        raise self.retry(
            exc=TransientProcessingError(
                outcome.get(
                    "error",
                    "transient failure",
                )
            ),
            countdown=outcome.get("countdown"),
        )

    if kind == "dead_lettered":
        _mark_task_failed_in_result_backend(
            article_id,
            outcome.get("error", "unknown"),
        )

    return outcome


def _handle_soft_time_limit(
    article_id: str,
    task_id: str,
) -> dict:
    error = "task exceeded the soft time limit"

    logger.error(
        "article.processing.soft_time_limit",
        extra={
            "article_id": article_id,
            "task_id": task_id,
            "error": error,
        },
    )

    try:
        with _worker_dependencies() as deps:
            article_uuid = uuid.UUID(article_id)

            deps["repository"].mark_failed(
                article_uuid,
                error_message=error,
            )

            deps["dlq_publisher"].publish(
                article_id=article_id,
                task_id=task_id,
                error=error,
                retry_count=0,
            )

    except Exception:  # noqa: BLE001 - never mask the original failure
        logger.exception(
            "article.processing.soft_time_limit.cleanup_failed"
        )

    _mark_task_failed_in_result_backend(
        article_id,
        error,
    )

    return {
        "outcome": "dead_lettered",
        "error": error,
    }


def _mark_task_failed_in_result_backend(
    article_id: str,
    error: str,
) -> None:
    """Expose dead-lettered tasks as FAILED in the result backend (Flower)."""
    try:
        process_article.update_state(
            state="FAILURE",
            meta={
                "article_id": article_id,
                "reason": "dead_lettered",
                "error": error,
            },
        )

    except Exception:  # noqa: BLE001 - result backend may be unavailable
        pass