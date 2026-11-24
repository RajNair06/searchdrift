"""Alembic environment: connects to Postgres and runs migrations.

This file is custom-written for our project. The default Alembic env.py uses a
synchronous engine, but we use asyncpg, so we need an async engine and
``asyncio.run()`` to drive it.

Two modes:
- **Offline** (``--sql``): generates SQL text without connecting to the database.
  Useful for reviewing what a migration will do before running it.
- **Online** (default): connects to the database and runs the migration.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from searchdrift.config import get_settings

# Import Base so Alembic can see its metadata (the registry of all tables).
# Import every model so they register themselves with Base.metadata.
from searchdrift.db import Base  # noqa: F401 — registers Base.metadata

# This import has no names used here — it registers models with Base.metadata
# as a side effect. Without it, autogenerate sees no tables.
import searchdrift.models  # noqa: F401

# Alembic Config object — gives access to alembic.ini values.
config = context.config

# Set up Python logging from alembic.ini's [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Base.metadata holds the schema of every model. Alembic compares this to
# the actual database to figure out what changed (autogenerate).
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL text without connecting to the database. Useful for reviewing
    what a migration will do before running it.
    """
    url = get_settings().database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Configure the migration context with a connection and run migrations."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside it.

    Alembic was written before async SQLAlchemy existed. This function bridges
    the gap: it creates an async engine, opens a connection, and passes it to
    the synchronous ``do_run_migrations``.
    """
    settings = get_settings()
    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,  # no pooling for migrations; one connection is enough
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to the database and apply)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
