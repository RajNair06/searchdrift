"""Pytest fixtures shared across all tests.

The ``db`` fixture gives each test a database session with automatic rollback,
so tests don't leave data behind. This matches the pattern in test_health.py
where we enter the lifespan manually.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from searchdrift.api.app import app, lifespan


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Provide a database session for tests.

    Lifecycle:
      1. Enter the lifespan (creates engine and sessionmaker).
      2. Create a session and begin a transaction.
      3. Yield the session to the test.
      4. Rollback the transaction (undo all test data).
      5. Close the session.

    This means every test starts with a clean database and leaves no trace.
    """
    async with lifespan(app):
        sessionmaker = app.state.sessionmaker
        async with sessionmaker() as session:
            # Use a savepoint so the test can commit internally (for FK checks)
            # but we roll back everything at the end.
            nested = await session.begin_nested()
            yield session
            await nested.rollback()
