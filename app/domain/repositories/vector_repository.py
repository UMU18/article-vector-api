"""Repository interface for the vector store (Qdrant in production).

Abstraction keeps search/processing services free of Qdrant imports so the
vector backend can be swapped or faked in unit tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VectorPoint:
    """A single similarity-search hit."""

    point_id: str
    score: float
    payload: dict = field(default_factory=dict)


class VectorRepository(ABC):
    """Port for upserting and searching vectors."""

    @abstractmethod
    def ensure_collection(self) -> None:
        """Idempotently create the target collection when missing."""

    @abstractmethod
    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> None:
        """Store/replace a vector together with its minimal payload."""

    @abstractmethod
    def search(
        self,
        vector: list[float],
        limit: int,
    ) -> list[VectorPoint]:
        """Return the ``limit`` most similar points, best match first."""