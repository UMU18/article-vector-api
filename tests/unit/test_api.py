"""API-level unit tests using FastAPI's TestClient with overridden
dependencies - no PostgreSQL / RabbitMQ / Redis / Qdrant required.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.main import app
from app.schemas.search import SearchResponse
from tests.unit.fakes import (
    FakeArticleRepository,
    FakeVectorRepository,
)


BASE_HEADERS = {
    "X-Request-ID": "test-request-id",
}


def _override_article_service():
    from tests.unit.fakes import FakeTaskPublisher

    repository = FakeArticleRepository()

    service = deps.ArticleService(
        repository=repository,
        task_publisher=FakeTaskPublisher(),
    )

    app.dependency_overrides[deps.get_article_service] = (
        lambda: service
    )

    return repository


def _override_search_service(
    results: list[dict] | None = None,
):
    from app.domain.repositories.vector_repository import VectorPoint
    from app.services.search_service import SearchService
    from tests.unit.fakes import FakeCache, StubEmbeddingService

    vector_repo = FakeVectorRepository()

    vector_repo._points = [
        VectorPoint(
            point_id=item["article_id"],
            score=item["score"],
            payload=item,
        )
        for item in (results or [])
    ]

    class _FixedEmbedding(StubEmbeddingService):
        def generate_query_embedding(
            self,
            text: str,
        ):
            return [1.0] * 128

    service = SearchService(
        embedding_service=_FixedEmbedding(
            vector=[1.0] * 128
        ),
        vector_repository=vector_repo,
        cache=FakeCache(),
        cache_ttl=300,
        top_k=10,
    )

    app.dependency_overrides[deps.get_search_service] = (
        lambda: service
    )

    return service


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    # No context manager: lifespan (Qdrant ensure) is intentionally not run
    # so these tests stay infrastructure-free.
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/v1/articles
# ---------------------------------------------------------------------------


def test_create_article_returns_202_with_pending_status(client):
    _override_article_service()

    response = client.post(
        "/api/v1/articles",
        json={
            "title": "Judul",
            "content": "Teks panjang berita...",
            "author": "Ani",
        },
        headers=BASE_HEADERS,
    )

    assert response.status_code == 202

    body = response.json()

    uuid.UUID(body["id"])

    assert body["status"] == "pending"
    assert response.headers["X-Request-ID"] == "test-request-id"


@pytest.mark.parametrize(
    "missing_field",
    ["title", "content", "author"],
)
def test_create_article_missing_fields_returns_422_envelope(
    client,
    missing_field,
):
    _override_article_service()

    payload = {
        "title": "t",
        "content": "c",
        "author": "a",
    }

    payload.pop(missing_field)

    response = client.post(
        "/api/v1/articles",
        json=payload,
    )

    assert response.status_code == 422

    error = response.json()["error"]

    assert error["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "title": " ",
            "content": "c",
            "author": "a",
        },
        {
            "title": "t",
            "content": "",
            "author": "a",
        },
        {
            "title": "t",
            "content": "c",
            "author": " ",
        },
    ],
)
def test_create_article_whitespace_only_returns_422(
    client,
    payload,
):
    _override_article_service()

    response = client.post(
        "/api/v1/articles",
        json=payload,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/articles/search
# ---------------------------------------------------------------------------


def test_search_returns_expected_response_shape(client):
    _override_search_service(
        results=[
            {
                "article_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "title": "Perkembangan Artificial Intelligence",
                "author": "John Doe",
                "score": 0.9231,
            }
        ]
    )

    response = client.get(
        "/api/v1/articles/search",
        params={"q": "artificial intelligence"},
    )

    assert response.status_code == 200

    body = response.json()

    assert body["query"] == "artificial intelligence"
    assert body["results"][0]["score"] == pytest.approx(0.9231)

    # Validate the response against the Pydantic response schema.
    SearchResponse.model_validate(body)


def test_search_missing_query_returns_422(client):
    _override_search_service()

    response = client.get(
        "/api/v1/articles/search"
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/articles/{id} + /status
# ---------------------------------------------------------------------------


def test_get_article_by_id(client):
    from app.domain.entities.article import Article

    repository = _override_article_service()

    article = Article(
        title="T",
        content="C",
        author="A",
    )

    repository.save(article)

    response = client.get(
        f"/api/v1/articles/{article.id}"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_get_article_unknown_id_returns_404_envelope(client):
    _override_article_service()

    response = client.get(
        f"/api/v1/articles/{uuid.uuid4()}"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ARTICLE_NOT_FOUND"


def test_get_article_status_endpoint(client):
    from app.domain.entities.article import Article

    repository = _override_article_service()

    article = Article(
        title="T",
        content="C",
        author="A",
    )

    repository.save(article)

    response = client.get(
        f"/api/v1/articles/{article.id}/status"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "pending"
    assert body["retry_count"] == 0


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_all_ok(client):
    app.dependency_overrides[
        deps.get_dependency_checks
    ] = lambda: {
        "postgres": lambda: None,
        "redis": lambda: None,
        "rabbitmq": lambda: None,
        "qdrant": lambda: None,
    }

    response = client.get("/health/ready")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert set(body["dependencies"].values()) == {"ok"}


def test_readiness_dependency_down_returns_503(client):
    app.dependency_overrides[
        deps.get_dependency_checks
    ] = lambda: {
        "postgres": lambda: None,
        "redis": lambda: None,
        "rabbitmq": lambda: (
            (_ for _ in ()).throw(
                RuntimeError("broker down")
            )
        ),
        "qdrant": lambda: None,
    }

    response = client.get("/health/ready")

    assert response.status_code == 503

    body = response.json()

    assert body["status"] == "unavailable"
    assert "unavailable" in body["dependencies"]["rabbitmq"]