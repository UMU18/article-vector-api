"""Alembic environment: resolves the database URL from application settings
so migrations always target the same database the app uses."""

from __future__ import annotations

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context

from app.core.config import get_settings
from app.infrastructure.database.models import Base # noqa: F401 (imports models)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

    target_metadata = Base.metadata


    def _database_url() -> str:
        return get_settings().sync_database_url


        def run_migrations_offline() -> None:
            """Emit SQL to stdout without a live DB connection."""
            context.configure(
            url=_database_url(),
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()


                def run_migrations_online() -> None:
                    """Run migrations against a live connection."""
                    connectable = sa.create_engine(_database_url(), pool_pre_ping=True)
                    with connectable.connect() as connection:
                        context.configure(
                        connection=connection, target_metadata=target_metadata, compare_type=True
                        )
                        with context.begin_transaction():
                            context.run_migrations()


                            if context.is_offline_mode():
                                run_migrations_offline()
                            else:
                                run_migrations_online()
