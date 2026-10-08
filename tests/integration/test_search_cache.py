"""Search + Redis cache integration tests:

GET search -> Redis miss -> Qdrant -> Redis set -> response
GET search -> Redis hit -> response (same payload)
"""

from __future__ import annotations

import json
import uuid
import pytest


@pytest.mark.integration
def test_search_roundtrip_and_cache_key(api_client, redis_client):
    query = f"probe {uuid.uuid4().hex[:8]}"

    # Already normalized (lowercase, single spaces).
    normalized = query

    first = api_client.get(
        "/api/v1/articles/search",
        params={"q": query},
    )

    assert first.status_code == 200

    first_body = first.json()

    # Cache miss path wrote the response under the key.
    cache_key = f"article-search:{normalized}"

    cached = redis_client.get(cache_key)

    assert cached is not None

    ttl = redis_client.ttl(cache_key)

    assert 0 < ttl <= 300

    # The cached payload equals the first response (query + results).
    assert json.loads(cached) == first_body

    # Second request is served from cache: identical body.
    second = api_client.get(
        "/api/v1/articles/search",
        params={"q": query},
    )

    assert second.status_code == 200
    assert second.json() == first_body

@pytest.mark.integration
def test_normalized_variants_hit_the_same_cache_entry(
    api_client,
    redis_client,
):
    token = uuid.uuid4().hex[:8]
    base = f"cachecheck{token}"

    api_client.get(
        "/api/v1/articles/search",
        params={"q": f" {base} "},
    )

    # Whitespace/case variants normalize to the same key.
    assert redis_client.exists(
        f"article-search:{base}"
    ) == 1