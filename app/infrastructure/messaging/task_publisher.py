"""Publisher for article processing tasks.

The API publishes tasks by name via ``send_task`` so it never needs to
import the worker module - keeping the API decoupled from worker code.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.logging import get_logger
from app.infrastructure.messaging.celery_app import celery_app


logger = get_logger(__name__)

PROCESS_ARTICLE_TASK = "app.workers.article_worker.process_article"


class CeleryArticleTaskPublisher:
    """Publishes article processing tasks to the ``articles`` queue."""

    def __init__(self, application=None) -> None:
        self._application = application

    def _app(self):
        return (
            self._application
            if self._application is not None
            else celery_app
        )

    def publish_processing(self, article_id: str) -> str | None:
        """Dispatch ``process_article`` for ``article_id``; return the task id."""
        async_result = self._app().send_task(
            PROCESS_ARTICLE_TASK,
            args=[article_id],
            queue="articles",
            delivery_mode=2,  # persistent message
        )

        task_id = str(async_result.id) if async_result is not None else None

        logger.info(
            "article.task.published",
            extra={
                "article_id": article_id,
                "task_id": task_id,
            },
        )

        return task_id


@lru_cache(maxsize=1)
def get_task_publisher() -> CeleryArticleTaskPublisher:
    """Return the process-wide Celery task publisher."""
    return CeleryArticleTaskPublisher()