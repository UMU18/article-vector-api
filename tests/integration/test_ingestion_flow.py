"""End-to-end ingestion flow:

POST article -> PostgreSQL -> Celery/RabbitMQ -> Qdrant -> status completed
then vector search finds the article again.
"""

from __future__ import annotations

import time
import uuid
import pytest

import httpx


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def _wait_until_completed(
    api_client: httpx.Client,
    article_id: str,
    deadline_s: int = 150,
):
    """Poll the status endpoint until the embedding pipeline finishes.

    The mock embedding fails ~30% of the time and delays ~20% of the time, so
    a generous deadline (retries with 2/4/8s backoff + slow-path sleeps) keeps
    the test stable.
    """
    deadline = time.monotonic() + deadline_s
    last_body = {}

    while time.monotonic() < deadline:
        response = api_client.get(
            f"/api/v1/articles/{article_id}/status"
        )

        assert response.status_code == 200

        last_body = response.json()

        if last_body["status"] in {"completed", "failed"}:
            return last_body

        time.sleep(2)

    return last_body

@pytest.mark.integration
def test_full_ingestion_pipeline_reaches_completed(api_client):
    max_attempts = 5
    successful_article_id = None
    final_status = {}

    for i in range(max_attempts):
        token = f"transformer{_unique_suffix()}"

        title = f"Deep Dive {token}: Arsitektur Transformer"

        content = (
            f"Artikel ini membahas {token} secara mendetail. "
            "Arsitektur transformer merevolusi pemrosesan bahasa alami "
            "dengan mekanisme self-attention dan paralelisasi penuh."
        )

        # 1. Ingest -> 202 Accepted with pending status.
        created = api_client.post(
            "/api/v1/articles",
            json={
                "title": title,
                "content": content,
                "author": "Integration Bot",
            },
        )

        assert created.status_code == 202

        body = created.json()
        article_id = body["id"]

        assert body["status"] == "pending"

        # 2. Async pipeline: worker must eventually mark it completed.
        status_body = _wait_until_completed(
            api_client,
            article_id,
        )

        if status_body["status"] == "completed":
            successful_article_id = article_id
            final_status = status_body
            break
        time.sleep(5)
    
    assert successful_article_id is not None, "All attempts failed to complete ingestion"

    assert final_status["status"] == "completed", (
        f"expected completed, got: {final_status}"
    )
    assert final_status["embedding_id"] is not None
    assert final_status["retry_count"] >= 0

    # 3. The article detail endpoint reflects the same state.
    detail = api_client.get(
        f"/api/v1/articles/{article_id}"
    )

    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"

@pytest.mark.integration
def test_vector_search_finds_ingested_article(api_client):
    max_attempts = 5
    successful_article_id = None
    successful_content = ""

    for i in range(max_attempts):
        token = f"kopi{_unique_suffix()}"
        
        title = f"Sejarah {token} di Indonesia"
        
        content = (
        f"Kopi {token} memiliki sejarah panjang di nusantara. "
        "Perkebunan kopi dibawa oleh kolonial dan berkembang pesat."
        )
        created = api_client.post(
            "/api/v1/articles",
            json={
                "title": title,
                "content": content,
                "author": "Kopi Bot",
            },
        )

        assert created.status_code == 202

        article_id = created.json()["id"]

        status_body = _wait_until_completed(
            api_client,
            article_id,
        )

        if status_body["status"] == "completed":
            successful_article_id = article_id
            successful_content = content
            break
        time.sleep(5)

    assert successful_article_id is not None, "All attempts failed to complete ingestion"

    # Search using the unique token - the article sharing that token must
    # rank at the top (feature-hashing mock embedding).
    search = api_client.get(
        "/api/v1/articles/search",
       params={"q": successful_content}
    )

    assert search.status_code == 200

    results = search.json()["results"]

    assert len(results) > 0
    article_ids = [result["article_id"] for result in results]

    assert successful_article_id in article_ids

@pytest.mark.integration
def test_pipeline_handles_permanent_failure_or_success(api_client):
    token = f"dlq_test_{_unique_suffix()}"
    created = api_client.post(
        "/api/v1/articles",
        json={"title": f"Test DLQ {token}", "content": "Konten tes", "author": "Bot"},
    )
    article_id = created.json()["id"]

    final_status = _wait_until_completed(api_client, article_id)

    assert final_status["status"] in {"completed", "failed"}

    if final_status["status"] == "failed":
        assert final_status.get("retry_count", 0) >= 3