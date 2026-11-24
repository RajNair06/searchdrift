"""Database engine (connection pool), session factory, and FastAPI dependency.

The engine is created once per process and shared. It keeps a pool of open
Postgres connections, because opening a new one costs a TCP handshake plus
authentication on every request.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Parent class for every ORM model.

    Inheriting from this tells SQLAlchemy "this class maps to a database table."
    Alembic reads ``Base.metadata`` to know which tables exist, so it can
    generate migrations that create or alter them.
    """


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_size=5,  # connections kept open
        max_overflow=5,  # extra connections allowed under bursts
        pool_pre_ping=True,  # test a pooled connection before use; drops dead ones
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    # expire_on_commit=False: objects stay readable after commit without
    # another round trip to the database (important in async code).
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: gives each endpoint a database session.

    Lifecycle per request:
      1. Create a session from the pool (one connection borrowed).
      2. Endpoint runs (db.add, db.execute, etc.).
      3. On success: commit the transaction.
      4. On exception: rollback, then re-raise so FastAPI returns 500.
      5. Always: close the session (return the connection to the pool).

    The endpoint never writes ``async with`` — FastAPI runs this generator
    around the endpoint automatically.
    """
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Type alias so endpoints stay short:  async def my_endpoint(db: DB):
DB = Annotated[AsyncSession, Depends(get_db)]
