#!/usr/bin/env python3

"""Wait until backing services are reachable before starting a process.

Used by the docker compose commands to avoid startup races:

    python docker/wait_for_dependencies.py [--wait-table] [--skip-all-but-broker]

Checks (by default): PostgreSQL, Redis, RabbitMQ, Qdrant.

``--wait-table`` additionally waits for the ``articles`` table (schema owned
by the api container that runs ``alembic upgrade head``).

``--skip-all-but-broker`` only probes RabbitMQ (used by Flower).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable


DEADLINE_SECONDS = float(
    os.getenv("WAIT_FOR_DEPS_TIMEOUT", "60")
)

POLL_INTERVAL = 2.0


def _check_postgres() -> None:
    import psycopg2

    psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "articles"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        connect_timeout=3,
    ).close()


def _check_table() -> None:
    import psycopg2

    connection = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "articles"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        connect_timeout=3,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.articles')"
            )

            if cursor.fetchone()[0] is None:
                raise RuntimeError(
                    "articles table does not exist yet"
                )
    finally:
        connection.close()


def _check_redis() -> None:
    import redis

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        socket_connect_timeout=3,
    )

    client.ping()


def _check_rabbitmq() -> None:
    from kombu import Connection

    host = os.getenv("RABBITMQ_HOST", "rabbitmq")
    port = os.getenv("RABBITMQ_PORT", "5672")
    user = os.getenv("RABBITMQ_USER", "guest")
    password = os.getenv("RABBITMQ_PASSWORD", "guest")
    vhost = os.getenv("RABBITMQ_VHOST", "/")

    url = f"amqp://{user}:{password}@{host}:{port}{vhost}"

    connection = Connection(
        url,
        connect_timeout=3,
    )

    try:
        connection.connect()
    finally:
        connection.release()


def _check_qdrant() -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "qdrant"),
        port=int(os.getenv("QDRANT_PORT", "6333")),
        timeout=3,
    )

    client.get_collections()


def wait_for(
    checks: dict[str, Callable[[], None]],
) -> None:
    pending = dict(checks)
    deadline = time.monotonic() + DEADLINE_SECONDS

    while pending:
        for name, probe in list(pending.items()):
            try:
                probe()

                print(
                    f"[wait-for-deps] {name}: ready",
                    flush=True,
                )

                del pending[name]

            except Exception as exc:  # noqa: BLE001 - keep polling
                print(
                    f"[wait-for-deps] {name}: {exc}",
                    flush=True,
                )

        if not pending:
            break

        if time.monotonic() > deadline:
            print(
                f"[wait-for-deps] Timed out after "
                f"{DEADLINE_SECONDS}s; "
                f"still waiting for: {', '.join(pending)}",
                flush=True,
            )
            sys.exit(1)

        time.sleep(POLL_INTERVAL)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--wait-table",
        action="store_true",
        help="also wait until the articles table exists",
    )

    parser.add_argument(
        "--skip-all-but-broker",
        action="store_true",
        help="only probe RabbitMQ (Flower)",
    )

    args = parser.parse_args()

    if args.skip_all_but_broker:
        checks = {
            "rabbitmq": _check_rabbitmq,
        }
    else:
        checks = {
            "postgres": _check_postgres,
            "redis": _check_redis,
            "rabbitmq": _check_rabbitmq,
            "qdrant": _check_qdrant,
        }

    if args.wait_table:
        checks["articles-table"] = _check_table

    wait_for(checks)

    return 0


if __name__ == "__main__":
    sys.exit(main())