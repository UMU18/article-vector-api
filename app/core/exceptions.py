"""Application and domain exceptions.

API-facing errors derive from :class:`AppError` and are rendered by the global
exception handlers in ``app.main`` into the envelope::

    {"error": {"code": "...", "message": "..."}}

Worker/embedding errors are plain domain exceptions and never reach the API.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for API-facing application errors."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or "An unexpected error occurred"

        if code is not None:
            self.code = code

        if status_code is not None:
            self.status_code = status_code

        super().__init__(self.message)


class ArticleNotFoundError(AppError):
    """Raised when an article cannot be found."""

    status_code = 404
    code = "ARTICLE_NOT_FOUND"

    def __init__(self, message: str = "Article not found") -> None:
        super().__init__(message)


class ValidationAppError(AppError):
    """Raised when application-level validation fails."""

    status_code = 422
    code = "VALIDATION_ERROR"


class DependencyUnavailableError(AppError):
    """Raised when an external dependency is unavailable."""

    status_code = 503
    code = "DEPENDENCY_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Embedding / processing domain errors
# (used by services + Celery worker)
# ---------------------------------------------------------------------------


class EmbeddingError(Exception):
    """Base class for embedding-related failures."""


class EmbeddingValidationError(EmbeddingError):
    """Invalid embedding input. Non-retryable."""


class EmbeddingAPIError(EmbeddingError):
    """Simulated external embedding API failure. Retryable."""


class EmbeddingTimeoutError(EmbeddingError):
    """Embedding generation exceeded the configured timeout. Retryable."""


class TransientProcessingError(EmbeddingError):
    """Wrapper handed to ``self.retry`` when scheduling a Celery retry."""