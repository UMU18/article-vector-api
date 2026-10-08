"""SQLAlchemy engine/session plumbing (lazy so tests can import safely)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    """Create the process-wide engine on first use (lazy, pool_pre_ping)."""
    settings = get_settings()

    return create_engine(
        settings.sync_database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    """Return the session factory bound to the shared engine."""
    return sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


def get_db():
    """FastAPI dependency yielding a request-scoped session."""
    session: Session = get_session_factory()()

    try:
        yield session
    finally:
        session.close()