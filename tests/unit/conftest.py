"""Shared pytest fixtures for the unit test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2]),
)

from app.services.article_service import ArticleService  # noqa: E402
from app.services.search_service import SearchService  # noqa: E402
from tests.unit.fakes import (  # noqa: E402
    FakeArticleRepository,
    FakeCache,
    FakeDeadLetterPublisher,
    FakeTaskPublisher,
    FakeVectorRepository,
)


@pytest.fixture
def fake_repository() -> FakeArticleRepository:
    return FakeArticleRepository()


@pytest.fixture
def fake_publisher() -> FakeTaskPublisher:
    return FakeTaskPublisher()


@pytest.fixture
def article_service(
    fake_repository,
    fake_publisher,
) -> ArticleService:
    return ArticleService(
        repository=fake_repository,
        task_publisher=fake_publisher,
    )


@pytest.fixture
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture
def fake_vector_repository() -> FakeVectorRepository:
    return FakeVectorRepository()


@pytest.fixture
def fake_dlq_publisher() -> FakeDeadLetterPublisher:
    return FakeDeadLetterPublisher()


@pytest.fixture
def search_service(
    stub_embedding,
    fake_vector_repository,
    fake_cache,
) -> SearchService:
    return SearchService(
        embedding_service=stub_embedding,
        vector_repository=fake_vector_repository,
        cache=fake_cache,
        cache_ttl=300,
        top_k=10,
    )


@pytest.fixture
def stub_embedding():
    from tests.unit.fakes import StubEmbeddingService

    return StubEmbeddingService(
        vector=[0.5] * 128,
    )