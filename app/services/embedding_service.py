"""Mock embedding service - the heart of the flaky AI simulation.

Behaviour contract:

- Output is a ``list[float]`` of exactly ``EMBEDDING_DIMENSION`` (128) values.

- ``generate(text)`` simulates an unreliable external AI API:
  - 30% -> EmbeddingAPIError (retryable system/API error)
  - 20% -> sleep > 5 s (guaranteed to trip the 5 s timeout)
  - 50% -> success

- ``generate_with_timeout(text)`` enforces ``EMBEDDING_TIMEOUT_SECONDS`` using
  a worker thread, raising ``EmbeddingTimeoutError`` when exceeded.

- ``generate_query_embedding(text)`` is deterministic and *never* flaky; it is
  used by the search API so a user search cannot randomly fail.

Vector construction uses the feature-hashing trick: tokens are hashed into
``dimension`` buckets with signed weights, then L2-normalised. Identical text
always produces the identical vector, and texts that share tokens end up
geometrically close, which keeps COSINE similarity meaningful in demos.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import (
    EmbeddingAPIError,
    EmbeddingTimeoutError,
    EmbeddingValidationError,
)
from app.core.logging import get_logger


logger = get_logger(__name__)


# Simulated failure distribution.
EMBEDDING_ERROR_RATE = 0.30
EMBEDDING_DELAY_RATE = 0.20

# Delay window must exceed the 5 s default timeout so the timeout path is
# exercised for real.
EMBEDDING_DELAY_MIN_SECONDS = 5.5
EMBEDDING_DELAY_MAX_SECONDS = 8.0

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def normalize_text(text: str) -> str:
    """Trim, lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def tokenize(text: str) -> list[str]:
    """Extract lowercase alphanumeric tokens (input is lowercased first)."""
    return _TOKEN_PATTERN.findall(text.lower())


class EmbeddingService:
    """Flaky mock embedding generator with a deterministic core."""

    def __init__(
        self,
        dimension: int = 128,
        timeout_seconds: float = 5.0,
        rng: random.Random | None = None,
    ) -> None:
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds
        self._rng = rng if rng is not None else random.Random()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, text: str) -> list[float]:
        """Flaky generation path used by the Celery worker.

        Raises:
            EmbeddingValidationError: invalid input (non-retryable).
            EmbeddingAPIError: simulated API failure (retryable).
        """
        self._validate_text(text)
        self._simulate_flaky_behavior()

        return self.build_embedding(text)

    def generate_with_timeout(self, text: str) -> list[float]:
        """Run ``generate`` in a worker thread and enforce the timeout."""
        self._validate_text(text)

        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="embedding",
        )

        try:
            future = executor.submit(self.generate, text)

            try:
                return future.result(timeout=self.timeout_seconds)

            except FuturesTimeoutError as exc:
                future.cancel()

                logger.warning(
                    "embedding.timeout",
                    extra={
                        "error": f"exceeded {self.timeout_seconds}s",
                    },
                )

                raise EmbeddingTimeoutError(
                    f"embedding generation exceeded {self.timeout_seconds}s"
                ) from exc

        finally:
            executor.shutdown(wait=False)

    def generate_query_embedding(self, text: str) -> list[float]:
        """Deterministic, non-flaky path used by the search API."""
        self._validate_text(text)

        return self.build_embedding(text)

    # ------------------------------------------------------------------
    # Deterministic vector construction (feature hashing)
    # ------------------------------------------------------------------

    def build_embedding(self, text: str) -> list[float]:
        """Build a deterministic, L2-normalised embedding vector."""
        normalized = normalize_text(text)
        vector = [0.0] * self.dimension

        for token in tokenize(normalized):
            digest = hashlib.md5(token.encode("utf-8")).digest()

            bucket = int.from_bytes(
                digest[:4],
                "big",
            ) % self.dimension

            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        if all(value == 0.0 for value in vector):
            # Texts without alphanumeric tokens still get a stable vector
            # derived from the hash of the raw text.
            seed = int.from_bytes(
                hashlib.sha256(
                    normalized.encode("utf-8")
                ).digest()[:8],
                "big",
            )

            fallback_rng = random.Random(seed)

            vector = [
                fallback_rng.uniform(-1.0, 1.0)
                for _ in range(self.dimension)
            ]

        norm = math.sqrt(
            sum(value * value for value in vector)
        ) or 1.0

        return [
            value / norm
            for value in vector
        ]

    # ------------------------------------------------------------------
    # Flaky simulation
    # ------------------------------------------------------------------

    def _simulate_flaky_behavior(self) -> None:
        roll = self._rng.random()

        if roll < EMBEDDING_ERROR_RATE:
            raise EmbeddingAPIError(
                "mock embedding API returned a system error "
                "(simulated 30% failure)"
            )

        if roll < EMBEDDING_ERROR_RATE + EMBEDDING_DELAY_RATE:
            delay = self._rng.uniform(
                EMBEDDING_DELAY_MIN_SECONDS,
                EMBEDDING_DELAY_MAX_SECONDS,
            )

            logger.info(
                "embedding.simulated_delay",
                extra={
                    "status": "delay",
                    "duration_ms": round(delay * 1000),
                },
            )

            time.sleep(delay)

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingValidationError(
                "text must be a non-empty string to embed"
            )


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Process-wide embedding service configured from settings."""
    settings = get_settings()

    return EmbeddingService(
        dimension=settings.embedding_dimension,
        timeout_seconds=settings.embedding_timeout_seconds,
    )


def generate_mock_embedding(text: str) -> list[float]:
    """Helper: flaky 128-dim mock embedding.

    Simulates the unreliable external AI API and may raise
    ``EmbeddingAPIError`` / ``EmbeddingTimeoutError`` via
    ``EmbeddingService.generate_with_timeout``.
    """
    return get_embedding_service().generate_with_timeout(text)