"""E2E test fixtures for GAIA agent graph scenarios.

Uses real GAIA nodes (filter_messages_node, manage_system_prompts_node) and the
real create_agent/State from app.override.langgraph_bigtool — only the LLM
(BindableToolsFakeModel) is mocked. USE_REAL_SERVICES=1 (CI) backs the
checkpointer/store with AsyncPostgresSaver/AsyncPostgresStore against real
Postgres; USE_REAL_SERVICES=0 falls back to MemorySaver/InMemoryStore.

If filter_messages_node or manage_system_prompts_node are deleted or
mis-imported, every fixture here — and every test using them — fails.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.constants.memory import ReconcileOutcome
from app.core.lazy_loader import providers
from app.core.websocket_manager import websocket_manager
from app.db.mongodb import indexes
from app.memory.ingestion import RetainedMemory
from app.models.integration_models import UserIntegrationCapabilities
from app.models.memory_models import MemoryEntry
from app.models.user_models import AuthenticatedUser
from app.override.langgraph_bigtool.agent_config import (
    AgentConfig,
    HookConfig,
    ToolRetrievalConfig,
)
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.hooks import HookType
from app.services.conversation.composition import build_runtime_ports
from app.services.conversation.runtime import install_runtime_ports
from tests.conftest import FAKE_USER
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import StreamingScriptedModel, streaming_model
from tests.e2e._harness.step_stack import (
    CONVERSATIONS_MODULE,
    FOLLOW_UP_NODE,
    OWNED_COLLECTIONS,
    RESET_MODULE,
    OpenStack,
    Stack,
)
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
    """Skip the e2e files that need real Mongo/Redis at collection otherwise.

    These are the only e2e files that request the real-infra fixtures from
    tests/integration/real/db_fixtures (verified by grep): the HIL journeys and
    the trigger-dispatch fan-out. Everything else in this directory runs hermetic
    with MemorySaver + fake LLM.
    """

    real_infra_files = {
        "test_hil_barrier_e2e.py",
        "test_hil_spawn_e2e.py",
        "test_todo_trigger_dispatch_e2e.py",
        "test_tracked_todo_chat_e2e.py",
    }
    dir_root = Path(__file__).resolve().parent
    skip_items_without_real_services(
        [
            item
            for item in items
            if item.path.is_relative_to(dir_root) and item.path.name in real_infra_files
        ],
        reason="requires USE_REAL_SERVICES=1 (real Mongo/Redis)",
    )


def build_gaia_test_graph(
    fake_llm: BindableToolsFakeModel,
    tool_registry: dict[str, BaseTool],
    initial_tool_ids: list[str] | None = None,
    checkpointer: MemorySaver | None = None,
    store: InMemoryStore | None = None,
):
    """Build a real GAIA agent graph: real create_agent and pre-model hooks, fake LLM/checkpointer/store.

    Deleting filter_messages_node or manage_system_prompts_node raises ImportError
    here — the intended sentinel for every e2e test.
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
    (CI), otherwise falls back to in-process MemorySaver.
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
    (CI), otherwise falls back to in-process InMemoryStore.
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
    """Register the real global ToolRegistry provider (in-process only, no ChromaDB/network).

    format_tool_call_entry needs get_tool_registry() registered to resolve a
    streamed tool call's category. The provider registry is a process-wide
    singleton with no reset between tests, so registration happens once and is
    reused exactly as in a running app.
    """
    from app.agents.tools.core.registry import init_tool_registry

    if not providers.is_initialized("tool_registry"):
        init_tool_registry()
    return providers


@pytest.fixture
def thread_config() -> dict[str, Any]:
    """Build a unique thread config per test, including the user_id GAIA nodes require."""
    return {
        "configurable": {
            "thread_id": str(uuid4()),
            "user_id": str(ObjectId()),
        }
    }


def make_gaia_state(**overrides) -> dict[str, Any]:
    """Build a minimal GAIA State dict for direct node testing.

    Uses the real State fields from app.override.langgraph_bigtool.utils
    (which extends langgraph_bigtool State with the todos channel).
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


@pytest.fixture
async def checkpointer(postgres_url: str) -> AsyncIterator[CheckpointerManager]:
    """Yield the app's own checkpointer manager on the real Postgres, as every graph and the reset reach it."""
    manager = await CheckpointerManager(conninfo=postgres_url, max_pool_size=4).setup()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
async def owner(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[AuthenticatedUser]:
    """Yield the HTTP client's user as a real Mongo user, with nothing of theirs left from a previous run."""
    user_id = FAKE_USER.user_id
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})
    await mongo_db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {"email": FAKE_USER.email, "name": FAKE_USER.name, "timezone": "UTC"},
            "$unset": {"hil_preferences": ""},
        },
        upsert=True,
    )
    yield FAKE_USER
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})


@pytest.fixture
async def conversation_indexes(mongo_db: AsyncIOMotorDatabase) -> None:
    """Create the one-chat-per-todo index startup ships, from its shipped spec, on this test database.

    Dropped first: the test database outlives a run, and an index left by an older
    spec would otherwise stand in for the one under test.
    """
    collection = mongo_db["conversations"]
    for spec in await collection.list_indexes().to_list(None):
        if list(spec["key"].items()) == indexes.CONVERSATION_TODO_BINDING_KEYS:
            await collection.drop_index(spec["name"])
    await collection.create_index(
        indexes.CONVERSATION_TODO_BINDING_KEYS, **indexes.CONVERSATION_TODO_BINDING_OPTIONS
    )
    for keys, options in indexes.CONVERSATION_ENTRY_INDEXES:
        await mongo_db[CONVERSATION_ENTRIES_COLLECTION].create_index(keys, **options)


@pytest.fixture
def offline_todo_seams() -> Iterator[None]:
    """Double the todo's ChromaDB embeddings and VFS projection: off this path, never asserted on."""
    with (
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
    ):
        yield


@pytest.fixture
def open_stack(
    checkpointer: CheckpointerManager,
    real_redis: Any,
    real_tool_registry: Any,
    owner: AuthenticatedUser,
    conversation_indexes: None,
    offline_todo_seams: None,
) -> OpenStack:
    """Open both real graphs on the real checkpointer, each tier's model scripted by the test."""

    @asynccontextmanager
    async def opened(
        *,
        executor: Sequence[Any] | StreamingScriptedModel,
        comms: Sequence[Any] = (),
    ) -> AsyncIterator[Stack]:
        built = Stack(
            checkpointer=checkpointer,
            executor_model=executor
            if isinstance(executor, StreamingScriptedModel)
            else streaming_model(executor),
            comms_model=streaming_model(comms),
        )

        async def record_push(_user_id: str, event: dict[str, Any]) -> None:
            built.pushed.append(event)

        memory = MagicMock()
        memory.retain_single = AsyncMock(
            return_value=RetainedMemory(
                entry=MemoryEntry(id="mem-todo-chat", content="m", category_path="general"),
                outcome=ReconcileOutcome.NEW,
            )
        )
        memory.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))
        memory.retain = AsyncMock()
        the_checkpointer = AsyncMock(return_value=checkpointer)

        async with AsyncExitStack() as stack:
            for patcher in (
                patch.object(
                    build_graph_module, "get_tools_store", AsyncMock(return_value=InMemoryStore())
                ),
                patch.object(build_graph_module, "get_checkpointer_manager", the_checkpointer),
                patch(f"{RESET_MODULE}.get_checkpointer_manager", the_checkpointer),
                patch(f"{CONVERSATIONS_MODULE}.get_checkpointer_manager", the_checkpointer),
                patch(
                    f"{FOLLOW_UP_NODE}.ainvoke_structured",
                    new=AsyncMock(return_value=FollowUpActions(actions=[])),
                ),
                patch(
                    f"{FOLLOW_UP_NODE}.get_user_integration_capabilities",
                    new=AsyncMock(return_value=UserIntegrationCapabilities(tool_names=[])),
                ),
                patch("app.agents.tools.memory_tools.memory_engine", memory),
                patch("app.agents.core.nodes.memory_node.memory_engine", memory),
                patch.object(websocket_manager, "broadcast_to_user", new=record_push),
            ):
                stack.enter_context(patcher)
            graphs = {
                "executor_agent": await stack.enter_async_context(
                    build_graph_module.build_executor_graph(chat_llm=built.executor_model)
                ),
                "comms_agent": await stack.enter_async_context(
                    build_graph_module.build_comms_graph(chat_llm=built.comms_model)
                ),
            }
            stack.enter_context(
                patch.object(
                    GraphManager,
                    "get_graph",
                    new=AsyncMock(side_effect=lambda name="default_graph": graphs[name]),
                )
            )
            install_runtime_ports(build_runtime_ports())
            try:
                yield built
            finally:
                # Inside the patches: nothing a run left going may reach the real services.
                await drain_background_runs()

    return opened
