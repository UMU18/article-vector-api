# ADR-0005 — PostgreSQL as Source of Truth; Qdrant as Rebuildable Index

- **Status:** Accepted
- **Date:** 2026-01-01
- **Context:** PRD §14 states PostgreSQL remains the source of truth while
  Qdrant is used for vector search; §32/§33 discuss what happens when Qdrant
  is unavailable and recommend separating article status from embedding
  status in production.

## Decision

- Every accepted article lives durably in PostgreSQL (`articles` table) with
  its processing status, `retry_count`, `error_message` and audit timestamps.
- When processing succeeds, the worker upserts one Qdrant point and stores
  the point id back into `articles.embedding_id`.
- `embedding_id IS NULL` is therefore the reconciliation predicate: any
  article in a non-pending state without an embedding id can be safely
  re-dispatched to rebuild its vector.
- The API only ever reads article truth from PostgreSQL; search results are
  enriched from Qdrant payloads, which are authoritative for ranking but not
  for article existence.
- The assignment-scope simplification (single `status` column covering both
  article and embedding state) is acknowledged as a trade-off; the production
  evolution — separate `article_status` / `embedding_status` columns plus a
  reprocess flow — is documented in the README (Qdrant Downtime Scenario,
  Future Improvements).

## Consequences

- A Qdrant outage never loses data: articles stay in PostgreSQL, failures
  accumulate in the DLQ, and the index can be rebuilt at any time.
- Idempotent reprocessing: re-running a task re-embeds (deterministic
  vector) and re-upserts the same point content under a fresh point id;
  a later enhancement may switch to content-addressed point ids to make
  upserts naturally deduplicating.
