"""LangGraph checkpointing backed by Postgres, lazily provided.

Flow
- Requires POSTGRES_URL from app.config.settings.
- @lazy_provider registers a provider for the checkpointer.
- First providers.aget(...) creates an async pool and checkpointer, then reuses it.
- Use helpers get_checkpointer_manager().

Add/change config
- Set POSTGRES_URL in settings; in dev it can be Optional.
- To alter pool size, adjust CheckpointerManager init params.
"""

from typing import cast

from langgraph.checkpoint.postgres.aio import (
    AsyncPostgresSaver,
)
from langgraph.store.postgres import AsyncPostgresStore
from psycopg import AsyncConnection
from psycopg.rows import DictRow, TupleRow
from psycopg_pool import AsyncConnectionPool

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.db.postgresql import LANGGRAPH_SETUP_LOCK_ID


class CheckpointerManager:
    """A manager class to handle checkpointer initialization and lifecycle."""

    def __init__(self, conninfo: str, max_pool_size: int = 20) -> None:
        self.conninfo = conninfo
        self.max_pool_size = max_pool_size
        # Tuple rows, deliberately — see the note in setup() on the dict_row cast.
        self.pool: AsyncConnectionPool[AsyncConnection[TupleRow]] | None = None
        self.checkpointer: AsyncPostgresSaver | None = None

    async def setup(self) -> "CheckpointerManager":
        """Initialize the connection pool and checkpointer."""
        # Swarm VXLAN drops idle TCP after ~15 min (conntrack timeout); without
        # keepalives + pool recycling the pool hands out dead sockets. Defence
        # in depth: libpq keepalives, max_idle/max_lifetime recycling, check=....
        connection_kwargs = {
            "autocommit": True,
            "prepare_threshold": 0,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }

        self.pool = AsyncConnectionPool(
            conninfo=self.conninfo,
            min_size=1,
            max_size=self.max_pool_size,
            max_idle=300,  # close connections idle for > 5 min
            max_lifetime=1800,  # recycle every 30 min regardless
            kwargs=connection_kwargs,
            check=AsyncConnectionPool.check_connection,
            open=False,
            timeout=30,
        )
        await self.pool.open(wait=True, timeout=30)

        # AsyncPostgresSaver sets row_factory=dict_row on every cursor itself,
        # so the pool's own factory is irrelevant — kept on default tuple rows
        # since other callers (cleanup, retention) index by position.
        self.checkpointer = AsyncPostgresSaver(
            conn=cast(AsyncConnectionPool[AsyncConnection[DictRow]], self.pool)
        )
        # Session-level lock on an autocommit connection, held across both setups so
        # concurrent starters (API replicas, xdist workers) run the DDL one at a time.
        async with self.pool.connection() as conn:
            await conn.execute("SELECT pg_advisory_lock(%s)", (LANGGRAPH_SETUP_LOCK_ID,))
            try:
                await self.checkpointer.setup()
                async with AsyncPostgresStore.from_conn_string(self.conninfo) as store:
                    await store.setup()
            finally:
                await conn.execute("SELECT pg_advisory_unlock(%s)", (LANGGRAPH_SETUP_LOCK_ID,))

        return self

    async def close(self) -> None:
        """Close the connection pool and cleanup resources."""
        if self.pool:
            await self.pool.close()

    def get_checkpointer(self) -> AsyncPostgresSaver:
        """Get the initialized checkpointer."""
        if not self.checkpointer:
            raise RuntimeError("Checkpointer has not been initialized. Call setup() first.")
        return self.checkpointer


@lazy_provider(
    name="checkpointer_manager",
    required_keys=[settings.POSTGRES_URL],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=True,
    warning_message="PostgreSQL URL not configured. Langraph checkpointing features will be disabled. Langraph graph persistence will not work.",
)
async def init_checkpointer_manager() -> CheckpointerManager:
    """
    Initialize the main checkpointer manager.

    Returns:
        CheckpointerManager: The main checkpointer manager
    """
    conninfo: str = settings.POSTGRES_URL
    manager = CheckpointerManager(conninfo=conninfo)
    await manager.setup()
    return manager


async def get_checkpointer_manager() -> CheckpointerManager:
    """
    Get the main checkpointer manager instance.

    Returns:
        CheckpointerManager: The main checkpointer manager
    """
    manager = await providers.aget("checkpointer_manager")
    if not manager:
        raise RuntimeError("Checkpointer manager is not available")
    return cast(CheckpointerManager, manager)
