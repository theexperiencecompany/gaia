"""Session helper for the memory Postgres store.

Wraps ``get_db_session`` with ``expire_on_commit=False`` so ORM rows
returned from write functions stay readable after the session closes
(the SQLAlchemy-recommended setting for asyncio sessions).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy import CursorResult, Result
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgresql import get_db_session


@asynccontextmanager
async def memory_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session whose rows remain usable after commit + close."""
    async with get_db_session() as session:
        session.sync_session.expire_on_commit = False
        yield session


def rowcount(result: Result[Any]) -> int:
    """Rows affected by a DML statement.

    ``session.execute`` is typed as ``Result`` but returns ``CursorResult``
    for INSERT/UPDATE/DELETE; the cast recovers ``rowcount`` for mypy.
    """
    return cast(CursorResult[Any], result).rowcount
