"""Unit tests for the mock embedding service."""

from __future__ import annotations

import math
import random
import time

import pytest

from app.core.exceptions import (
    EmbeddingAPIError,
    EmbeddingTimeoutError,
    EmbeddingValidationError,
)
from app.services.embedding_service import (
    EmbeddingService,
    generate_mock_embedding,
    normalize_text,
    tokenize,
)


class ScriptedRng:
    """Deterministic rng returning scripted values from random()."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._index = 0

    def random(self) -> float:
        value = self._values[
            self._index % len(self._values)
        ]
        self._index += 1
        return value

    def uniform(
        self,
        low: float,
        high: float,
    ) -> float:
        return (low + high) / 2


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Perkembangan artificial intelligence di Indonesia",
        "teknologi",
        "a",
        "Pemilu 2029 dan dinamika politik nasional hari ini",
    ],
)
def test_embedding_has_128_dimensions(text):
    service = EmbeddingService(
        dimension=128,
        rng=ScriptedRng([0.9]),
    )

    vector = service.generate(text)

    assert len(vector) == 128
    assert all(
        isinstance(value, float)
        for value in vector
    )


def test_module_level_generate_mock_embedding_returns_128_floats(
    monkeypatch,
):
    """Returns 128 floats on the success branch of the flaky path."""
    import app.services.embedding_service as embedding_module

    stable_service = EmbeddingService(
        dimension=128,
        rng=ScriptedRng([0.9]),
    )

    monkeypatch.setattr(
        embedding_module,
        "get_embedding_service",
        lambda: stable_service,
    )

    vector = embedding_module.generate_mock_embedding(
        "deterministic helper check"
    )

    assert isinstance(vector, list)
    assert len(vector) == 128


def test_module_level_generate_mock_embedding_propagates_api_error(
    monkeypatch,
):
    """On the 30% error branch the service raises EmbeddingAPIError."""
    import app.services.embedding_service as embedding_module

    failing_service = EmbeddingService(
        dimension=128,
        rng=ScriptedRng([0.10]),
    )

    monkeypatch.setattr(
        embedding_module,
        "get_embedding_service",
        lambda: failing_service,
    )

    with pytest.raises(EmbeddingAPIError):
        embedding_module.generate_mock_embedding("any text")


def test_embedding_is_l2_normalized():
    service = EmbeddingService(
        dimension=64,
        rng=ScriptedRng([0.9]),
    )

    vector = service.build_embedding(
        "kesehatan mental di tempat kerja"
    )

    norm = math.sqrt(
        sum(value * value for value in vector)
    )

    assert norm == pytest.approx(
        1.0,
        abs=1e-9,
    )


# ---------------------------------------------------------------------------
# Determinism / similarity behaviour (feature hashing core)
# ---------------------------------------------------------------------------


def test_same_text_produces_same_vector():
    service = EmbeddingService(
        dimension=128,
        rng=ScriptedRng([0.9]),
    )

    first = service.build_embedding(
        "Teknologi AI Berkembang Pesat"
    )
    second = service.build_embedding(
        "Teknologi AI Berkembang Pesat"
    )

    assert first == second


def test_different_text_produces_different_vector():
    service = EmbeddingService(
        dimension=128,
        rng=ScriptedRng([0.9]),
    )

    first = service.build_embedding(
        "Teknologi AI Berkembang Pesat"
    )
    second = service.build_embedding(
        "Resep Rendang Padang Asli"
    )

    assert first != second


def _cosine(
    a: list[float],
    b: list[float],
) -> float:
    dot = sum(
        x * y
        for x, y in zip(a, b)
    )

    norm_a = math.sqrt(
        sum(x * x for x in a)
    )

    norm_b = math.sqrt(
        sum(y * y for y in b)
    )

    return dot / (norm_a * norm_b)


def test_texts_sharing_tokens_are_more_similar():
    service = EmbeddingService(
        dimension=128,
        rng=ScriptedRng([0.9]),
    )

    related_a = service.build_embedding(
        "teknologi ai berkembang pesat"
    )

    related_b = service.build_embedding(
        "teknologi ai masa depan"
    )

    unrelated = service.build_embedding(
        "resep masakan rendang padang"
    )

    assert _cosine(
        related_a,
        related_b,
    ) > _cosine(
        related_a,
        unrelated,
    )


def test_normalize_and_tokenize_helpers():
    assert (
        normalize_text(
            " Artificial Intelligence "
        )
        == "artificial intelligence"
    )

    assert tokenize(
        "Teknologi AI 2026!"
    ) == [
        "teknologi",
        "ai",
        "2026",
    ]

    assert tokenize(
        "TEKNOLOGI-AI"
    ) == [
        "teknologi",
        "ai",
    ]


# ---------------------------------------------------------------------------
# Flaky behaviour simulation
# ---------------------------------------------------------------------------


def test_simulated_api_error_when_roll_below_30_percent(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.embedding_service.time.sleep",
        lambda s: None,
    )

    service = EmbeddingService(
        dimension=8,
        rng=ScriptedRng([0.10]),
    )

    with pytest.raises(EmbeddingAPIError):
        service.generate("hello world")


def test_delay_path_sleeps_more_than_five_seconds(
    monkeypatch,
):
    sleeps: list[float] = []

    monkeypatch.setattr(
        "app.services.embedding_service.time.sleep",
        sleeps.append,
    )

    service = EmbeddingService(
        dimension=8,
        rng=ScriptedRng([0.35]),
    )

    vector = service.generate("hello world")

    assert len(vector) == 8
    assert len(sleeps) == 1
    assert sleeps[0] > 5.0


def test_success_when_roll_above_50_percent(monkeypatch):
    monkeypatch.setattr(
        "app.services.embedding_service.time.sleep",
        lambda s: None,
    )

    service = EmbeddingService(
        dimension=8,
        rng=ScriptedRng([0.75]),
    )

    vector = service.generate("hello world")

    assert len(vector) == 8


def test_flaky_distribution_matches_spec(monkeypatch):
    """Over 2000 calls, error rate stays within ±3% of 30%."""
    monkeypatch.setattr(
        "app.services.embedding_service.time.sleep",
        lambda s: None,
    )

    service = EmbeddingService(
        dimension=16,
        rng=random.Random(42),
    )

    errors = 0
    delays = 0
    total = 2000

    for index in range(total):
        try:
            service.generate(
                f"sample article number {index}"
            )
        except EmbeddingAPIError:
            errors += 1

    # The current service has a 30% error branch and 20% delay branch.
    # Since sleep is mocked, the delay branch completes normally.
    assert abs(errors / total - 0.30) < 0.03


def test_query_embedding_is_never_flaky():
    """The search path uses the deterministic core."""

    # RNG that would always trigger the simulated API error.
    service = EmbeddingService(
        dimension=32,
        rng=ScriptedRng([0.0]),
    )

    vector = service.generate_query_embedding(
        "teknologi artificial intelligence"
    )

    assert len(vector) == 32

    assert vector == service.build_embedding(
        "teknologi artificial intelligence"
    )


# ---------------------------------------------------------------------------
# Timeout strategy
# ---------------------------------------------------------------------------


def test_generate_with_timeout_raises_when_embedding_is_slow(
    monkeypatch,
):
    real_sleep = time.sleep

    # Compress the simulated 5.5-8s delay into
    # 0.5s of real time.
    monkeypatch.setattr(
        "app.services.embedding_service.time.sleep",
        lambda _s: real_sleep(0.5),
    )

    service = EmbeddingService(
        dimension=8,
        timeout_seconds=0.2,
        rng=ScriptedRng([0.35]),
    )

    with pytest.raises(EmbeddingTimeoutError):
        service.generate_with_timeout(
            "slow embedding call"
        )


def test_generate_with_timeout_returns_quickly_on_success():
    service = EmbeddingService(
        dimension=8,
        timeout_seconds=5.0,
        rng=ScriptedRng([0.9]),
    )

    vector = service.generate_with_timeout(
        "fast success"
    )

    assert len(vector) == 8


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_input",
    ["", " ", None, 123, [], {}],
)
def test_invalid_input_raises_validation_error(
    bad_input,
):
    service = EmbeddingService(
        dimension=8,
        rng=ScriptedRng([0.9]),
    )

    with pytest.raises(EmbeddingValidationError):
        service.generate(bad_input)


@pytest.mark.parametrize(
    "bad_input",
    ["", " ", None],
)
def test_invalid_query_embedding_raises_validation_error(
    bad_input,
):
    service = EmbeddingService(
        dimension=8,
        rng=ScriptedRng([0.9]),
    )

    with pytest.raises(EmbeddingValidationError):
        service.generate_query_embedding(bad_input)