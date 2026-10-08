"""Article domain entity - framework-agnostic core model."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime


class ArticleStatus(str, enum.Enum):
    """Processing lifecycle of an article."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Article:
    """Pure domain entity; no ORM / FastAPI / infrastructure imports."""

    title: str
    content: str
    author: str

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: ArticleStatus = ArticleStatus.PENDING
    embedding_id: uuid.UUID | None = None
    error_message: str | None = None
    retry_count: int = 0

    created_at: datetime | None = None
    updated_at: datetime | None = None
    processed_at: datetime | None = None

    def to_dict(self) -> dict:
        """Flat dictionary representation (useful for payloads and tests)."""
        return {
            "id": str(self.id),
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "status": self.status.value,
            "embedding_id": (
                str(self.embedding_id)
                if self.embedding_id
                else None
            ),
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at
                else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at
                else None
            ),
            "processed_at": (
                self.processed_at.isoformat()
                if self.processed_at
                else None
            ),
        }