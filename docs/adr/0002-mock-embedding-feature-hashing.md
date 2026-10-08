# ADR-0002 — Mock Embedding: Feature Hashing with a Flaky Wrapper

- **Status:** Accepted
- **Date:** 2026-01-01
- **Context:** PRD §9 requires `generate_mock_embedding(text) -> list[float]`
  with exactly 128 dimensions, and §10 requires it to simulate an unreliable
  external AI API (30% error, 20% delay > 5 s, 50% success) so that timeout
  and retry machinery can be exercised for real.

## Decision

`EmbeddingService` separates the **deterministic vector core** from the
**flaky simulation wrapper**:

1. **Vector core — feature hashing (hashing trick).** The text is normalized
   (trim/lowercase/collapse whitespace) and tokenized; each token is hashed
   (MD5) into one of 128 buckets with a ±1 sign taken from the hash, the
   accumulated vector is L2-normalized. Identical text always yields the
   identical vector, and texts sharing tokens are geometrically close, which
   makes COSINE search demonstrably meaningful.
2. **Flaky wrapper — `generate(text)`.** Draws one uniform roll:
   `< 0.30` → `EmbeddingAPIError`; `< 0.50` → sleep uniform(5.5, 8.0) s
   (always exceeds the 5 s timeout) then succeed; otherwise succeed
   immediately.
3. **Timeout — `generate_with_timeout(text)`.** Runs the flaky call in a
   single-worker `ThreadPoolExecutor` and raises `EmbeddingTimeoutError`
   after `EMBEDDING_TIMEOUT_SECONDS=5` via `future.result(timeout=...)`.
   The stray sleeping thread is abandoned with `shutdown(wait=False)`.
4. **Search path — `generate_query_embedding(text)`.** Calls the core
   directly, *never* the flaky wrapper, so a user search cannot randomly
   fail or stall because of the simulated vendor.

## Alternatives considered

- **Pure random vectors:** trivially satisfies the 128-float contract but
  makes search results meaningless — rejected: the demo/search flow would
  return arbitrary articles with arbitrary scores.
- **Real embedding model:** violates the "mock" requirement and adds heavy
  dependencies — rejected (but the port boundary makes this a drop-in
  upgrade later).

## Consequences

- All resilience behaviour (30/20/50, >5 s delay, timeout) is preserved and
  unit-testable with a scripted RNG.
- Search is stable and cache-friendly; repeated identical queries embed to
  identical vectors.
- The same text always maps to one vector → worker retries are effectively
  idempotent regarding vector content.
