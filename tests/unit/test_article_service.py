"""Unit tests for ArticleService."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ArticleNotFoundError
from app.domain.entities.article import ArticleStatus


def test_create_article_saves_with_pending_status_and_publishes_task(
    article_service,
    fake_repository,
    fake_publisher,
):
    article = article_service.create_article(
        title="Judul Artikel",
        content="Teks panjang berita...",
        author="Nama Author",
    )

    stored = fake_repository.get_by_id(article.id)

    assert stored is not None
    assert stored.status == ArticleStatus.PENDING
    assert stored.title == "Judul Artikel"
    assert stored.author == "Nama Author"
    assert fake_publisher.published == [str(article.id)]


def test_create_article_strips_whitespace(
    article_service,
    fake_repository,
):
    article = article_service.create_article(
        title=" Judul ",
        content=" Konten ",
        author=" Author ",
    )

    stored = fake_repository.get_by_id(article.id)

    assert stored.title == "Judul"
    assert stored.content == "Konten"
    assert stored.author == "Author"


def test_create_article_generates_uuid_ids():
    from app.services.article_service import ArticleService
    from tests.unit.fakes import (
        FakeArticleRepository,
        FakeTaskPublisher,
    )

    service = ArticleService(
        FakeArticleRepository(),
        FakeTaskPublisher(),
    )

    first = service.create_article(
        title="a",
        content="b",
        author="c",
    )

    second = service.create_article(
        title="a",
        content="b",
        author="c",
    )

    assert first.id != second.id
    assert isinstance(first.id, uuid.UUID)


def test_get_article_returns_entity(
    article_service,
    fake_repository,
):
    created = article_service.create_article(
        title="t",
        content="c",
        author="a",
    )

    fetched = article_service.get_article(created.id)

    assert fetched.id == created.id


def test_get_article_raises_not_found(article_service):
    with pytest.raises(ArticleNotFoundError):
        article_service.get_article(uuid.uuid4())


def test_get_article_status_returns_entity(article_service):
    created = article_service.create_article(
        title="t",
        content="c",
        author="a",
    )

    status_article = article_service.get_article_status(
        created.id
    )

    assert status_article.status == ArticleStatus.PENDING
    assert status_article.retry_count == 0