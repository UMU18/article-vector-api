"""Pydantic schemas for article endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.entities.article import ArticleStatus


class ArticleCreateRequest(BaseModel):
    """POST /api/v1/articles body."""

    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)
    author: str = Field(min_length=1, max_length=200)

    @field_validator("title", "content", "author")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "must contain at least one non-whitespace character"
            )

        return value


class ArticleCreatedResponse(BaseModel):
    """202 Accepted body."""

    id: uuid.UUID
    status: ArticleStatus


class ArticleResponse(BaseModel):
    """Full article representation (optional GET /articles/{id})."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    author: str
    status: ArticleStatus
    embedding_id: uuid.UUID | None = None
    error_message: str | None = None
    retry_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    processed_at: datetime | None = None


class ArticleStatusResponse(BaseModel):
    """Processing status representation
    (optional GET /articles/{id}/status).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ArticleStatus
    retry_count: int = 0
    error_message: str | None = None
    embedding_id: uuid.UUID | None = None
    processed_at: datetime | None = None


class HealthResponse(BaseModel):
    """GET /health body."""

    status: str = "ok"


class ReadinessResponse(BaseModel):
    """GET /health/ready body - one entry per backing dependency."""

    status: str
    dependencies: dict[str, str]