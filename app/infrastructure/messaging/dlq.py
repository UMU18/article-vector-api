"""Dead Letter Queue publisher.

When an article has exhausted every retry, the worker publishes a structured
"dead letter" message to the ``articles.dlx`` exchange (routed to the
``articles.dead`` queue). Permanently failed messages therefore live in a
dedicated queue instead of poisoning the normal processing path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from kombu import Connection, Exchange, Queue

from app.core.config import get_settings
from app.core.logging import get_logger


logger = get_logger(__name__)

DLX_EXCHANGE = "articles.dlx"
DLQ_QUEUE = "articles.dead"
DLQ_ROUTING_KEY = "articles.dead"


class RabbitMQDeadLetterPublisher:
    """Publishes permanent-failure envelopes to the DLQ."""

    def __init__(self, broker_url: str | None = None) -> None:
        self._broker_url = broker_url

    def _url(self) -> str:
        return self._broker_url or get_settings().celery_broker_url

    def publish(
        self,
        *,
        article_id: str,
        task_id: str | None,
        error: str,
        retry_count: int = 0,
    ) -> None:
        payload = {
            "article_id": article_id,
            "task_id": task_id or "unknown",
            "error": (error or "unknown error")[:1000],
            "retry_count": retry_count,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }

        exchange = Exchange(
            DLX_EXCHANGE,
            type="direct",
            durable=True,
        )

        queue = Queue(
            DLQ_QUEUE,
            exchange=exchange,
            routing_key=DLQ_ROUTING_KEY,
            durable=True,
        )

        with Connection(
            self._url(),
            connect_timeout=5,
        ) as connection:
            producer = connection.Producer(serializer="json")

            producer.publish(
                payload,
                exchange=exchange,
                routing_key=DLQ_ROUTING_KEY,
                declare=[exchange, queue],
                delivery_mode=2,  # persistent
                retry=True,
                retry_policy={
                    "max_retries": 3,
                    "interval_start": 0.5,
                },
            )

        logger.warning(
            "article.processing.dead_letter.published",
            extra={
                "article_id": article_id,
                "task_id": payload["task_id"],
                "retry_count": retry_count,
            },
        )


@lru_cache(maxsize=1)
def get_dlq_publisher() -> RabbitMQDeadLetterPublisher:
    """Return the process-wide DLQ publisher."""
    return RabbitMQDeadLetterPublisher()