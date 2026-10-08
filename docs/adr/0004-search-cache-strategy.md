# ADR-0004 — Search Cache: Normalized Keys, TTL 300 s, Best-Effort

- **Status:** Accepted
- **Date:** 2026-01-01
- **Context:** Require Redis caching of search results with the
  key `article-search:{normalized_query}`, normalization
  (trim/lowercase/collapse whitespace) and a TTL of 5 minutes
  (`SEARCH_CACHE_TTL=300`).

## Decision

- `SearchService.search()` first normalizes the query and builds
  `article-search:{normalized}`.
- **Cache hit:** return the stored payload (only `query` is replaced with
  the caller's original spelling), skipping embedding + Qdrant entirely.
- **Cache miss:** embed the query (deterministic path, see ADR-0002) → Qdrant similarity search → serialize the response → SET with a TTL of 300 seconds → respond.
- **Failure mode:** every cache read/write is wrapped — Redis errors are
  logged (`search.cache.unavailable`) and treated as a miss/no-op. The cache
  can never take search down; it only optimizes it.
- Query embeddings are deterministic (feature hashing), so the cached result
  for a query stays valid as long as the underlying article set is
  unchanged within the TTL window.

## Consequences

- `"  Artificial   Intelligence "`, `"artificial intelligence"` and
  `"ARTIFICIAL intelligence"` collapse to one cache entry — higher hit ratio
  and PRD compliance.
- Stale results are bounded by the 300 s TTL, which is acceptable for a
  demo-grade search index that is rebuilt asynchronously anyway.
- A Redis outage degrades latency (cache bypass), not correctness or
  availability.
