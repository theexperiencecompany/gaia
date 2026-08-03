"""Run a real compiled agent graph and assert on what it did.

``Transcript`` covers what the *client* sees. This covers what the *graph* does:
which tools the model called, which the graph actually let run, what each one
returned, and how the run terminated. Those are different questions — a tool can
be called and rejected, or run and produce nothing — and conflating them is how
"the agent called the tool" gets asserted without the tool ever executing.

Assertions go through :class:`GraphRun`, never through raw event tuples.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.store.memory import InMemoryStore

from app.agents.core.graph_builder import build_graph as _build_graph
from tests.helpers import BindableToolsFakeModel, create_fake_llm_with_tool_calls

#: The node that runs the LLM. Only its updates carry the model's own decisions.
AGENT_NODE = "agent"
#: Where a call to a tool the graph never bound is turned into a correction.
REJECT_NODE = "reject_unbound_tools"
#: Where ``retrieve_tools`` resolves names into ``selected_tool_ids``.
SELECT_NODE = "select_tools"
#: Where a real tool body executes.
TOOLS_NODE = "tools"
#: Terminal node for ``finish_task``.
FINISH_NODE = "finish_task"


class RecordingStore(InMemoryStore):
    """A real ``BaseStore`` that records every semantic search performed on it.

    Recording rather than raising: ``retrieve_tools`` degrades silently on a
    search failure (``retrieval.py`` swallows partial failures), so an exception
    raised here would be absorbed and the test would pass for the wrong reason.
    Assert on ``searches`` after the run instead.
    """

    def __init__(self) -> None:
        super().__init__()
        self.searches: list[tuple[Any, dict[str, Any]]] = []

    async def asearch(self, namespace_prefix: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        self.searches.append((namespace_prefix, kwargs))
        return await super().asearch(namespace_prefix, **kwargs)


@dataclass(frozen=True)
class NodeMessage:
    node: str
    message: BaseMessage


@dataclass
class GraphRun:
    """One graph invocation, recorded per node."""

    events: list[NodeMessage] = field(default_factory=list)
    selected: list[list[str]] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    error: BaseException | None = None

    # -- what the model asked for -------------------------------------------

    def tool_calls(self) -> list[tuple[str, dict[str, Any], str | None]]:
        """(name, args, id) for every tool call the model emitted, in order."""
        return [
            (call["name"], call.get("args", {}), call.get("id"))
            for event in self.events
            if event.node == AGENT_NODE and isinstance(event.message, AIMessage)
            for call in event.message.tool_calls or []
        ]

    def tool_names(self) -> list[str]:
        return [name for name, _, _ in self.tool_calls()]

    # -- what the graph actually did ----------------------------------------

    def nodes(self) -> list[str]:
        """Ordered, de-duplicated-in-a-row node sequence — the route taken."""
        route: list[str] = []
        for event in self.events:
            if not route or route[-1] != event.node:
                route.append(event.node)
        return route

    def results_from(self, node: str) -> list[str]:
        """Text of every ToolMessage a given node produced."""
        return [
            str(event.message.content)
            for event in self.events
            if event.node == node and isinstance(event.message, ToolMessage)
        ]

    def result_for(self, tool_name: str) -> str | None:
        """What a tool returned, joined to its call by ``tool_call_id``.

        ``None`` means the tool never produced a result — it was rejected,
        never ran, or the run ended first.
        """
        ids = {call_id for name, _, call_id in self.tool_calls() if name == tool_name}
        for event in self.events:
            message = event.message
            if isinstance(message, ToolMessage) and message.tool_call_id in ids:
                return str(message.content)
        return None

    def ran(self, tool_name: str) -> bool:
        """True only if the tool's body executed in the tools node."""
        ids = {call_id for name, _, call_id in self.tool_calls() if name == tool_name}
        return any(
            event.node in (TOOLS_NODE, FINISH_NODE)
            and isinstance(event.message, ToolMessage)
            and event.message.tool_call_id in ids
            for event in self.events
        )

    def bound_tools(self) -> list[str]:
        """Every tool id the graph bound, across all retrieval rounds."""
        seen: list[str] = []
        for batch in self.selected:
            for name in batch:
                if name not in seen:
                    seen.append(name)
        return seen

    def final_text(self) -> str:
        """The model's last message with no tool calls — the run's answer."""
        for event in reversed(self.events):
            message = event.message
            if event.node == AGENT_NODE and isinstance(message, AIMessage):
                if not message.tool_calls:
                    return str(message.content)
        return ""


@asynccontextmanager
async def executor_graph(
    script: Sequence[dict[str, Any] | str],
    store: InMemoryStore | None = None,
) -> AsyncIterator[Any]:
    """The REAL executor graph, with only the model and two I/O seams replaced.

    Everything the tests assert on is production code: ``create_agent``, the
    real tool registry, the real ``retrieve_tools`` and its binding validation,
    the real middleware stack, the real todo hooks.

    Two patches only, both narrow:

    * ``get_tools_store`` — the ChromaDB-backed vector store, swapped for a real
      ``InMemoryStore``. It must be a genuine ``BaseStore``: ``retrieve_tools``
      declares it ``Annotated[BaseStore, InjectedStore]`` and pydantic rejects a
      MagicMock. Binding by ``exact_tool_names`` never searches it, so exact
      binding stays embedding-free and deterministic.
    * ``get_checkpointer_manager`` — the Postgres checkpointer. Awaited
      unconditionally at build time even when an in-memory checkpointer is
      requested, and it raises when its provider is absent.

    Deliberately NOT patched: ``get_tool_registry`` (the tests want the real 91
    tools and their spaces) and ``create_executor_middleware`` (pure, and
    stubbing it silently removes ``spawn_subagent``).
    """
    # Registered rather than mocked: format_tool_call_entry and the retrieval
    # validator both resolve real categories through this provider singleton.
    from app.agents.tools.core.registry import init_tool_registry
    from app.core.lazy_loader import providers

    if not providers.is_initialized("tool_registry"):
        init_tool_registry()

    llm: BindableToolsFakeModel = create_fake_llm_with_tool_calls(list(script))
    with (
        patch.object(
            _build_graph, "get_tools_store", AsyncMock(return_value=store or InMemoryStore())
        ),
        patch.object(_build_graph, "get_checkpointer_manager", AsyncMock(return_value=None)),
    ):
        async with _build_graph.build_executor_graph(
            chat_llm=llm, in_memory_checkpointer=True
        ) as graph:
            yield graph


async def run_graph(
    graph: Any,
    prompt: str,
    *,
    thread_id: str = "t-1",
    user_id: str = "u-1",
    recursion_limit: int = 25,
    state: dict[str, Any] | None = None,
) -> GraphRun:
    """Drive one turn and record every node update.

    A ``GraphRecursionError`` is captured on the run rather than raised: an
    agent spinning to its limit is a behaviour worth asserting, not a test error.
    """
    from langgraph.errors import GraphRecursionError

    run = GraphRun()
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "recursion_limit": recursion_limit,
    }
    initial = (
        state if state is not None else {"messages": [HumanMessage(content=prompt)], "todos": []}
    )
    try:
        async for _mode, payload in graph.astream(initial, stream_mode=["updates"], config=config):
            for node, update in payload.items():
                if not isinstance(update, dict):
                    continue
                if "selected_tool_ids" in update:
                    run.selected.append(list(update["selected_tool_ids"]))
                if update.get("todos"):
                    run.todos = list(update["todos"])
                for message in update.get("messages", []) or []:
                    run.events.append(NodeMessage(node=node, message=message))
    except GraphRecursionError as exc:
        run.error = exc
    return run
