"""Qdrant-backed implementation of the ``VectorRepository`` port.

Collection design:
- name: ``articles`` (configurable)
- vector size: 128
- distance: COSINE
- payload: {article_id, title, author}

Qdrant is a *search index*, PostgreSQL remains the source of truth.
Infrastructure errors are translated into ``DependencyUnavailableError`` so
the API can answer ``503`` and the worker can treat them as transient.
"""

from __future__ import annotations

import threading
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import get_settings
from app.core.exceptions import DependencyUnavailableError
from app.core.logging import get_logger
from app.domain.repositories.vector_repository import VectorPoint, VectorRepository


logger = get_logger(__name__)


class QdrantVectorRepository(VectorRepository):
    """Lazy, thread-safe Qdrant client wrapper."""

    def __init__(
        self,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._dimension = dimension
        self._ensure_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lazy configuration
    # ------------------------------------------------------------------

    @property
    def collection_name(self) -> str:
        if self._collection_name is None:
            self._collection_name = get_settings().qdrant_collection

        return self._collection_name

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = get_settings().embedding_dimension

        return self._dimension

    def _get_client(self) -> QdrantClient:
        if self._client is None:
            settings = get_settings()

            self._client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                timeout=5,
            )

        return self._client

    # ------------------------------------------------------------------
    # VectorRepository implementation
    # ------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the collection idempotently."""
        try:
            client = self._get_client()

            with self._ensure_lock:
                if client.collection_exists(self.collection_name):
                    return

                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.dimension,
                        distance=Distance.COSINE,
                    ),
                )

            logger.info(
                "qdrant.collection.created",
                extra={"collection": self.collection_name},
            )

        except Exception as exc:  # noqa: BLE001 - translated on purpose
            raise DependencyUnavailableError(
                f"Vector store unavailable: {exc}"
            ) from exc

    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> None:
        try:
            client = self._get_client()

            self.ensure_collection()

            client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                ],
                wait=True,
            )

            logger.info(
                "qdrant.upsert.success",
                extra={
                    "article_id": payload.get("article_id"),
                    "status": "upserted",
                },
            )

        except Exception as exc:  # noqa: BLE001 - translated on purpose
            raise DependencyUnavailableError(
                f"Vector store unavailable: {exc}"
            ) from exc

    def search(
        self,
        vector: list[float],
        limit: int,
    ) -> list[VectorPoint]:
        try:
            client = self._get_client()

            self.ensure_collection()

            response = client.query_points(
                collection_name=self.collection_name,
                query=vector,
                limit=limit,
                with_payload=True,
            )

            return [
                VectorPoint(
                    point_id=str(hit.id),
                    score=float(hit.score),
                    payload=dict(hit.payload or {}),
                )
                for hit in response.points
            ]

        except Exception as exc:  # noqa: BLE001 - translated on purpose
            raise DependencyUnavailableError(
                f"Vector store unavailable: {exc}"
            ) from exc


@lru_cache(maxsize=1)
def _get_vector_repository_instance() -> QdrantVectorRepository:
    return QdrantVectorRepository()


def get_vector_repository() -> QdrantVectorRepository:
    return _get_vector_repository_instance()