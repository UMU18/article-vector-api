# ADR-0003 — Retry with Exact Exponential Backoff + Dead Letter Queue

- **Status:** Accepted
- **Date:** 2026-01-01
- **Context:** PRD §12 requires retries with exponential backoff (2 s, 4 s,
  8 s, then permanent failure) and §13 requires dead-lettering of messages
  that exhausted their retries, while the article must remain `processing`
  during retries and only become `failed` afterwards (§7).

## Decision

- The worker's core (`attempt_processing`) counts **1-based attempts**.
  With `CELERY_MAX_RETRIES=3` the task runs **4 attempts total**; the
  countdown for a retry after attempt *n* is
  `min(2 * 2**(n-1), CELERY_RETRY_BACKOFF_MAX)` → exactly **2, 4, 8** seconds.
- On a transient failure (simulated API error, timeout, Qdrant outage, DB
  hiccup) with retries remaining, the task raises `self.retry(exc=…,
  countdown=…)`; Celery republishes the message and the article stays
  `processing` with `retry_count = attempts - 1`.
- On permanent failure the worker:
  1. marks the article `failed` with the error message,
  2. publishes a structured envelope to the `articles.dlx` exchange →
     durable `articles.dead` queue,
  3. records the task as `FAILURE` in the result backend (Flower visibility).
- **Defense in depth:** the `articles` queue is declared with
  `x-dead-letter-exchange=articles.dlx` / `x-dead-letter-routing-key`,
  so broker-level rejections/expiries dead-letter into the same queue even
  if the explicit publish path were bypassed.
- `EmbeddingValidationError` (invalid input) is **non-retryable** and goes
  straight to `failed` + DLQ — retrying can never fix bad input.

## Alternatives considered

- **Celery `autoretry_for` + `retry_backoff`:** convenient but the PRD's
  exact 2/4/8 cadence, per-attempt status bookkeeping and DLQ hand-off are
  clearer and stricter with explicit orchestration.
- **DLX only (no explicit publish):** depends on reject-path semantics of
  the Celery/ack mode; the explicit publish makes the DLQ contract visible,
  testable and broker-agnostic.

## Consequences

- Temporary failures never mark an article `failed` prematurely.
- The normal queue can never be blocked by poison messages.
- DLQ replay (draining `articles.dead` and re-publishing) is a manual
  operation today — automated replay is listed under Future Improvements.
