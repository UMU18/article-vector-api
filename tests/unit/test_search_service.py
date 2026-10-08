"""Unit tests for SearchService."""

from __future__ import annotations

import json

import pytest

from app.core.exceptions import (
    DependencyUnavailableError,
    ValidationAppError,
)
from app.domain.repositories.vector_repository import VectorPoint
from tests.unit.fakes import StubEmbeddingService


def _point(
    article_id: str,
    title: str,
    author: str,
    score: float,
) -> VectorPoint:
    return VectorPoint(
        point_id=article_id,
        score=score,
        payload={
            "article_id": article_id,
            "title": title,
            "author": author,
        },
    )


def test_cache_miss_searches_qdrant_then_writes_cache(
    search_service,
    fake_vector_repository,
    fake_cache,
):
    fake_vector_repository._points = [
        _point(
            "11111111-1111-1111-1111-111111111111",
            "Judul",
            "Author",
            0.9231,
        )
    ]

    response = search_service.search(
        "artificial intelligence"
    )

    assert fake_vector_repository.search_calls == 1
    assert fake_cache.set_calls == 1

    assert response["query"] == "artificial intelligence"

    assert response["results"] == [
        {
            "article_id": "11111111-1111-1111-1111-111111111111",
            "title": "Judul",
            "author": "Author",
            "score": 0.9231,
        }
    ]


def test_cache_hit_skips_qdrant(
    search_service,
    fake_vector_repository,
    fake_cache,
):
    cached_payload = json.dumps(
        {
            "query": "anything",
            "results": [],
        }
    )

    fake_cache.store[
        "article-search:artificial intelligence"
    ] = cached_payload

    response = search_service.search(
        "artificial intelligence"
    )

    assert fake_vector_repository.search_calls == 0
    assert response["query"] == "artificial intelligence"
    assert response["results"] == []


def test_normalized_queries_share_one_cache_key(
    search_service,
    fake_vector_repository,
    fake_cache,
):
    fake_vector_repository._points = []

    search_service.search(
        " Artificial Intelligence "
    )
    search_service.search(
        "artificial intelligence"
    )

    # Both requests use the same normalized cache entry.
    assert fake_cache.set_calls == 1

    assert (
        "article-search:artificial intelligence"
        in fake_cache.store
    )


def test_cache_ttl_is_300_seconds(
    search_service,
    fake_cache,
    fake_vector_repository,
):
    fake_vector_repository._points = []

    search_service.search("teknologi")

    assert (
        fake_cache.ttls["article-search:teknologi"]
        == 300
    )


def test_scores_are_rounded_to_four_decimals(
    search_service,
    fake_vector_repository,
):
    fake_vector_repository._points = [
        _point(
            "22222222-2222-2222-2222-222222222222",
            "T",
            "A",
            0.87654321,
        )
    ]

    response = search_service.search("anything")

    assert (
        response["results"][0]["score"]
        == 0.8765
    )


def test_missing_payload_fields_are_filtered_out(
    search_service,
    fake_vector_repository,
):
    fake_vector_repository._points = [
        VectorPoint(
            point_id="x",
            score=0.5,
            payload={"foo": "bar"},
        ),
        _point(
            "33333333-3333-3333-3333-333333333333",
            "OK",
            "A",
            0.4,
        ),
    ]

    response = search_service.search("anything")

    assert [
        item["article_id"]
        for item in response["results"]
    ] == [
        "33333333-3333-3333-3333-333333333333"
    ]


def test_vector_repository_failure_maps_to_dependency_unavailable(
    search_service,
):
    search_service._vector_repository.fail = True

    with pytest.raises(DependencyUnavailableError):
        search_service.search("teknologi")


def test_cache_failure_does_not_break_search(
    search_service,
    fake_vector_repository,
    fake_cache,
):
    fake_cache.fail = True

    fake_vector_repository._points = [
        _point(
            "44444444-4444-4444-4444-444444444444",
            "T",
            "A",
            0.7,
        )
    ]

    response = search_service.search("teknologi")

    assert len(response["results"]) == 1


def test_whitespace_only_query_raises_validation_error(
    search_service,
):
    with pytest.raises(ValidationAppError):
        search_service.search(" ")


def test_search_uses_deterministic_query_embedding(
    fake_vector_repository,
    fake_cache,
):
    """Query embedding must not run the flaky simulation."""

    from app.services.embedding_service import EmbeddingService
    from app.services.search_service import SearchService

    # RNG scripted to always trigger the simulated API error.
    flaky_embedding = EmbeddingService(
        dimension=16,
        rng=type(
            "AlwaysErrorRng",
            (),
            {
                "random": staticmethod(
                    lambda: 0.0
                ),
                "uniform": staticmethod(
                    lambda a, b: a
                ),
            },
        )(),
    )

    service = SearchService(
        embedding_service=flaky_embedding,
        vector_repository=fake_vector_repository,
        cache=fake_cache,
        cache_ttl=300,
        top_k=10,
    )

    fake_vector_repository._points = []

    # Must not raise EmbeddingAPIError despite the hostile RNG.
    response = service.search("stability check")

    assert response["query"] == "stability check"