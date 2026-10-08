"""Article endpoints.

Route order matters: ``/articles/search`` is declared *before*
``/articles/{article_id}`` so the literal segment is never captured by the
UUID path parameter.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_article_service, get_search_service
from app.schemas.article import (
    ArticleCreateRequest,
    ArticleCreatedResponse,
    ArticleResponse,
    ArticleStatusResponse,
)
from app.schemas.search import SearchResponse
from app.services.article_service import ArticleService
from app.services.search_service import SearchService


router = APIRouter(prefix="/articles", tags=["articles"])


@router.post(
    "",
    response_model=ArticleCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an article (async processing starts in the background)",
    responses={
        202: {"description": "Article accepted and queued for embedding"},
        422: {"description": "Validation error"},
    },
)
def create_article(
    payload: ArticleCreateRequest,
    service: Annotated[
        ArticleService,
        Depends(get_article_service),
    ],
) -> ArticleCreatedResponse:
    article = service.create_article(
        title=payload.title,
        content=payload.content,
        author=payload.author,
    )

    return ArticleCreatedResponse(
        id=article.id,
        status=article.status,
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Vector search over article embeddings (Redis cached, TTL 5 min)",
    responses={
        200: {"description": "Search results"},
        422: {"description": "Validation error"},
        503: {"description": "Vector store unavailable"},
    },
)
def search_articles(
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=500,
            description="Free-text search query",
        ),
    ],
    service: Annotated[
        SearchService,
        Depends(get_search_service),
    ],
) -> SearchResponse:
    response = service.search(q)

    return SearchResponse(**response)


@router.get(
    "/{article_id}",
    response_model=ArticleResponse,
    summary="Get a single article by id",
    responses={
        404: {"description": "Article not found"},
    },
)
def get_article(
    article_id: uuid.UUID,
    service: Annotated[
        ArticleService,
        Depends(get_article_service),
    ],
) -> ArticleResponse:
    article = service.get_article(article_id)

    return ArticleResponse.model_validate(article)


@router.get(
    "/{article_id}/status",
    response_model=ArticleStatusResponse,
    summary="Get the embedding processing status of an article",
    responses={
        404: {"description": "Article not found"},
    },
)
def get_article_status(
    article_id: uuid.UUID,
    service: Annotated[
        ArticleService,
        Depends(get_article_service),
    ],
) -> ArticleStatusResponse:
    article = service.get_article_status(article_id)

    return ArticleStatusResponse.model_validate(article)