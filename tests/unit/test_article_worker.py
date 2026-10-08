"""Unit tests for the article processing worker.

Exercises the pure ``attempt_processing`` state machine with fakes, plus the
Celery task wrapper in direct-call mode (no broker required).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import app.workers.article_worker as worker_module
from app.core.exceptions import (
    EmbeddingAPIError,
    EmbeddingTimeoutError,
    EmbeddingValidationError,
    TransientProcessingError,
)
from app.domain.entities.article import Article, ArticleStatus
from tests.unit.fakes import (
    FakeArticleRepository,
    FakeDeadLetterPublisher,
    FakeVectorRepository,
    StubEmbeddingService,
)


MAX_RETRIES = 3  # 3 retries -> 4 attempts total


def _article(**overrides) -> Article:
    defaults = dict(
        title="Perkembangan Artificial Intelligence",
        content="teknologi ai berkembang pesat di indonesia",
        author="John Doe",
    )

    defaults.update(overrides)

    return Article(**defaults)


def _deps(article: Article | None = None):
    repository = FakeArticleRepository(
        [article] if article else []
    )

    return (
        repository,
        FakeVectorRepository(),
        FakeDeadLetterPublisher(),
    )


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_success_completes_article_and_upserts_vector():
    article = _article()

    repository, vector_repo, dlq = _deps(article)

    embedding = StubEmbeddingService(
        vector=[0.25] * 128
    )

    outcome = worker_module.attempt_processing(
        str(article.id),
        task_id="task-1",
        attempt=1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=embedding,
        vector_repository=vector_repo,
        dlq_publisher=dlq,
    )

    assert outcome["outcome"] == "completed"
    assert outcome["attempts"] == 1

    stored = repository.get_by_id(article.id)

    assert stored.status == ArticleStatus.COMPLETED
    assert stored.embedding_id is not None
    assert stored.processed_at is not None
    assert stored.retry_count == 0

    # Exactly one vector upserted with the minimal payload.
    assert len(vector_repo.upserts) == 1

    point_id, vector, payload = vector_repo.upserts[0]

    assert point_id == str(stored.embedding_id)
    assert len(vector) == 128

    assert payload == {
        "article_id": str(article.id),
        "title": article.title,
        "author": article.author,
    }

    assert dlq.messages == []


def test_processing_status_is_set_before_embedding():
    article = _article()

    repository, _, _ = _deps(article)

    # Embedding raises immediately -> we can observe the
    # "processing" write.
    embedding = StubEmbeddingService(
        error=EmbeddingAPIError("boom")
    )

    worker_module.attempt_processing(
        str(article.id),
        task_id="task-2",
        attempt=1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=embedding,
        vector_repository=FakeVectorRepository(),
        dlq_publisher=FakeDeadLetterPublisher(),
    )

    stored = repository.get_by_id(article.id)

    # Transient failure with retries remaining -> stays in processing.
    assert stored.status == ArticleStatus.PROCESSING
    assert stored.error_message is None


# ---------------------------------------------------------------------------
# Retry + exponential backoff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempt", "expected_countdown"),
    [
        (1, 2),
        (2, 4),
        (3, 8),
    ],
)
def test_retry_countdown_is_exponential(
    attempt,
    expected_countdown,
):
    article = _article()

    repository, _, dlq = _deps(article)

    outcome = worker_module.attempt_processing(
        str(article.id),
        task_id="task-3",
        attempt=attempt,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(
            error=EmbeddingAPIError("api down")
        ),
        vector_repository=FakeVectorRepository(),
        dlq_publisher=dlq,
    )

    assert outcome["outcome"] == "retry"
    assert outcome["countdown"] == expected_countdown
    assert dlq.messages == []

    assert (
        repository.get_by_id(article.id).status
        == ArticleStatus.PROCESSING
    )


def test_retries_exhausted_dead_letters_and_marks_failed():
    article = _article()

    repository, vector_repo, dlq = _deps(article)

    outcome = worker_module.attempt_processing(
        str(article.id),
        task_id="task-4",
        attempt=MAX_RETRIES + 1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(
            error=EmbeddingAPIError("api down")
        ),
        vector_repository=vector_repo,
        dlq_publisher=dlq,
    )

    assert outcome["outcome"] == "dead_lettered"

    stored = repository.get_by_id(article.id)

    assert stored.status == ArticleStatus.FAILED
    assert "api down" in stored.error_message
    assert stored.retry_count == MAX_RETRIES

    # Nothing ever reached Qdrant, but a DLQ envelope was published.
    assert vector_repo.upserts == []

    assert len(dlq.messages) == 1

    message = dlq.messages[0]

    assert message["article_id"] == str(article.id)
    assert message["task_id"] == "task-4"
    assert message["retry_count"] == MAX_RETRIES


def test_embedding_timeout_is_transient_and_retried():
    article = _article()

    repository, _, dlq = _deps(article)

    outcome = worker_module.attempt_processing(
        str(article.id),
        task_id="task-5",
        attempt=1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(
            error=EmbeddingTimeoutError("timed out")
        ),
        vector_repository=FakeVectorRepository(),
        dlq_publisher=dlq,
    )

    assert outcome["outcome"] == "retry"

    assert (
        repository.get_by_id(article.id).status
        == ArticleStatus.PROCESSING
    )


def test_qdrant_outage_is_transient_and_retried():
    article = _article()

    repository, _, dlq = _deps(article)

    outcome = worker_module.attempt_processing(
        str(article.id),
        task_id="task-6",
        attempt=1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(
            vector=[0.1] * 128
        ),
        vector_repository=FakeVectorRepository(
            fail=True
        ),
        dlq_publisher=dlq,
    )

    assert outcome["outcome"] == "retry"

    assert (
        repository.get_by_id(article.id).status
        == ArticleStatus.PROCESSING
    )


# ---------------------------------------------------------------------------
# Non-retryable + skip paths
# ---------------------------------------------------------------------------


def test_invalid_embedding_input_fails_immediately_without_retry():
    article = _article()

    repository, _, dlq = _deps(article)

    outcome = worker_module.attempt_processing(
        str(article.id),
        task_id="task-7",
        attempt=1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(
            error=EmbeddingValidationError("empty")
        ),
        vector_repository=FakeVectorRepository(),
        dlq_publisher=dlq,
    )

    assert outcome["outcome"] == "dead_lettered"

    stored = repository.get_by_id(article.id)

    assert stored.status == ArticleStatus.FAILED
    assert len(dlq.messages) == 1


def test_missing_article_is_skipped():
    repository, vector_repo, dlq = _deps()

    outcome = worker_module.attempt_processing(
        str(uuid.uuid4()),
        task_id="task-8",
        attempt=1,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(),
        vector_repository=vector_repo,
        dlq_publisher=dlq,
    )

    assert outcome == {"outcome": "skipped"}
    assert dlq.messages == []


def test_retry_count_is_tracked_on_retry_attempts():
    article = _article()

    repository, _, _ = _deps(article)

    worker_module.attempt_processing(
        str(article.id),
        task_id="task-9",
        attempt=2,
        max_retries=MAX_RETRIES,
        repository=repository,
        embedding_service=StubEmbeddingService(
            error=EmbeddingAPIError("x")
        ),
        vector_repository=FakeVectorRepository(),
        dlq_publisher=FakeDeadLetterPublisher(),
    )

    assert repository.get_by_id(article.id).retry_count == 1


# ---------------------------------------------------------------------------
# Celery task wrapper (direct call; broker not required)
# ---------------------------------------------------------------------------


def _patch_worker_dependencies(
    monkeypatch,
    deps: dict,
):
    from contextlib import contextmanager

    @contextmanager
    def fake_dependencies():
        yield deps

    monkeypatch.setattr(
        worker_module,
        "_worker_dependencies",
        fake_dependencies,
    )


def test_celery_task_success_direct_call(monkeypatch):
    article = _article()

    repository = FakeArticleRepository([article])

    deps = {
        "repository": repository,
        "embedding_service": StubEmbeddingService(
            vector=[0.3] * 128
        ),
        "vector_repository": FakeVectorRepository(),
        "dlq_publisher": FakeDeadLetterPublisher(),
    }

    _patch_worker_dependencies(
        monkeypatch,
        deps,
    )

    outcome = worker_module.process_article(
        str(article.id)
    )

    assert outcome["outcome"] == "completed"

    assert (
        repository.get_by_id(article.id).status
        == ArticleStatus.COMPLETED
    )


def test_celery_task_schedules_retry(monkeypatch):
    article = _article()

    deps = {
        "repository": FakeArticleRepository([article]),
        "embedding_service": StubEmbeddingService(
            error=EmbeddingAPIError("boom")
        ),
        "vector_repository": FakeVectorRepository(),
        "dlq_publisher": FakeDeadLetterPublisher(),
    }

    _patch_worker_dependencies(
        monkeypatch,
        deps,
    )

    # Inside a real worker ``self.retry`` raises
    # ``celery.exceptions.Retry`` and the message is republished
    # with countdown 2. When the task is invoked directly (here)
    # Celery re-raises the wrapped transient exception instead -
    # either way the retry path must fire.
    with pytest.raises(TransientProcessingError):
        worker_module.process_article(
            str(article.id)
        )


def test_celery_task_dead_letter_when_no_retries_allowed(
    monkeypatch,
):
    article = _article()

    repository = FakeArticleRepository([article])
    dlq = FakeDeadLetterPublisher()

    deps = {
        "repository": repository,
        "embedding_service": StubEmbeddingService(
            error=EmbeddingAPIError("boom")
        ),
        "vector_repository": FakeVectorRepository(),
        "dlq_publisher": dlq,
    }

    _patch_worker_dependencies(
        monkeypatch,
        deps,
    )

    recorded: list[tuple[str, str]] = []

    monkeypatch.setattr(
        worker_module,
        "_mark_task_failed_in_result_backend",
        lambda article_id, error: recorded.append(
            (article_id, error)
        ),
    )

    original = worker_module.process_article.max_retries
    worker_module.process_article.max_retries = 0

    try:
        outcome = worker_module.process_article(
            str(article.id)
        )
    finally:
        worker_module.process_article.max_retries = original

    assert outcome["outcome"] == "dead_lettered"
    assert len(dlq.messages) == 1

    assert (
        repository.get_by_id(article.id).status
        == ArticleStatus.FAILED
    )

    # Dead-lettered tasks surface as FAILURE in the result backend
    # (Flower).
    assert recorded == [
        (str(article.id), outcome["error"])
    ]