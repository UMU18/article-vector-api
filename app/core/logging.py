"""Structured logging with JSON output and request correlation.

Provides:

- ``configure_logging``: idempotent root logger setup (JSON or human-readable).
- ``request_id_var``: context variable carrying the current ``request_id`` so
  every log line emitted during an HTTP request (or worker execution) can be
  traced.
- ``LogContext``: small helper to push a static request ID, e.g. inside the
  Celery worker where there is no HTTP request.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone


request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)


# Extra log-record attributes that are promoted into the JSON payload.
_STRUCTURED_FIELDS = (
    "article_id",
    "task_id",
    "status",
    "duration_ms",
    "error",
    "query",
    "attempt",
    "retry_count",
    "path",
    "method",
    "collection",
    "app_name",
    "app_env",
    "countdown",
    "embedding_id",
)


_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "stacklevel",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id

        for field in _STRUCTURED_FIELDS:
            value = record.__dict__.get(field)

            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


class TextFormatter(logging.Formatter):
    """Human-friendly console format used for local debugging."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<7} {record.getMessage()}"

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key in _STRUCTURED_FIELDS
        }

        request_id = request_id_var.get()
        if request_id:
            extras["request_id"] = request_id

        if extras:
            pairs = " ".join(
                f"{key}={value}"
                for key, value in extras.items()
            )
            base = f"{base} {pairs}"

        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"

        return base


_configured = False


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
) -> None:
    """Configure the root logger once; safe to call multiple times."""
    global _configured

    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Quieten noisy third-party loggers while keeping our own events visible.
    for noisy in (
        "uvicorn.access",
        "celery.app.trace",
        "celery.worker.consumer",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the given name."""
    return logging.getLogger(name)


class LogContext:
    """Attach a stable request ID to logs produced outside HTTP requests."""

    def __init__(self, request_id: str) -> None:
        self._token = request_id_var.set(request_id)

    def release(self) -> None:
        """Restore the previous request ID context."""
        request_id_var.reset(self._token)