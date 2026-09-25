"""Run a real compiled agent graph and assert on what it did.

Transcript covers what the *client* sees. This covers what the *graph* does:
which tools the model called, which the graph actually let run, what each one
returned, and how the run terminated. Those are different questions — a tool can
be called and rejected, or run and produce nothing — and conflating them is how
"the agent called the tool" gets asserted without the tool ever executing.

Assertions go through :class:GraphRun, never through raw event tuples.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langgraph.store.memory import InMemoryStore
from pydantic import PrivateAttr

from app.agents.core.graph_builder import build_graph as _build_graph
from tests.helpers import BindableToolsFakeModel

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
#: Where the completion guard sends a run back for one more pass instead of
#: letting it end on demonstrably unfinished work.
NUDGE_NODE = "nudge_continue"

#: The memory engine double a comms graph was built with, so a test can assert
#: passive ingestion actually ran.
_MEMORY_DOUBLES: dict[int, Any] = {}

#: Compiled graphs are third-party objects that reject stray attributes, so the
#: harness keeps the scripted model beside the graph rather than on it. Lets
#: ``run_graph`` surface prompts without every test having to thread the model.
_SCRIPTED_MODELS: dict[int, RecordingFakeModel] = {}


class RecordingStore(InMemoryStore):
    """A real BaseStore that records every semantic search performed on it.

    Recording rather than raising: retrieve_tools degrades silently on a
    search failure (retrieval.py swallows partial failures), so an exception
    raised here would be absorbed and the test would pass for the wrong reason.
    Assert on searches after the run instead.
    """

    def __init__(self) -> None:
        super().__init__()
        self.searches: list[tuple[Any, dict[str, Any]]] = []

    async def asearch(self, namespace_prefix: Any, **kwargs: Any) -> Any:
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
    #: The tool names actually bound to the model on each call — what the
    #: provider receives as function declarations, as opposed to
    #: ``selected_tool_ids``, which is only what retrieval decided.
    bound: list[list[str]] = field(default_factory=list)
    #: The message list handed to the model on each call. Pre-model hooks rewrite
    #: it on the way in and that rewrite never reaches the checkpoint, so this is
    #: the only place a hook's effect is observable.
    prompts: list[list[BaseMessage]] = field(default_factory=list)
    #: Every node that emitted an update, in order, including message-less
    #: nodes (e.g. end_graph_hooks); nodes() covers only the message-bearing route.
    visited: list[str] = field(default_factory=list)
    error: BaseException | None = None

    def last_prompt(self) -> list[BaseMessage]:
        return self.prompts[-1] if self.prompts else []

    def model_bound_tools(self) -> list[str]:
        """Tool names bound on the most recent model call."""
        return self.bound[-1] if self.bound else []

    def system_slot(self, kwarg: str) -> str | None:
        """Text of the system message a pre-model hook tagged with kwarg."""
        for message in self.last_prompt():
            if isinstance(message, SystemMessage) and message.additional_kwargs.get(kwarg):
                return str(message.content)
        return None

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
        """Return what a tool returned, joined to its call by tool_call_id, or None if it never produced a result."""
        ids = {call_id for name, _, call_id in self.tool_calls() if name == tool_name}
        for event in self.events:
            message = event.message
            if isinstance(message, ToolMessage) and message.tool_call_id in ids:
                return str(message.content)
        return None

    def ran(self, tool_name: str) -> bool:
        """Return True only if the tool's body executed in the tools node."""
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
        """Return the model's last message with no tool calls — the run's answer."""
        for event in reversed(self.events):
            message = event.message
            if event.node == AGENT_NODE and isinstance(message, AIMessage):
                if not message.tool_calls:
                    return str(message.content)
        return ""


class RecordingFakeModel(BindableToolsFakeModel):
    """A scripted model that also remembers what it was shown.

    Pre-model hooks (todo context, system-prompt management, message filtering)
    rewrite the message list on its way to the model and that rewrite is
    ephemeral — it never lands in the checkpoint. So the only way to assert on a
    hook's effect is to record the prompt the model actually received.

    last_chat_messages / chat_messages_log are the public recording API
    (LlamaIndex's MockLLMWithChatMemoryOfLastCall namesake); prompts is
    the same log, read by :func:run_graph.
    """

    _prompts: list[list[BaseMessage]] = PrivateAttr(default_factory=list)
    _bound: list[list[str]] = PrivateAttr(default_factory=list)

    @property
    def prompts(self) -> list[list[BaseMessage]]:
        return self._prompts

    @property
    def bound(self) -> list[list[str]]:
        return self._bound

    @property
    def last_chat_messages(self) -> list[BaseMessage] | None:
        """The message list of the most recent model call, None before the first."""
        return self._prompts[-1] if self._prompts else None

    @property
    def chat_messages_log(self) -> list[list[BaseMessage]]:
        """Every message list handed to the model, in call order."""
        return list(self._prompts)

    def bind_tools(self, tools: Any, **kwargs: Any) -> RecordingFakeModel:
        """Record what the model was actually handed.

        The base fake returns self and throws the tool list away, which
        makes every binding assertion unfalsifiable: without this, only
        selected_tool_ids (what retrieval decided) is observable, not what was bound.
        """
        self._bound.append([getattr(tool, "name", str(tool)) for tool in tools])
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self._prompts.append(list(messages))
        return super()._generate(messages, *args, **kwargs)

    async def _agenerate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        # Dispatch through ``self._generate``, not ``super()._generate``: a
        # subclass overriding the response (e.g. CallAllToolsModel) must see the
        # override on the async path too, or its script is silently bypassed.
        return self._generate(messages, *args, **kwargs)


#: What a scripted hand-off sends for call_executor's required
#: acceptance_criteria, filled here so one schema change doesn't rewrite fifty scripts by hand.
SCRIPTED_ACCEPTANCE_CRITERIA = ["scripted e2e hand-off"]


#: One scripted tool-call payload, shared by every helper that models the
#: ``name``/``args``/``id`` triple LangGraph puts on AIMessage.tool_calls.
class ToolCall(TypedDict):
    name: str
    args: dict[str, Any]
    id: str


def call(name: str, args: dict[str, Any] | None = None, call_id: str = "c1") -> ToolCall:
    """One scripted tool call.

    Lived in four e2e modules as identical copies until acceptance_criteria
    became required and every one of them broke at once.
    """
    call_args = dict(args or {})
    if name == "call_executor" and "acceptance_criteria" not in call_args:
        call_args["acceptance_criteria"] = list(SCRIPTED_ACCEPTANCE_CRITERIA)
    return {"name": name, "args": call_args, "id": call_id}


def scripted_model(script: Sequence[Any]) -> RecordingFakeModel:
    """Build a fake model that replays script, one entry per model call.

    Four entry shapes: str (plain reply), dict (one tool call), list[dict]
    (several tool calls in ONE turn, the only way to reach parallel-call
    routing), or BaseMessage (used as-is).
    """
    responses: list[BaseMessage] = []
    for item in script:
        if isinstance(item, BaseMessage):
            responses.append(item)
        elif isinstance(item, dict):
            responses.append(AIMessage(content="", tool_calls=[item]))
        elif isinstance(item, list):
            responses.append(AIMessage(content="", tool_calls=list(item)))
        else:
            responses.append(AIMessage(content=str(item)))
    return RecordingFakeModel(responses=responses, profile={"max_input_tokens": 1_000_000})


def call_all_tools_response_generator(
    messages: list[BaseMessage], tools: list[BaseTool]
) -> AIMessage:
    """Emit one tool call per bound tool, then a plain completion reply once a result is seen (or the graph would loop forever)."""
    if any(isinstance(message, ToolMessage) for message in messages):
        return AIMessage(content="Tool calls complete.")
    if not tools:
        return AIMessage(content="No tools available.")
    tool_calls: list[dict[str, Any]] = []
    for tool in tools:
        args: dict[str, Any] = {}
        schema = getattr(tool, "args_schema", None)
        if schema is not None:
            for field_name, field_info in schema.model_fields.items():
                if not field_info.is_required():
                    args[field_name] = field_info.get_default(call_default_factory=True)
        tool_calls.append({"name": tool.name, "args": args, "id": f"call-all-{uuid4().hex}"})
    return AIMessage(content="", tool_calls=tool_calls)


class CallAllToolsModel(RecordingFakeModel):
    """A scripted model that calls EVERY bound tool on its first turn.

    responses is accepted so construction stays drop-in with
    :func:scripted_model, but never consumed: every call is auto-generated.
    After the results are back the generator replies "Tool calls complete.",
    so a run exercises every tool the graph bound and still terminates.
    """

    _bound_tools: list[BaseTool] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> CallAllToolsModel:
        super().bind_tools(tools, **kwargs)
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self._prompts.append(list(messages))
        response = call_all_tools_response_generator(messages, self._bound_tools)
        return ChatResult(generations=[ChatGeneration(message=response)])


@asynccontextmanager
async def executor_graph(
    script: Sequence[dict[str, Any] | str],
    store: InMemoryStore | None = None,
    model: RecordingFakeModel | None = None,
) -> AsyncIterator[Any]:
    """Build the REAL executor graph, with only the model and two I/O seams replaced.

    Patches only get_tools_store (retrieve_tools declares it InjectedStore, so pydantic
    rejects a MagicMock; exact_tool_names never searches it) and get_checkpointer_manager.
    Deliberately NOT patched: get_tool_registry, and create_executor_middleware, whose stub
    would silently drop spawn_subagent. model overrides script when given.
    """
    # Registered rather than mocked: format_tool_call_entry and the retrieval
    # validator both resolve real categories through this provider singleton.
    from app.agents.tools.core.registry import init_tool_registry
    from app.core.lazy_loader import providers

    if not providers.is_initialized("tool_registry"):
        init_tool_registry()

    llm = model if model is not None else scripted_model(script)
    with (
        patch.object(
            _build_graph, "get_tools_store", AsyncMock(return_value=store or InMemoryStore())
        ),
        patch.object(_build_graph, "get_checkpointer_manager", AsyncMock(return_value=None)),
    ):
        async with _build_graph.build_executor_graph(
            chat_llm=llm, in_memory_checkpointer=True
        ) as graph:
            _SCRIPTED_MODELS[id(graph)] = llm
            try:
                yield graph
            finally:
                _SCRIPTED_MODELS.pop(id(graph), None)


@asynccontextmanager
async def comms_graph(
    script: Sequence[Any],
    store: InMemoryStore | None = None,
    model: RecordingFakeModel | None = None,
    checkpointer_manager: Any | None = None,
) -> AsyncIterator[Any]:
    """Build the REAL comms graph, with only the model and the external edges replaced.

    Three tools, the pre-model hooks and both end-graph hooks are the real
    comms front door; only the end hooks' external edges (follow-up's LLM
    call, memory ingestion) are doubled. model overrides script when given.
    """
    from app.agents.core.nodes.follow_up_actions_node import FollowUpActions

    # Patched by path, not by attribute: ``app.agents.core.nodes`` re-exports the
    # NODE FUNCTION under this name, so importing it gives a function, not the
    # module the collaborators live on.
    node_module = "app.agents.core.nodes.follow_up_actions_node"

    import fakeredis.aioredis

    from app.constants.memory import ReconcileOutcome
    from app.db.redis import redis_cache
    from app.memory.ingestion import RetainedMemory
    from app.models.memory_models import MemoryEntry

    llm = model if model is not None else scripted_model(script)
    # Typed to the engine's real return shape, not a bare MagicMock: the memory
    # tools read `.entry.category_path` and `.outcome` off it, so a loose double
    # turns a tool result into an AttributeError string the test then asserts on.
    memory = MagicMock()
    memory.retain_single = AsyncMock(
        return_value=RetainedMemory(
            entry=MemoryEntry(id="mem-test-001", content="test memory", category_path="general"),
            outcome=ReconcileOutcome.NEW,
        )
    )
    memory.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))

    # A real (fake) Redis, not none: call_executor takes a busy lock through
    # it and executor_status_hook reads it every turn, so without one every
    # comms test's delegation silently returns a ConnectionError string.
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    with (
        patch.object(redis_cache, "redis", redis_client),
        patch.object(
            _build_graph, "get_tools_store", AsyncMock(return_value=store or InMemoryStore())
        ),
        patch.object(
            _build_graph,
            "get_checkpointer_manager",
            AsyncMock(return_value=checkpointer_manager),
        ),
        patch(
            f"{node_module}.ainvoke_structured",
            new=AsyncMock(return_value=FollowUpActions(actions=[])),
        ),
        patch(
            f"{node_module}.get_user_integration_capabilities",
            new=AsyncMock(return_value={"tool_names": []}),
        ),
        patch(f"{node_module}.get_stream_writer", return_value=lambda _: None),
        patch("app.agents.tools.memory_tools.memory_engine", memory),
        patch(
            "app.agents.core.background.executor_runner.prepare_executor_execution",
            new=AsyncMock(return_value=(None, "executor not available in tests")),
        ),
    ):
        async with _build_graph.build_comms_graph(
            chat_llm=llm, in_memory_checkpointer=checkpointer_manager is None
        ) as graph:
            _SCRIPTED_MODELS[id(graph)] = llm
            _MEMORY_DOUBLES[id(graph)] = memory
            try:
                yield graph
            finally:
                _SCRIPTED_MODELS.pop(id(graph), None)
                _MEMORY_DOUBLES.pop(id(graph), None)


def memory_engine_of(graph: Any) -> Any:
    """Return the memory double a comms graph was built with."""
    return _MEMORY_DOUBLES[id(graph)]


def scripted_model_of(graph: Any) -> RecordingFakeModel:
    """Return the scripted model a graph was built with — prompts, bindings, memory.

    Only valid inside the graph's async with block: the harness unregisters
    the model when the graph is torn down.
    """
    return _SCRIPTED_MODELS[id(graph)]


async def run_graph(
    graph: Any,
    prompt: str,
    *,
    thread_id: str = "t-1",
    user_id: str = "u-1",
    recursion_limit: int = 25,
    state: dict[str, Any] | None = None,
    **configurable: Any,
) -> GraphRun:
    """Drive one turn and record every node update.

    A GraphRecursionError is captured on the run rather than raised: an
    agent spinning to its limit is a behaviour worth asserting, not a test error.
    Any further keyword is a configurable key, for the identity a tool reads
    beyond thread and user (stream_id, conversation_id, the run's provenance).
    """
    from langgraph.errors import GraphRecursionError

    run = GraphRun()
    # user_id goes in BOTH places, as build_agent_config does: the graph reads
    # `configurable` but every @tool reads `metadata["user_id"]`, so setting
    # only one makes tools silently return "user_id not found" as if they ran.
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id, **configurable},
        "metadata": {"user_id": user_id},
        "recursion_limit": recursion_limit,
    }
    initial = (
        state if state is not None else {"messages": [HumanMessage(content=prompt)], "todos": []}
    )
    try:
        async for _mode, payload in graph.astream(initial, stream_mode=["updates"], config=config):
            for node, update in payload.items():
                if not run.visited or run.visited[-1] != node:
                    run.visited.append(node)
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

    model = _SCRIPTED_MODELS.get(id(graph))
    if model is not None:
        run.prompts = list(model.prompts)
        run.bound = list(model.bound)

    # `todos` is written by a tool returning a Command, which does not always
    # surface as a node update. The checkpoint is the authoritative copy of the
    # channel, so read it from there rather than from the event stream.
    snapshot = await graph.aget_state(config)
    values = snapshot.values if snapshot else {}
    if isinstance(values, dict) and isinstance(values.get("todos"), list):
        run.todos = list(values["todos"])
    return run
