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
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
import pytest

from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.core.lazy_loader import providers
from app.override.langgraph_bigtool.create_agent import (
    AgentConfig,
    HookConfig,
    ToolRetrievalConfig,
    create_agent,
)
from app.override.langgraph_bigtool.hooks import HookType
from tests.helpers import BindableToolsFakeModel, pg_advisory_lock, skip_items_without_real_services
from tests.integration.real.db_fixtures import (
    hil_approvals_collection,
    mongo_db,
    mongodb_url,
    postgres_url,
    real_redis,
    redis_url,
)

# Imported to register the fixtures for this directory; `__all__` marks them as
# a deliberate re-export (same pattern as tests/integration/real/conftest.py).
__all__ = [
    "hil_approvals_collection",
    "mongo_db",
    "mongodb_url",
    "postgres_url",
    "real_redis",
    "redis_url",
]

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "0") == "1"
_POSTGRES_URL = os.environ.get("DATABASE_URL", "")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """HIL e2e files need real Mongo/Redis; skip them at collection otherwise.

    These are the only e2e files that request the real-infra fixtures from
    tests/integration/real/db_fixtures (verified by grep). Everything else in
    this directory runs hermetic with MemorySaver + fake LLM.
    """

    real_infra_files = {"test_hil_barrier_e2e.py", "test_hil_spawn_e2e.py"}
    dir_root = Path(__file__).resolve().parent
    skip_items_without_real_services(
        [
            item
            for item in items
            if item.path.is_relative_to(dir_root) and item.path.name in real_infra_files
        ],
        reason="HIL e2e requires USE_REAL_SERVICES=1 (real Mongo/Redis)",
    )


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
        tool_registry=tool_registry,
        tools_config=ToolRetrievalConfig(
            disable_retrieve_tools=True,
            initial_tool_ids=initial_tool_ids or list(tool_registry.keys()),
        ),
        hooks_config=HookConfig(pre_model_hooks=pre_model_hooks),
        agent_config=AgentConfig(agent_name="test_agent"),
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
        checkpointer = AsyncPostgresSaver(conn=pool)
        async with pg_advisory_lock(_POSTGRES_URL):
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
            async with pg_advisory_lock(_POSTGRES_URL):
                await store.setup()
            yield store
    else:
        yield InMemoryStore()


@pytest.fixture
def real_tool_registry():
    """Register the real global ToolRegistry provider.

    ``format_tool_call_entry`` resolves every streamed tool call's category
    through ``get_tool_registry()``; without the provider registered that lookup
    raises, so any test asserting on a ``tool_data`` frame needs this. Setup is
    in-process only (``_initialize_categories`` imports the tool modules and
    indexes them by name) — no ChromaDB, no network.

    The provider registry is a process-wide singleton with no reset between
    tests, so registration happens once and the built instance is then reused
    exactly as it is in a running app.
    """
    from app.agents.tools.core.registry import init_tool_registry

    if not providers.is_initialized("tool_registry"):
        init_tool_registry()
    return providers


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


def make_node_config(user_id: str | None = None, thread_id: str | None = None) -> dict[str, Any]:
    """Build a RunnableConfig dict suitable for GAIA node invocation."""
    return {
        "configurable": {
            "user_id": user_id or str(uuid4()),
            "thread_id": thread_id or str(uuid4()),
        }
    }
