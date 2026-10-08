"""FastAPI application factory / entry point.

Wires routers, structured logging, request-id middleware and the
error envelope::

    {"error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

import time
import uuid as uuid_module
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1 import articles, health
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger, request_id_var
from app.infrastructure.vector.qdrant import get_vector_repository


logger = get_logger(__name__)

DESCRIPTION = """
Article Ingestion & Vector Search API.

- **POST /api/v1/articles** ingests an article, stores it in PostgreSQL and
  dispatches an async embedding task via Celery + RabbitMQ (HTTP 202).
- **GET /api/v1/articles/search** performs similarity search against Qdrant
  with a 5-minute Redis cache.
- **GET /health** / **GET /health/ready** expose liveness and readiness.
"""


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()

    configure_logging(
        settings.log_level,
        settings.log_format,
    )

    logger.info(
        "application.startup",
        extra={
            "app_name": settings.app_name,
            "app_env": settings.app_env,
        },
    )

    # Best-effort: make sure the Qdrant collection exists
    # (size=128, COSINE).
    try:
        get_vector_repository().ensure_collection()
    except Exception as exc:  # noqa: BLE001 - startup must not block
        logger.warning(
            "qdrant.collection.ensure_failed",
            extra={"error": str(exc)},
        )

    yield

    logger.info("application.shutdown")


app = FastAPI(
    title="Article Ingestion & Vector Search API",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware: request id + access log
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_context_middleware(
    request: Request,
    call_next,
):
    request_id = (
        request.headers.get("X-Request-ID")
        or uuid_module.uuid4().hex
    )

    token = request_id_var.set(request_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)

    except Exception:
        duration_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        logger.error(
            "http.request.failed",
            extra={
                "path": request.url.path,
                "method": request.method,
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )
        raise

    else:
        duration_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        logger.info(
            "http.request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        response.headers["X-Request-ID"] = request_id

        return response

    finally:
        request_id_var.reset(token)


# ---------------------------------------------------------------------------
# Error envelope handlers
# ---------------------------------------------------------------------------

@app.exception_handler(AppError)
async def app_error_handler(
    request: Request,
    exc: AppError,
) -> JSONResponse:
    logger.warning(
        "http.app_error",
        extra={
            "path": request.url.path,
            "error": str(exc),
            "status": exc.status_code,
        },
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "field": ".".join(
                str(part)
                for part in error.get("loc", [])
            ),
            "message": error.get("msg", ""),
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": details,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Never leak stack traces to clients.
    logger.error(
        "http.unhandled_error",
        extra={
            "path": request.url.path,
            "error": str(exc),
        },
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            }
        },
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health.router)

api_v1_prefix = "/api/v1"

app.include_router(
    articles.router,
    prefix=api_v1_prefix,
)