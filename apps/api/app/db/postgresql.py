"""
PostgreSQL Database Configuration

This module provides SQLAlchemy setup for PostgreSQL database connection.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base

# Create a SQLAlchemy base class for declarative models
Base = declarative_base()


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
    logger.debug("Initializing PostgreSQL async engine")

    postgres_url: str = settings.POSTGRES_URL  # type: ignore
    url = postgres_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(
        url=url,
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("PostgreSQL engine initialized for database")
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
            logger.info("PostgreSQL connections closed")
    except Exception as e:
        logger.error(f"Error closing PostgreSQL connections: {e}")
