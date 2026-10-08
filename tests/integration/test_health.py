"""Health + readiness integration tests."""

from __future__ import annotations
import pytest

@pytest.mark.integration
def test_health_is_ok(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.integration
def test_readiness_reports_all_dependencies(api_client):
    response = api_client.get("/health/ready")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert set(body["dependencies"]) == {
        "postgres",
        "redis",
        "rabbitmq",
        "qdrant",
    }
    assert set(body["dependencies"].values()) == {"ok"}


@pytest.mark.integration
def test_openapi_docs_available(api_client):
    response = api_client.get("/docs")

    assert response.status_code == 200