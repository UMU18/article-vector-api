"""Pydantic schemas for the vector search endpoint."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    """A single vector search result."""

    article_id: uuid.UUID
    title: str
    author: str
    score: float = Field(ge=0.0, le=1.0)


class SearchResponse(BaseModel):
    """Response body for the vector search endpoint."""

    query: str
    results: list[SearchResultItem]