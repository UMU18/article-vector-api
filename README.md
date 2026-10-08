# Article Ingestion & Vector Search API

A production-style backend service that ingests articles through a REST API,
processes them asynchronously with Celery + RabbitMQ, stores 128-dimensional
mock embeddings in Qdrant, and serves similarity search with a 5-minute Redis
cache — built with FastAPI, PostgreSQL and Clean Architecture.

## 1. Project Overview

The system solves the classic "unreliable external AI dependency" problem
end to end:

1. **Ingest** — `POST /api/v1/articles` validates the payload, persists the
   article to PostgreSQL with status `pending`, publishes a Celery task via
   RabbitMQ, and immediately responds `202 Accepted` with the article id.
2. **Process** — a Celery worker picks the task up, simulates embedding
   generation through `generate_mock_embedding()` (an intentionally flaky
   external-AI stand-in: 30% API errors, 20% >5s delays, 50% success),
   enforces a hard 5-second timeout, retries transient failures with exact
   exponential backoff (2s → 4s → 8s), and dead-letters permanent failures.
3. **Index** — successful embeddings (128 floats) are upserted into the
   Qdrant `articles` collection (COSINE distance) with a minimal payload
   `{article_id, title, author}`.
4. **Search** — `GET /api/v1/articles/search?q=...` normalizes the query,
   checks Redis (`article-search:{normalized}`, TTL 300s), and on a cache
   miss embeds the query and runs a similarity search against Qdrant.
5. **Seed** — a Faker-powered CLI (`python -m app.cli seed`) generates
   configurable amounts of Indonesian dummy articles that flow through the
   exact same async pipeline as production data.

Everything runs with a single `docker compose up --build`.

## 2. Architecture

```text
                         ┌──────────────────┐
                         │      Client      │
                         └────────┬─────────┘
                                  │ HTTP
                                  ▼
                     ┌────────────────────────┐
                     │       FastAPI          │
                     │  POST /api/v1/articles │
                     │  GET  /api/v1/articles/search
                     │  GET  /health(+ready)  │
                     └───────┬────────┬───────┘
                       write │        │ read/search
                             ▼        ▼
                     ┌────────────┐  ┌─────────┐
                     │ PostgreSQL │  │  Redis  │
                     └─────┬──────┘  └────┬────┘
                           │          cache miss
                    Celery task   ┌──────┴──────┐
                           │      ▼             │
                           ▼   Qdrant ◄─────────┘
                     ┌───────────┐
                     │ RabbitMQ  │
                     └─────┬─────┘
                           ▼
                     ┌────────────────────┐
                     │   Celery Worker    │
                     │ generate embedding │
                     │ timeout / retry    │
                     └───────┬────────────┘
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
           ┌──────────┐          ┌────────────┐
           │  Qdrant  │          │ PostgreSQL │
           │  vector  │          │ completed  │
           └──────────┘          └────────────┘
```

### Clean Architecture layering

```text
app/
├── api/              # FastAPI routers + dependency wiring (delivery layer)
├── schemas/          # Pydantic request/response models (delivery layer)
├── services/         # Application use cases: article, embedding, search
├── domain/           # Entities + repository PORTS (interfaces) - no framework
├── infrastructure/   # Adapters: SQLAlchemy, Redis, Celery/RabbitMQ, Qdrant
├── workers/          # Celery task orchestrating the processing pipeline
├── cli/              # `python -m app.cli seed` (Faker seeder)
└── core/             # Config, structured logging, exceptions (shared kernel)
```

Dependency direction is strictly inward: `services` and `domain` never import
FastAPI, SQLAlchemy, Redis, RabbitMQ or Qdrant. Infrastructure implements the
ports defined in `app/domain/repositories/`, which is what makes the unit
test suite able to run the full business logic with plain in-memory fakes.

## 3. Tech Stack

| Component | Technology | Responsibility |
|---|---|---|
| API | FastAPI | REST API + OpenAPI docs |
| Language | Python 3.12 | Main programming language |
| ORM | SQLAlchemy 2.x | PostgreSQL access |
| Migration | Alembic | Schema migrations (no manual DDL) |
| Database | PostgreSQL | Source of truth for article metadata |
| Task Queue | Celery | Async background processing |
| Message Broker | RabbitMQ | Task transport + dead-letter routing |
| Cache | Redis | Search result cache (TTL 300 s) |
| Vector DB | Qdrant | Embedding storage + similarity search |
| Seeder | Faker | Indonesian dummy article generation |
| Monitoring | Flower | Optional Celery dashboard |
| Testing | Pytest | Unit + integration suites |
| Containers | Docker / Docker Compose | Reproducible local environment |

## 4. Prerequisites

- Docker Engine 24+ with the Compose v2 plugin
- Make (optional, for the Makefile shortcuts)
- Python 3.12 (optional, only for running tests or the app outside Docker)

Check your setup:

```bash
docker compose version
```

## 5. Environment Configuration

All configuration is provided via environment variables (see `.env.example`).
Inside Docker Compose the values are wired automatically; for local
non-Docker runs copy and adjust:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` / `APP_NAME` | `development` / `article-vector-api` | Identity |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | Structured logging |
| `POSTGRES_*` | `postgres:5432/articles` | Source-of-truth database |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | `redis:6379/0` | Search cache |
| `RABBITMQ_*` | `guest:guest@rabbitmq:5672` | Broker connection |
| `QDRANT_HOST` / `QDRANT_PORT` / `QDRANT_COLLECTION` | `qdrant:6333/articles` | Vector store |
| `EMBEDDING_DIMENSION` | `128` | Mock embedding size |
| `EMBEDDING_TIMEOUT_SECONDS` | `5` | Hard embedding timeout |
| `CELERY_MAX_RETRIES` | `3` | Retries before DLQ (4 attempts total) |
| `CELERY_RETRY_BACKOFF` / `CELERY_RETRY_BACKOFF_MAX` | `true` / `60` | Exponential backoff config |
| `SEARCH_CACHE_TTL` | `300` | Redis cache TTL (seconds) |
| `SEARCH_TOP_K` | `10` | Number of results returned |
| `FAKER_LOCALE` | `id_ID` | Seeder content locale |

## 6. Running with Docker Compose

```bash
docker compose up --build          # or: make up
```

This starts: `api` (migrates then serves on :8000), `worker` (waits for the
schema then consumes the `articles` queue), `postgres`, `rabbitmq`
(management UI on :15672), `redis`, `qdrant` (dashboard on :6333/dashboard).

> **Port conflicts?** If your machine already runs PostgreSQL (or any other of
> these services) locally, remap the *host* side of the port binding — not the
> internal ports. Copy `.env.example` to `.env` and set e.g.
> `POSTGRES_HOST_PORT=5433`, then run `docker compose up` again. Compose reads
> these `*_HOST_PORT` variables automatically; the containers still talk to
> each other on the default internal ports (`postgres:5432`, `redis:6379`, ...),
> so nothing in the application changes. Connect your GUI client (DBeaver,
> pgAdmin, ...) to `localhost:5433`.

Optional Celery monitoring:

```bash
docker compose --profile monitoring up -d flower   # or: make flower (UI :5555)
```

Quick smoke test:

```bash
curl -s localhost:8000/health
# {"status":"ok"}

curl -s -X POST localhost:8000/api/v1/articles \
  -H 'Content-Type: application/json' \
  -d '{"title":"Perkembangan Artificial Intelligence",
       "content":"AI berkembang pesat mengubah industri teknologi...",
       "author":"John Doe"}'
# {"id":"...","status":"pending"}

# wait a few seconds (the mock AI fails ~50% of the time), then:
curl -s "localhost:8000/api/v1/articles/search?q=artificial%20intelligence"
# {"query":"...","results":[{"article_id":"...","title":"...","author":"...","score":0.92}]}
```

## 7. Database Migration

Migrations are the *only* sanctioned way to change the schema (PRD §17).
The `api` container applies them automatically on boot; the `worker`
container waits for the resulting `articles` table before starting.

```bash
docker compose exec api alembic upgrade head      # apply all
docker compose exec api alembic downgrade -1      # roll back one step
docker compose exec api alembic history           # list revisions
```

Initial revision `0001` creates the `articles` table exactly per PRD §15:
`id UUID PK`, `title`, `content`, `author` (TEXT), `status article_status`
ENUM (`pending|processing|completed|failed`), `embedding_id UUID NULL`,
`error_message TEXT NULL`, `retry_count INTEGER`, `created_at`, `updated_at`,
`processed_at NULL`, plus indexes on `status` and `created_at`.

## 8. API Documentation

Interactive OpenAPI documentation ships with FastAPI:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Raw schema: <http://localhost:8000/openapi.json>

| Method | Endpoint | Purpose | Status |
|---|---|---|---|
| POST | `/api/v1/articles` | Create article (async embedding) | 202 |
| GET | `/api/v1/articles/search?q=` | Vector search (cached) | 200 |
| GET | `/api/v1/articles/{id}` | Article detail | 200 / 404 |
| GET | `/api/v1/articles/{id}/status` | Processing status | 200 / 404 |
| GET | `/health` | Liveness | 200 |
| GET | `/health/ready` | Postgres/Redis/RabbitMQ/Qdrant probes | 200 / 503 |

Every error uses the PRD envelope and never leaks stack traces:

```json
{"error": {"code": "ARTICLE_NOT_FOUND", "message": "Article not found"}}
```

| Situation | Status |
|---|---:|
| Success create | 202 |
| Search success | 200 |
| Validation error | 422 |
| Article not found | 404 |
| Internal error | 500 |
| Dependency unavailable | 503 |

## 9. Seeder CLI

```bash
python -m app.cli seed --count 100        # inside docker: make seed
python -m app.cli seed --count 500 --batch-size 50
```

Output:

```text
Starting article seeder...

Generating 500 articles...

[####################] 100%

Successfully created 500 articles.
Tasks dispatched: 500
Elapsed: 3.42s
```

Seeded articles are inserted as `pending` and one Celery task is published
per article, so they traverse the identical pending → processing →
completed/failed pipeline as API-created articles. Titles are enriched with
Indonesian topics (teknologi, AI, ekonomi, ...) so keyword-overlap searches
produce meaningful, ranked results with the mock embeddings.

## 10. Running Worker

Inside Docker the worker starts automatically. Manual runs:

```bash
# container
docker compose exec worker celery -A app.workers.article_worker:celery_app worker \
    --loglevel=INFO --concurrency=2 --queues=articles

# local venv (needs the infra services reachable)
celery -A app.workers.article_worker:celery_app worker --loglevel=INFO \
    --concurrency=2 --queues=articles
```

Worker reliability settings: `task_acks_late=True` (ack after completion),
`worker_prefetch_multiplier=1` (fair dispatch), `broker_connection_retry_on_startup=True`.
`task_track_started=True` + the Redis result backend give Flower full visibility.

## 11. Running Tests

```bash
pip install -r requirements.txt

pytest tests/unit -v                      # 72 tests, zero infrastructure
pytest tests/integration -m integration -v  # requires `docker compose up`
```

- **Unit tests** cover `generate_mock_embedding()` (dimension, determinism,
  30/20/50 distribution, timeout, invalid input), `ArticleService`,
  `SearchService` (cache hit/miss, normalization, TTL, 503 translation),
  the full worker state machine (success, retry countdowns 2/4/8, dead
  letter, non-retryable input, missing article) and the API layer (202/422/
  404/503 envelopes) — all with in-memory fakes via the domain ports.
- **Integration tests** exercise the real stack: ingest → poll status until
  `completed` → search finds the article → Redis cache key/TTL assertions.

## 12. Retry Strategy

`generate_mock_embedding()` simulates an unreliable AI vendor
(PRD §10): **30%** `EmbeddingAPIError`, **20%** a 5.5–8 s stall that always
trips the **5 s** `EMBEDDING_TIMEOUT_SECONDS` thread-based timeout, **50%**
success. Both failure classes are transient and retried.

Retries use exact exponential backoff (jitter disabled) with
`CELERY_MAX_RETRIES=3`, i.e. **4 attempts total**:

```text
Attempt 1 → fail → wait 2s
Attempt 2 → fail → wait 4s
Attempt 3 → fail → wait 8s
Attempt 4 → permanent failure → DLQ
```

While any retry remains, the article stays in `processing`
(`retry_count` is tracked on each attempt) — it only becomes `failed` after
the final attempt, exactly as the PRD state diagram requires.

## 13. DLQ Strategy

After retries are exhausted the worker:

1. marks the article `failed` with the error message in PostgreSQL,
2. publishes a dead-letter envelope to the `articles.dlx` exchange, routed
   to the durable `articles.dead` queue:

```json
{
  "article_id": "…",
  "task_id": "…",
  "error": "…",
  "retry_count": 3,
  "failed_at": "2026-01-01T00:00:00+00:00"
}
```

Defense in depth: the `articles` queue itself is declared with
`x-dead-letter-exchange=articles.dlx`, so any message rejected/expired at
the broker level lands in the same DLQ. Failed messages therefore never
block or poison the normal processing path, and `articles.dead` can be
inspected (`rabbitmqctl list_queues`) or replayed later. Dead-lettered tasks
are also surfaced as `FAILURE` in the result backend for Flower.

## 14. Caching Strategy

- Cache key: `article-search:{normalized_query}` where normalization is
  trim → lowercase → collapse whitespace, so `"  Artificial   Intelligence "`
  and `"artificial intelligence"` share one entry (PRD §20).
- TTL: `SEARCH_CACHE_TTL=300` seconds (5 minutes).
- On hit the cached payload is returned verbatim (only `query` is re-echoed
  as the caller sent it); on miss the flow is embed → Qdrant search →
  `SET` with TTL → respond.
- The cache is **best effort**: Redis errors are logged and skipped so a
  cache outage degrades latency, never availability.
- Query embedding uses the deterministic, non-flaky embedding path
  (ADR-0002) — searches can never randomly fail because of the simulated AI.

## 15. Qdrant Design

- Collection `articles`, `size=128`, `distance=COSINE`, created
  idempotently at API startup and lazily before every write/search.
- One point per article; the point id is a fresh UUID stored back into
  `articles.embedding_id` (PostgreSQL remains the source of truth, Qdrant is
  only a rebuildable search index).
- Minimal payload per PRD §14: `{"article_id", "title", "author"}`.
- Reads return `top_k=10` hits mapped to
  `{article_id, title, author, score(round 4)}`.
- Qdrant errors are translated to `DependencyUnavailableError` → HTTP 503 /
  worker transient retry (Scenario 3 in PRD §31).

## 16. Architecture Decision Record

Full records live in [`docs/adr/`](docs/adr):

| ADR | Decision |
|---|---|
| [ADR-0001](docs/adr/0001-clean-architecture-layering.md) | Clean Architecture layering with domain ports + infrastructure adapters |
| [ADR-0002](docs/adr/0002-mock-embedding-feature-hashing.md) | Feature-hashing mock embedding (deterministic core, flaky wrapper, non-flaky query path) |
| [ADR-0003](docs/adr/0003-retry-and-dlq-strategy.md) | Exact 2/4/8 backoff, attempt-based exhaustion, explicit DLQ publish + broker DLX |
| [ADR-0004](docs/adr/0004-search-cache-strategy.md) | Normalized-key Redis cache, TTL 300, best-effort failure mode |
| [ADR-0005](docs/adr/0005-postgresql-source-of-truth.md) | PostgreSQL as source of truth, `embedding_id` links to Qdrant points |

## 17. Qdrant Downtime Scenario

If Qdrant is down for 3 hours while ingestion continues (PRD §32):

1. The API keeps accepting articles — `POST` only touches PostgreSQL and
   RabbitMQ, so `202 Accepted` responses continue and **no article is lost**.
2. Each task runs, fails against Qdrant, retries (2/4/8 s), exhausts its
   retries and lands in the DLQ with the article marked `failed`.
3. RabbitMQ buffers the ingestion backlog meanwhile; nothing is dropped.
4. Recovery options: replay the DLQ (re-publish `articles.dead` messages)
   or add a reconciliation job that re-dispatches `embedding_id IS NULL`
   articles. The recommended production evolution (PRD §33) is to split
   `article_status` from `embedding_status` so articles stay consumable
   while their embeddings are still pending.

## 18. 500k/hour Scaling Scenario

500,000 articles/hour ≈ **139 articles/s**, versus a single-node baseline of
1 API + 1 worker. The scale-out plan:

```text
                Load Balancer
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
      API 1         API 2    ...  API N        (stateless, N replicas)
        └─────────────┼─────────────┘
                      ▼
                  RabbitMQ cluster      (quorum queues, HA)
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    Worker 1      Worker 2    ...  Worker N    (scale horizontally)
                      │
                Qdrant cluster         (sharding / replication)
```

- **API**: stateless → N replicas behind an LB; add request rate limits.
- **Celery**: `docker compose up --scale worker=N`; with ~50% flaky failure
  the effective attempt rate is ~2× the ingestion rate — provision workers
  accordingly and monitor queue depth.
- **RabbitMQ**: durable queues + persistent messages (already configured),
  quorum queues and clustering for HA.
- **PostgreSQL**: connection pooling (already), read replicas for search
  enrichment, batch inserts for the seeder, partitioning if needed.
- **Qdrant**: cluster mode with sharding as point counts grow.
- **Redis**: HA (Sentinel/cluster) once the cache becomes critical.

## 19. Trade-offs

- **Mock embeddings are keyword-hash based, not semantic.** Real transformers
  would be drop-in replacements behind `EmbeddingService`; the hashing trick
  was chosen so the demo search is deterministic and meaningful.
- **Repository methods commit per call** (no unit-of-work). Simpler and safe
  for this scale; transactions-per-aggregate would be the next refinement.
- **`status` couples article and embedding state** (per assignment scope).
  PRD §33's split into `article_status`/`embedding_status` is the better
  production design and is sketched in ADR-0005/Future Improvements.
- **Explicit DLQ publish + broker DLX** double-covers failures at the cost
  of a small dedup consideration on replay.
- **Sync SQLAlchemy + thread-based timeout** keeps the code simple and the
  Celery integration boring; an async stack would add complexity without
  benefiting this workload profile.
- **DLQ replay is manual.** A reprocess endpoint/job would automate recovery
  (listed as future work).

## 20. Future Improvements

1. Split `embedding_status` from `article_status` (PRD §33) plus a
   `POST /articles/{id}/reprocess` endpoint that requeues failed embeddings.
2. Replace the mock with a real embedding provider behind the same
   `EmbeddingService` port; add response caching for query embeddings.
3. DLQ management: replay CLI (`python -m app.cli dlq replay`), metrics on
   dead-letter volume, alerting thresholds.
4. Observability upgrade: OpenTelemetry traces across API → task → Qdrant,
   Prometheus metrics (queue depth, attempt histogram, cache hit ratio).
5. Content-addressed embeddings + Qdrant upsert dedup to make task retries
   fully idempotent even across re-dispatch.
6. CI pipeline (ruff + mypy + pytest unit gate, dockerized integration job),
   pre-commit hooks, and OpenAPI client generation.
7. Pagination + filters on search results, hybrid keyword+vector ranking.
