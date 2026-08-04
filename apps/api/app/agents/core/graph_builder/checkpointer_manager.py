"""LangGraph checkpointing backed by Postgres, lazily provided.

Flow
- Requires `POSTGRES_URL` from `app.config.settings`.
- `@lazy_provider` registers a provider for the checkpointer.
- First `providers.aget(...)` creates an async pool and checkpointer, then reuses it.
- Use helpers `get_checkpointer_manager()`.

Add/change config
- Set `POSTGRES_URL` in settings; in dev it can be Optional.
- To alter pool size, adjust `CheckpointerManager` init params.
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


class CheckpointerManager:
    """
    A manager class to handle checkpointer initialization and lifecycle.
    """

    def __init__(self, conninfo: str, max_pool_size: int = 20) -> None:
        self.conninfo = conninfo
        self.max_pool_size = max_pool_size
        # Tuple rows, deliberately — see the note in setup() on the dict_row cast.
        self.pool: AsyncConnectionPool[AsyncConnection[TupleRow]] | None = None
        self.checkpointer: AsyncPostgresSaver | None = None

    async def setup(self) -> "CheckpointerManager":
        """
        Initialize the connection pool and checkpointer.
        """
        # Swarm VXLAN overlay silently drops idle TCP connections (conntrack
        # timeout ~15 min). Without keepalives + pool recycling the pool hands
        # out dead sockets and chat_stream fails with "server closed the
        # connection unexpectedly". Defence in depth:
        #   1. libpq TCP keepalives keep the NAT entry alive.
        #   2. max_idle / max_lifetime recycle in the pool.
        #   3. check=... pings each connection before handing it out.
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

        # AsyncPostgresSaver's signature demands a dict_row pool, but it sets
        # row_factory=dict_row on every cursor it opens, so the pool's own factory
        # is irrelevant to it. Keep the pool on the default tuple rows — callers
        # that borrow it (conversation cleanup, checkpoint retention) index by
        # position.
        self.checkpointer = AsyncPostgresSaver(
            conn=cast(AsyncConnectionPool[AsyncConnection[DictRow]], self.pool)
        )
        await self.checkpointer.setup()

        async with AsyncPostgresStore.from_conn_string(self.conninfo) as store:
            await store.setup()

        return self

    async def close(self) -> None:
        """
        Close the connection pool and cleanup resources.
        """
        if self.pool:
            await self.pool.close()

    def get_checkpointer(self) -> AsyncPostgresSaver:
        """
        Get the initialized checkpointer.
        """
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
