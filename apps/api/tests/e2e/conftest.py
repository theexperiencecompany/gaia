"""E2E test fixtures for GAIA agent graph scenarios.

Uses REAL GAIA production nodes and graph builder infrastructure:
- filter_messages_node: from app.agents.core.nodes.filter_messages
- manage_system_prompts_node: from app.agents.core.nodes.manage_system_prompts
- create_agent: from app.override.langgraph_bigtool.create_agent
- State: from app.override.langgraph_bigtool.utils (the real agent state schema)

Mocks only:
- LLM: BindableToolsFakeModel (no real LLM calls; supports bind_tools())

When USE_REAL_SERVICES=1 (Dagger CI):
- Checkpointer: AsyncPostgresSaver against real Postgres
- Store: AsyncPostgresStore against real Postgres

When USE_REAL_SERVICES=0 (opt-out, local run without Docker):
- Checkpointer: MemorySaver (in-process fallback)
- Store: InMemoryStore (in-process fallback)

If filter_messages_node or manage_system_prompts_node are deleted or
mis-imported, these fixtures (and every test using them) will fail.
"""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.hooks import HookType
from tests.helpers import BindableToolsFakeModel

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "1") == "1"
_POSTGRES_URL = os.environ.get("DATABASE_URL", "")


def build_gaia_test_graph(
    fake_llm: BindableToolsFakeModel,
    tool_registry: dict[str, BaseTool],
    initial_tool_ids: list[str] | None = None,
    checkpointer: MemorySaver | None = None,
    store: InMemoryStore | None = None,
):
    """Build a real GAIA agent graph for E2E testing.

    Uses the real ``create_agent`` from ``app.override.langgraph_bigtool.create_agent``
    and wires in the real GAIA pre-model hooks:
    - filter_messages_node
    - manage_system_prompts_node

    The LLM, checkpointer, and store are replaced with in-memory test doubles
    so no external services are required.

    If ``app.agents.core.nodes.filter_messages.filter_messages_node`` or
    ``app.agents.core.nodes.manage_system_prompts.manage_system_prompts_node``
    are removed, this function will raise an ImportError and ALL e2e tests
    will fail — which is the desired sentinel behaviour.
    """
    pre_model_hooks: list[HookType] = [
        cast(HookType, filter_messages_node),
        cast(HookType, manage_system_prompts_node),
    ]

    builder = create_agent(
        llm=fake_llm,
        agent_name="test_agent",
        tool_registry=tool_registry,
        disable_retrieve_tools=True,
        initial_tool_ids=initial_tool_ids or list(tool_registry.keys()),
        middleware=None,
        pre_model_hooks=pre_model_hooks,
    )

    resolved_store = store or InMemoryStore()
    resolved_checkpointer = checkpointer or MemorySaver()
    return builder.compile(checkpointer=resolved_checkpointer, store=resolved_store)


@pytest.fixture
async def memory_saver():
    """LangGraph checkpointer.

    Returns AsyncPostgresSaver backed by real Postgres when USE_REAL_SERVICES=1
    (Dagger CI), otherwise falls back to in-process MemorySaver.
    Each test gets a fresh pool so thread-scoped state never leaks between tests.
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
        yield MemorySaver()


@pytest.fixture
async def in_memory_store():
    """LangGraph store.

    Returns AsyncPostgresStore backed by real Postgres when USE_REAL_SERVICES=1
    (Dagger CI), otherwise falls back to in-process InMemoryStore.
    """
    if _USE_REAL_SERVICES:
        from langgraph.store.postgres import AsyncPostgresStore

        async with AsyncPostgresStore.from_conn_string(_POSTGRES_URL) as store:
            await store.setup()
            yield store
    else:
        yield InMemoryStore()


@pytest.fixture
def thread_config() -> dict[str, Any]:
    """Unique thread config per test, includes user_id required by GAIA nodes."""
    return {
        "configurable": {
            "thread_id": str(uuid4()),
            "user_id": str(uuid4()),
        }
    }


def make_gaia_state(**overrides) -> dict[str, Any]:
    """Build a minimal GAIA State dict for direct node testing.

    Uses the real State fields from app.override.langgraph_bigtool.utils
    (which extends langgraph_bigtool State with the ``todos`` channel).
    """
    defaults: dict[str, Any] = {
        "messages": [],
        "selected_tool_ids": [],
        "todos": [],
    }
    defaults.update(overrides)
    return defaults


def make_mock_store() -> MagicMock:
    """Lightweight mock store for direct node testing (avoids InMemoryStore overhead)."""
    return MagicMock(spec=["asearch", "aput", "aget", "adelete"])


def make_node_config(
    user_id: str | None = None, thread_id: str | None = None
) -> dict[str, Any]:
    """Build a RunnableConfig dict suitable for GAIA node invocation."""
    return {
        "configurable": {
            "user_id": user_id or str(uuid4()),
            "thread_id": thread_id or str(uuid4()),
        }
    }
