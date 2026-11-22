"""Both real graphs on the real checkpointer, with only the models and the narrow I/O seams doubled."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models import BaseChatModel
from langgraph.store.memory import InMemoryStore

from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.constants.memory import ReconcileOutcome
from app.core.websocket_manager import websocket_manager
from app.memory.ingestion import RetainedMemory
from app.models.integration_models import UserIntegrationCapabilities
from app.models.memory_models import MemoryEntry
from app.services.conversation.composition import build_runtime_ports
from app.services.conversation.runtime import install_runtime_ports
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.task_index import task_search_index

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"
RESET_MODULE = "app.services.checkpoint_thread_reset"
CONVERSATIONS_MODULE = "app.services.conversation_service"


@dataclass
class LiveGraphs:
    """What the open graphs pushed to the user's clients, in order."""

    pushed: list[dict[str, Any]] = field(default_factory=list)

    def pushed_of(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.pushed if event.get("type") == kind]


@contextmanager
def offline_todo_seams() -> Iterator[None]:
    """Double a todo's ChromaDB embeddings and VFS projection, and serve the task index in-process."""
    with (
        task_search_index(),
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
    ):
        yield


@asynccontextmanager
async def live_graphs(
    checkpointer: CheckpointerManager, *, executor_model: BaseChatModel, comms_model: BaseChatModel
) -> AsyncIterator[LiveGraphs]:
    """Open the executor and comms graphs as the app runs them, each on its scripted model."""
    opened = LiveGraphs()

    async def record_push(user_id: str, message: dict[str, Any]) -> None:
        opened.pushed.append(message)

    memory = MagicMock()
    memory.retain_single = AsyncMock(
        return_value=RetainedMemory(
            entry=MemoryEntry(id="mem-live-stack", content="m", category_path="general"),
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
                build_graph_module.build_executor_graph(chat_llm=executor_model)
            ),
            "comms_agent": await stack.enter_async_context(
                build_graph_module.build_comms_graph(chat_llm=comms_model)
            ),
        }
        stack.enter_context(
            patch.object(
                GraphManager,
                "get_graph",
                new=AsyncMock(side_effect=lambda name="default_graph": graphs[name]),
            )
        )
        # The history fold's model is the one production model the ports build themselves.
        stack.enter_context(
            patch("app.services.conversation.composition.init_llm", return_value=comms_model)
        )
        install_runtime_ports(build_runtime_ports())
        try:
            yield opened
        finally:
            # Inside the patches: nothing a run left going may reach the real services.
            await drain_background_runs()
