"""Application configuration loaded from environment variables (12-factor style).

All variable names map 1:1 to the environment contract defined in the
configuration, e.g. ``POSTGRES_HOST`` -> ``postgres_host``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object for every process (API, worker, CLI)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_env: str = "development"
    app_name: str = "article-vector-api"
    log_level: str = "INFO"
    log_format: str = "json"  # "json" | "text"

    # ------------------------------------------------------------------
    # PostgreSQL (source of truth)
    # ------------------------------------------------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "articles"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"

    # ------------------------------------------------------------------
    # Redis (search cache)
    # ------------------------------------------------------------------
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # ------------------------------------------------------------------
    # RabbitMQ (message broker)
    # ------------------------------------------------------------------
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"
    rabbitmq_vhost: str = "/"

    # ------------------------------------------------------------------
    # Qdrant (vector database)
    # ------------------------------------------------------------------
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "articles"

    # ------------------------------------------------------------------
    # Mock embedding
    # ------------------------------------------------------------------
    embedding_dimension: int = 128
    embedding_timeout_seconds: float = 5.0

    # ------------------------------------------------------------------
    # Celery / resilience
    # ------------------------------------------------------------------
    celery_max_retries: int = 3
    celery_retry_backoff: bool = True
    celery_retry_backoff_max: int = 60
    celery_task_soft_time_limit: int = 30
    celery_task_time_limit: int = 60
    celery_result_backend_db: int = 1

    # ------------------------------------------------------------------
    # Search / caching
    # ------------------------------------------------------------------
    search_cache_ttl: int = 300  # 5 minutes
    search_top_k: int = 10

    # ------------------------------------------------------------------
    # Seeder
    # ------------------------------------------------------------------
    faker_locale: str = "id_ID"

    # ------------------------------------------------------------------
    # Derived connection URLs
    # ------------------------------------------------------------------
    @property
    def sync_database_url(self) -> str:
        """SQLAlchemy URL using the psycopg2 (sync) driver."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis connection URL for the search cache."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def celery_broker_url(self) -> str:
        """RabbitMQ connection URL used as the Celery broker."""
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}{self.rabbitmq_vhost}"
        )

    @property
    def celery_result_backend(self) -> str:
        """Redis URL used as the Celery result backend."""
        return (
            f"redis://{self.redis_host}:{self.redis_port}"
            f"/{self.celery_result_backend_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton ``Settings`` instance."""
    return Settings()