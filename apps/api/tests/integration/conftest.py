"""Integration test fixtures shared across all integration test modules."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from typing_extensions import Annotated

from app.db.redis import redis_cache
from tests.factories import make_config, make_user

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "1") == "1"
_POSTGRES_URL = os.environ.get("DATABASE_URL", "")
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class SimpleState(BaseModel):
    """Minimal graph state for integration tests."""

    messages: Annotated[list, add_messages] = Field(default_factory=list)
    route: str = ""


@pytest.fixture
async def memory_saver():
    """LangGraph checkpointer.

    Returns AsyncPostgresSaver backed by real Postgres when USE_REAL_SERVICES=1
    (Dagger CI), otherwise falls back to in-process MemorySaver.
    """
    if _USE_REAL_SERVICES:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo=_POSTGRES_URL,
            min_size=1,
            max_size=3,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        await pool.open(wait=True, timeout=30)
        checkpointer = AsyncPostgresSaver(conn=pool)  # type: ignore[call-arg]
        await checkpointer.setup()
        yield checkpointer
        await pool.close()
    else:
        from langgraph.checkpoint.memory import MemorySaver

        yield MemorySaver()


@pytest.fixture
def thread_config() -> dict:
    """Provide a unique thread_id config per test."""
    return {"configurable": {"thread_id": str(uuid4())}}


@pytest.fixture
def compiled_graph(memory_saver):
    """Build a simple two-node graph (echo node) compiled with a checkpointer.

    Uses AsyncPostgresSaver when USE_REAL_SERVICES=1, otherwise MemorySaver.
    The graph accepts messages in state, echoes the last human message
    content prefixed with 'Echo: ', and terminates.
    """

    def echo_node(state: SimpleState) -> dict[str, Any]:
        last_msg = state.messages[-1] if state.messages else None
        content = last_msg.content if last_msg else "empty"
        return {"messages": [AIMessage(content=f"Echo: {content}")]}

    builder = StateGraph(SimpleState)
    builder.add_node("echo", echo_node)
    builder.set_entry_point("echo")
    builder.add_edge("echo", END)

    return builder.compile(checkpointer=memory_saver)


@pytest.fixture
def mock_providers():
    """Mock the global lazy provider registry to avoid real service init."""
    with patch("app.core.lazy_loader.providers") as mock_registry:
        mock_registry.get = MagicMock(return_value=None)
        mock_registry.aget = AsyncMock(return_value=None)
        mock_registry.register = MagicMock()
        mock_registry.is_available = MagicMock(return_value=False)
        mock_registry.is_initialized = MagicMock(return_value=False)
        yield mock_registry


@pytest.fixture
def sample_user() -> dict:
    return make_user()


@pytest.fixture
def sample_config() -> dict:
    return make_config()


# ---------------------------------------------------------------------------
# Real Redis fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def real_redis(monkeypatch):
    """Real Redis connection, patched into the app's redis_cache singleton.

    When USE_REAL_SERVICES=1 (Dagger CI), Redis is guaranteed to be running
    and connection failures are fatal. Otherwise, the test is skipped if
    Redis is not reachable so local runs without Docker still work.
    """
    client = Redis.from_url(_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except (ConnectionError, OSError, Exception):
        await client.aclose()
        if _USE_REAL_SERVICES:
            raise  # In CI with real services, Redis must be running
        pytest.skip("Redis not available at " + _REDIS_URL)

    monkeypatch.setattr(redis_cache, "redis", client)

    yield client

    await client.flushdb()
    await client.aclose()
