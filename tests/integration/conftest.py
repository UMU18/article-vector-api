"""Shared fixtures for integration tests.

These tests require the full docker compose stack:

    make up  # builds + starts api, worker, postgres, rabbitmq, redis, qdrant

Configuration:
    API_BASE_URL (default http://localhost:8000)
    REDIS_HOST / REDIS_PORT (default localhost:6379)
"""

from __future__ import annotations

import os

import httpx
import pytest


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.getenv(
        "API_BASE_URL",
        "http://localhost:8000",
    )


@pytest.fixture(scope="session")
def api_client(api_base_url: str):
    try:
        probe = httpx.get(
            f"{api_base_url}/health",
            timeout=5,
        )
        probe.raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip(
            "API not reachable - start the stack first with "
            "`make up` (docker compose up --build)"
        )

    with httpx.Client(
        base_url=api_base_url,
        timeout=180,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def redis_client():
    try:
        import redis

        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6380")),
            db=0,
            decode_responses=True,
            socket_connect_timeout=3,
        )

        client.ping()

    except Exception:  # noqa: BLE001
        pytest.skip(
            "Redis not reachable on localhost:6379 "
            "for cache assertions"
        )

    yield client