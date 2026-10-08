"""Celery application wired to RabbitMQ with a dead-letter setup.

Queue topology:

- ``articles`` -> main processing queue. Declared with
  ``x-dead-letter-exchange`` / ``x-dead-letter-routing-key`` so that messages
  rejected/expired at the broker level are automatically rerouted.

- ``articles.dead`` -> the Dead Letter Queue (DLQ), bound to the
  ``articles.dlx`` direct exchange.

The worker additionally publishes explicit DLQ messages after exhausting all
retries (see ``app.infrastructure.messaging.dlq``) - belt and braces.
"""

from __future__ import annotations

from celery import Celery
from kombu import Exchange, Queue

from app.core.config import get_settings


DLX_EXCHANGE = "articles.dlx"
DLQ_QUEUE = "articles.dead"
DLQ_ROUTING_KEY = "articles.dead"

DEFAULT_QUEUE = "articles"
DEFAULT_ROUTING_KEY = "articles"


def create_celery_app() -> Celery:
    """Build and configure the Celery application."""
    settings = get_settings()

    application = Celery(
        "article_vector_api",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.workers.article_worker"],
    )

    default_exchange = Exchange(
        "articles",
        type="direct",
        durable=True,
    )

    dlx_exchange = Exchange(
        DLX_EXCHANGE,
        type="direct",
        durable=True,
    )

    application.conf.update(
        # Serialisation
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],

        # Reliability: ack only after a task finishes, fetch one at a time.
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,

        # Time limits (last-resort safety net; the embedding call has its own
        # fine-grained internal timeout).
        task_soft_time_limit=settings.celery_task_soft_time_limit,
        task_time_limit=settings.celery_task_time_limit,

        # Broker resilience
        broker_connection_retry_on_startup=True,

        # Queue topology including dead-letter routing.
        task_queues=[
            Queue(
                DEFAULT_QUEUE,
                default_exchange,
                routing_key=DEFAULT_ROUTING_KEY,
                durable=True,
                queue_arguments={
                    "x-dead-letter-exchange": DLX_EXCHANGE,
                    "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
                },
            ),
            Queue(
                DLQ_QUEUE,
                dlx_exchange,
                routing_key=DLQ_ROUTING_KEY,
                durable=True,
            ),
        ],

        task_default_queue=DEFAULT_QUEUE,
        task_default_exchange="articles",
        task_default_exchange_type="direct",
        task_default_routing_key=DEFAULT_ROUTING_KEY,

        # Results
        result_expires=3600,
        timezone="UTC",
        enable_utc=True,
    )

    return application


celery_app = create_celery_app()