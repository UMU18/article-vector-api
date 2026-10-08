"""Health endpoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_dependency_checks
from app.schemas.article import HealthResponse, ReadinessResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe - the process is up."""
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    summary="Readiness probe checking PostgreSQL, Redis, RabbitMQ, Qdrant",
    responses={
        200: {"description": "All dependencies reachable"},
        503: {"description": "At least one dependency is unavailable"},
    },
)
def readiness(
    checks: Annotated[
        dict[str, Callable[[], None]],
        Depends(get_dependency_checks),
    ],
) -> JSONResponse:
    """Probe every backing service; 503 as soon as any check fails."""
    results: dict[str, str] = {}

    for name, probe in checks.items():
        try:
            probe()
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - report, never leak stack
            results[name] = f"unavailable: {type(exc).__name__}"

    all_ok = all(value == "ok" for value in results.values())

    body = ReadinessResponse(
        status="ok" if all_ok else "unavailable",
        dependencies=results,
    )

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content=body.model_dump(),
    )