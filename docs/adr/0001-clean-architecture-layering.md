# ADR-0001 — Clean Architecture Layering

- **Status:** Accepted
- **Date:** 2026-01-01
- **Context:** Requires a modular/clean architecture where business
  logic does not depend directly on FastAPI, Redis, RabbitMQ, Qdrant or
  SQLAlchemy, and where infrastructure implements interfaces needed by the
  application/domain.

## Decision

The codebase is split into concentric layers with strictly inward-pointing
imports:

```text
API (FastAPI routers, schemas)
 └─▶ Services (ArticleService, SearchService, EmbeddingService)
      └─▶ Domain (Article entity + repository PORTS)
           ▲
Infrastructure (SQLAlchemy repo, RedisCache, QdrantVectorRepository,
                Celery task publisher/DLQ) — implements the ports
```

- `app/domain/repositories/` defines abstract ports: `ArticleRepository`,
  `VectorRepository`, `CacheRepository`.
- `app/infrastructure/**` provides the concrete adapters and is the only
  place that imports third-party clients.
- The Celery worker's core is a pure orchestration function
  (`attempt_processing`) that receives its dependencies as arguments, so the
  whole resilience state machine is testable without Celery.

## Consequences

- Unit tests replace PostgreSQL/RabbitMQ/Redis/Qdrant with in-memory fakes —
  72 tests run in ~3 s with zero infrastructure.
- Swapping any backend (e.g. a real embedding provider, another vector DB)
  touches only the adapter layer.
- Cost: slightly more indirection and mapping boilerplate between ORM models
  and domain entities — accepted for the testability and substitutability
  gains.
