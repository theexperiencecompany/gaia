"""
PostgreSQL Database Configuration

This module provides SQLAlchemy setup for PostgreSQL database connection.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log

# Create a SQLAlchemy base class for declarative models
Base = declarative_base()


def _adapt_url_for_asyncpg(postgres_url: str) -> tuple[str, dict[str, Any]]:
    """Translate a libpq-style URL into something asyncpg accepts.

    The same `POSTGRES_URL` is consumed by `psycopg` (langgraph checkpointer)
    and by `asyncpg` (this SQLAlchemy engine). psycopg accepts `sslmode=...`
    natively; asyncpg does not — it rejects the kwarg with
    `connect() got an unexpected keyword argument 'sslmode'`. We strip
    `sslmode` from the URL and translate it into a `connect_args` ssl value
    instead. Managed Postgres providers like Neon/Supabase hand out URLs
    with `?sslmode=require`, so this is the common path.
    """
    parts = urlsplit(postgres_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    connect_args: dict[str, Any] = {}

    sslmode_values = query.pop("sslmode", None)
    if sslmode_values:
        sslmode = sslmode_values[0].lower()
        # asyncpg's `ssl` kwarg accepts True/False/'require'/etc.
        # 'disable' → no SSL; everything else → require SSL.
        if sslmode in {"disable", "allow", "prefer"}:
            connect_args["ssl"] = sslmode != "disable"
        else:
            connect_args["ssl"] = True

    rebuilt_query = urlencode([(k, v) for k, vs in query.items() for v in vs])
    rebuilt = urlunsplit((parts.scheme, parts.netloc, parts.path, rebuilt_query, parts.fragment))
    url = rebuilt.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url, connect_args


@lazy_provider(
    name="postgresql_engine",
    required_keys=[settings.POSTGRES_URL],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
async def init_postgresql_engine() -> AsyncEngine:
    """
    Initialize PostgreSQL async engine with proper connection pooling.

    Returns:
        AsyncEngine: The SQLAlchemy async engine
    """
    log.debug("Initializing PostgreSQL async engine")

    postgres_url: str = settings.POSTGRES_URL  # type: ignore
    url, connect_args = _adapt_url_for_asyncpg(postgres_url)

    engine = create_async_engine(
        url=url,
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args=connect_args,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.set(db={"connection_status": "connected", "backend": "postgresql"})
    log.info("PostgreSQL engine initialized for database")
    return engine


async def get_postgresql_engine() -> AsyncEngine:
    """
    Get the PostgreSQL engine from lazy provider.

    Returns:
        AsyncEngine: The SQLAlchemy async engine

    Raises:
        RuntimeError: If PostgreSQL engine is not available
    """
    engine = await providers.aget("postgresql_engine")
    if engine is None:
        raise RuntimeError("PostgreSQL engine not available")
    return engine


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a SQLAlchemy session as an async context manager.

    Yields:
        AsyncSession: SQLAlchemy async session
    """
    engine = await get_postgresql_engine()
    async with AsyncSession(engine) as session:
        try:
            yield session
        finally:
            await session.close()


async def close_postgresql_db() -> None:
    """
    Close database connections.
    Should be called during application shutdown.
    """
    try:
        if providers.is_initialized("postgresql_engine"):
            engine = await get_postgresql_engine()
            await engine.dispose()
            log.info("PostgreSQL connections closed")
    except Exception as e:
        log.error(f"Error closing PostgreSQL connections: {e}")
