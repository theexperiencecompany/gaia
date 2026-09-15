"""
PostgreSQL Database Configuration.

This module provides SQLAlchemy setup for PostgreSQL database connection.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.schema import DDL

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log

# Create a SQLAlchemy base class for declarative models
Base = declarative_base()

# Serializes schema bootstrap: concurrent create_all calls (API replicas, xdist
# workers) race on CREATE TYPE for enum columns and fail on pg_type's unique index.
SCHEMA_BOOTSTRAP_LOCK_ID = 743_001_993

# Same race in langgraph's checkpointer/store setup(): its CREATE TABLE IF NOT EXISTS
# collides on pg_type ("checkpoint_migrations") when two starters run it at once.
LANGGRAPH_SETUP_LOCK_ID = 743_001_994

# Datetime columns that must store tz-aware instants. create_all only CREATEs
# missing tables and never ALTERs existing ones, so legacy tables still hold
# naive timestamp columns; _ensure_timestamptz_columns promotes them in place.
_TIMESTAMPTZ_COLUMNS: tuple[tuple[str, str], ...] = (
    ("oauth_tokens", "expires_at"),
    ("oauth_tokens", "created_at"),
    ("oauth_tokens", "updated_at"),
    ("mcp_credentials", "token_expires_at"),
    ("mcp_credentials", "connected_at"),
    ("mcp_credentials", "created_at"),
    ("mcp_credentials", "updated_at"),
)


def _ensure_timestamptz_columns(connection: Connection) -> None:
    """Promote legacy naive timestamp columns (stored as UTC wall-clock) to timestamptz in place."""
    preparer = connection.dialect.identifier_preparer
    for table, column in _TIMESTAMPTZ_COLUMNS:
        data_type = connection.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).scalar()
        if data_type is None or data_type == "timestamp with time zone":
            continue
        # DDL, not text(): identifiers can never be bind parameters. Values come from the
        # _TIMESTAMPTZ_COLUMNS whitelist, not user input.
        quoted_table = preparer.quote(table)
        quoted_column = preparer.quote(column)
        connection.execute(
            DDL(
                f"ALTER TABLE {quoted_table} ALTER COLUMN {quoted_column} "
                f"TYPE timestamptz USING {quoted_column} AT TIME ZONE 'UTC'"
            )
        )
        log.info(f"{LogTag.STARTUP} Promoted column to timestamptz", table=table, column=column)


# Columns added to a table that already exists in production (create_all only CREATEs
# missing tables). Each entry is (table, column, definition); a NOT NULL definition
# must carry a DEFAULT so existing rows stay valid.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("memories", "shelf_life", "varchar(20) NOT NULL DEFAULT 'durable'"),
    ("bridge_device_mcp_servers", "kind", "varchar(20) NOT NULL DEFAULT 'stdio'"),
    ("bridge_devices", "client", "varchar(20)"),
)


def _ensure_added_columns(connection: Connection) -> None:
    """Add columns declared on a model but missing from an existing table.

    Idempotent — a fresh database already has them from create_all, and a
    re-run finds them present. Existing rows take the column's DEFAULT, which
    is why every NOT NULL entry declares one.
    """
    preparer = connection.dialect.identifier_preparer
    for table, column, definition in _ADDED_COLUMNS:
        exists = connection.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).scalar()
        if exists:
            continue
        # DDL, not text(): identifiers can never be bind parameters. Table,
        # column and definition all come from the whitelist above, never input.
        connection.execute(
            DDL(
                f"ALTER TABLE {preparer.quote(table)} ADD COLUMN {preparer.quote(column)} {definition}"
            )
        )
        log.info(f"{LogTag.STARTUP} Added missing column", table=table, column=column)


def _adapt_url_for_asyncpg(postgres_url: str) -> tuple[str, dict[str, Any]]:
    """Translate a libpq-style URL into something asyncpg accepts.

    asyncpg rejects the sslmode= kwarg psycopg accepts natively, so strip it from the URL
    and translate it into a connect_args ssl value instead.
    """
    parts = urlsplit(postgres_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    connect_args: dict[str, Any] = {}

    sslmode_values = query.pop("sslmode", None)
    if sslmode_values:
        sslmode = sslmode_values[0].lower()
        # asyncpg's `ssl` kwarg accepts True/False/'require'/etc.
        # 'disable' → no SSL; everything else → require SSL.
        connect_args["ssl"] = sslmode != "disable"

    rebuilt_query = urlencode([(k, v) for k, vs in query.items() for v in vs])
    # Replace the scheme structurally — a string replace of "postgresql://"
    # is both fragile and (for the mutator) an equivalent-mutant generator:
    # the count argument can never matter because the scheme appears once.
    url = urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=rebuilt_query))
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
    log.debug(f"{LogTag.STARTUP} Initializing PostgreSQL async engine")

    postgres_url: str = settings.POSTGRES_URL
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
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": SCHEMA_BOOTSTRAP_LOCK_ID}
        )
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_added_columns)
        await conn.run_sync(_ensure_timestamptz_columns)

    log.set(db={"connection_status": "connected", "backend": "postgresql"})
    log.info(f"{LogTag.STARTUP} PostgreSQL engine initialized for database")
    return engine


async def get_postgresql_engine() -> AsyncEngine:
    """Get the PostgreSQL engine from the lazy provider.

    Raises:
        RuntimeError: If the engine is not available.
    """
    engine = await providers.aget("postgresql_engine")
    if engine is None:
        raise RuntimeError("PostgreSQL engine not available")
    return cast(AsyncEngine, engine)


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
    """Close database connections during application shutdown."""
    try:
        if providers.is_initialized("postgresql_engine"):
            engine = await get_postgresql_engine()
            await engine.dispose()
            log.info(f"{LogTag.STARTUP} PostgreSQL connections closed")
    except Exception as e:
        log.error(
            f"{LogTag.STARTUP} Error closing PostgreSQL connections",
            error=str(e),
            error_type=type(e).__name__,
        )
