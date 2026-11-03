"""Unit tests for DynamicToolNode's one execution path.

Every call runs through LangGraph's own ToolNode execution, wrapped by the
middleware chain, the argument check and the timeout — whatever the tool injects
or returns.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt import InjectedState, InjectedStore
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from pydantic import BaseModel
import pytest

from app.agents.middleware.executor import MIDDLEWARE_FAILURE_TEMPLATE, MiddlewareExecutor
from app.agents.middleware.factory import ContextOptions, create_middleware_stack
from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import (
    AnalyticsContext,
    analytics_context,
    current_analytics_context,
    worker_context,
)

NODE = "app.override.langgraph_bigtool.dynamic_tool_node"

pytestmark = pytest.mark.unit


class _Passthrough(AgentMiddleware):
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return await handler(request)


@tool
async def hangs(query: str) -> str:
    """Never answer."""
    await asyncio.sleep(5)
    return query


@tool
async def breaks(query: str) -> str:
    """Fail on every call."""
    raise ValueError(f"bad {query}")


@tool("execute")
async def proxy(tool_name: str, data: dict[str, Any]) -> str:
    """Stand in for the execute proxy: slow enough to outlive a shrunk bound."""
    await asyncio.sleep(0.1)
    return f"ran {tool_name}"


@tool
async def files_a_ticket(
    title: str, labels: list[int], store: Annotated[BaseStore, InjectedStore()]
) -> str:
    """File a ticket; never reached with invalid arguments."""
    raise AssertionError("the tool ran with invalid arguments")


def _real_node(*tools: Any) -> DynamicToolNode:
    registry = {t.name: t for t in tools}
    return DynamicToolNode(registry, middleware_executor=MiddlewareExecutor([_Passthrough()]))


def _one_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    call = {"name": name, "args": args, "id": "call_1", "type": "tool_call"}
    return {"messages": [AIMessage(content="", tool_calls=[call])]}


async def _run(node: DynamicToolNode, name: str, args: dict[str, Any]) -> ToolMessage:
    result = await node._afunc(_one_call(name, args), {}, Runtime(store=InMemoryStore()))
    (message,) = result["messages"]
    return message


class _Recorder(AgentMiddleware):
    """Record each request the chain hands on, then pass it through."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[ToolCallRequest] = []

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        self.requests.append(request)
        return await handler(request)


class _SwapsInTool(AgentMiddleware):
    """Hand the call to a tool the node never registered, as a wrap_tool_call may."""

    def __init__(self, replacement: Any) -> None:
        super().__init__()
        self.replacement = replacement

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return await handler(request.override(tool=self.replacement))


class TestToolsBoundAfterCompilation:
    """The registry is live: a tool added after the node was built runs, and is checked, like any other."""

    async def test_a_tool_added_to_the_registry_later_runs(self) -> None:
        @tool
        def added_later(query: str) -> str:
            """Answer late."""
            return f"late {query}"

        registry: dict[str, Any] = {}
        node = DynamicToolNode(registry, middleware_executor=MiddlewareExecutor([_Passthrough()]))
        registry["added_later"] = added_later

        message = await _run(node, "added_later", {"query": "q"})

        assert message.content == "late q"

    async def test_a_later_tools_injected_arguments_are_never_blamed_on_the_model(self) -> None:
        @tool
        def counts(limit: int, todos: Annotated[list[int], InjectedState("todos")]) -> str:
            """Count todos up to a limit."""
            raise AssertionError("the tool ran with invalid arguments")

        registry: dict[str, Any] = {}
        node = DynamicToolNode(registry, middleware_executor=MiddlewareExecutor([_Passthrough()]))
        registry["counts"] = counts
        state = {**_one_call("counts", {"limit": "many"}), "todos": ["not-an-int"]}

        result = await node._afunc(state, {}, Runtime())

        (message,) = result["messages"]
        _, *fields, _ = message.text.splitlines()
        assert fields == [
            "limit: Input should be a valid integer, unable to parse string as an integer"
        ]

    async def test_a_tool_a_middleware_swaps_in_gets_its_injected_arguments(self) -> None:
        @tool
        async def keeps_notes(note: str, store: Annotated[BaseStore, InjectedStore()]) -> str:
            """Store a note."""
            return f"kept {note}"

        node = DynamicToolNode(
            {}, middleware_executor=MiddlewareExecutor([_SwapsInTool(keeps_notes)])
        )

        message = await _run(node, "keeps_notes", {"note": "n"})

        assert message.content == "kept n"


class TestEveryCallTakesTheOnePath:
    """Injection, Commands and interrupts all come back through the middleware chain."""

    async def test_a_state_injected_tool_runs_inside_the_chain_with_the_graph_state(self) -> None:
        @tool
        def counts_todos(prefix: str, todos: Annotated[list[str], InjectedState("todos")]) -> str:
            """Count the run's todos."""
            return f"{prefix}{len(todos)}"

        recorder = _Recorder()
        node = DynamicToolNode(
            {"counts_todos": counts_todos}, middleware_executor=MiddlewareExecutor([recorder])
        )
        state = {**_one_call("counts_todos", {"prefix": "n="}), "todos": ["a", "b"]}

        result = await node._afunc(state, {}, Runtime())

        (message,) = result["messages"]
        assert message.content == "n=2"
        (request,) = recorder.requests
        assert request.tool_call["name"] == "counts_todos"
        assert request.state["todos"] == ["a", "b"]

    async def test_a_middleware_tool_runs_inside_the_chain(self) -> None:
        @tool
        def spawns(task: str) -> str:
            """Stand in for spawn_subagent."""
            return f"spawned {task}"

        recorder = _Recorder()
        node = DynamicToolNode(
            {}, middleware_executor=MiddlewareExecutor([recorder]), middleware_tools=[spawns]
        )

        message = await _run(node, "spawns", {"task": "t"})

        assert message.content == "spawned t"
        assert [r.tool_call["name"] for r in recorder.requests] == ["spawns"]

    async def test_a_tools_command_comes_back_with_its_state_update(self) -> None:
        @tool
        def plans(title: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
            """Write a plan into state."""
            reply = ToolMessage(content="planned", tool_call_id=tool_call_id)
            return Command(update={"messages": [reply], "todos": [title]})

        result = await _real_node(plans)._afunc(_one_call("plans", {"title": "x"}), {}, Runtime())

        (command,) = result
        assert isinstance(command, Command)
        assert command.update["todos"] == ["x"]
        assert command.update["messages"][0].tool_call_id == "call_1"

    async def test_an_interrupt_raised_by_a_tool_reaches_the_runtime(self) -> None:
        @tool
        def asks_first(to: str) -> str:
            """Pause for approval."""
            raise GraphInterrupt(())

        with pytest.raises(GraphInterrupt):
            await _run(_real_node(asks_first), "asks_first", {"to": "bob"})


@pytest.fixture
def shrunk_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{NODE}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(f"{NODE}.TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS", 0.02)


@pytest.mark.usefixtures("shrunk_bounds")
class TestRealMiddlewarePath:
    """The tool call runs through a real MiddlewareExecutor around LangGraph's execution."""

    async def test_a_hung_tool_is_cut_short_under_its_own_name(self) -> None:
        message = await _run(_real_node(hangs), "hangs", {"query": "q"})
        assert message.status == "error"
        assert message.tool_call_id == "call_1"
        assert message.name == "hangs"
        assert message.content == (
            "Error: TimeoutError: 'hangs' timed out after 0.01s. The operation may or may "
            "not have completed on the provider side. Verify its effect before retrying."
        )

    async def test_a_proxied_timeout_names_the_real_tool_at_the_backstop_bound(self) -> None:
        message = await _run(
            _real_node(proxy), "execute", {"tool_name": "GMAIL_SEND_EMAIL", "data": {}}
        )
        assert message.name == "execute"
        assert message.text.startswith(
            "Error: TimeoutError: 'GMAIL_SEND_EMAIL' timed out after 0.03s."
        )

    async def test_a_proxied_exempt_tool_runs_unbounded(self) -> None:
        message = await _run(
            _real_node(proxy), "execute", {"tool_name": "deep_research", "data": {}}
        )
        assert message.content == "ran deep_research"
        assert message.tool_call_id == "call_1"
        assert message.name == "execute"

    async def test_a_failing_tool_reports_its_error_under_its_own_name(self) -> None:
        message = await _run(_real_node(breaks), "breaks", {"query": "q"})
        assert message.status == "error"
        assert message.tool_call_id == "call_1"
        assert message.name == "breaks"
        assert message.content == "Error: ValueError: bad q"

    async def test_invalid_arguments_come_back_as_a_fixable_call_naming_each_field(
        self,
    ) -> None:
        """The model reads this text to retry: each field it controls, and only those, with its problem."""
        message = await _run(_real_node(files_a_ticket), "files_a_ticket", {"labels": ["x"]})

        assert message.status == "error"
        assert message.tool_call_id == "call_1"
        assert message.name == "files_a_ticket"
        first, *fields, last = message.text.splitlines()
        assert first == (
            "Error: ToolInvocationError: 'files_a_ticket' was not run, its arguments are invalid:"
        )
        assert fields == [
            "title: Field required",
            "labels.0: Input should be a valid integer, unable to parse string as an integer",
        ]
        assert last == "Nothing happened yet. Call it again with these arguments fixed."

    @pytest.mark.parametrize(
        "middleware_executor", [None, MiddlewareExecutor([_Passthrough()])], ids=["plain", "chain"]
    )
    async def test_invalid_arguments_never_reach_the_tool_body(
        self, middleware_executor: MiddlewareExecutor | None
    ) -> None:
        ran: list[str] = []

        @tool
        async def sends_mail(to: str, retries: int) -> str:
            """Send one email."""
            ran.append(to)
            return "sent"

        node = DynamicToolNode({"sends_mail": sends_mail}, middleware_executor=middleware_executor)
        message = await _run(node, "sends_mail", {"to": "bob@example.com", "retries": "many"})

        assert ran == []
        assert message.text.startswith(
            "Error: ToolInvocationError: 'sends_mail' was not run, its arguments are invalid:"
        )
        assert "retries: Input should be a valid integer" in message.text

    @pytest.mark.parametrize(
        "middleware_executor", [None, MiddlewareExecutor([_Passthrough()])], ids=["plain", "chain"]
    )
    async def test_a_validation_error_after_a_side_effect_never_claims_nothing_happened(
        self, middleware_executor: MiddlewareExecutor | None
    ) -> None:
        """A tool that sent the email then failed to parse the reply must not invite a resend."""
        sent: list[str] = []

        class _ProviderReply(BaseModel):
            message_id: str

        @tool
        async def sends_then_misparses(to: str) -> str:
            """Send an email and parse the provider's reply."""
            sent.append(to)
            return _ProviderReply.model_validate({}).message_id

        node = DynamicToolNode(
            {"sends_then_misparses": sends_then_misparses}, middleware_executor=middleware_executor
        )
        message = await _run(node, "sends_then_misparses", {"to": "bob@example.com"})

        assert sent == ["bob@example.com"]
        assert message.status == "error"
        assert message.tool_call_id == "call_1"
        assert message.text.startswith(
            "Error: ValidationError: 1 validation error for _ProviderReply"
        )
        assert "was not run" not in message.text
        assert "Nothing happened" not in message.text

    async def test_a_tool_that_explains_its_own_invalid_arguments_keeps_its_text(self) -> None:
        """write_playbook and every Composio tool render their own argument errors."""

        @tool
        async def explains_itself(steps: list[int]) -> str:
            """Store steps."""
            raise AssertionError("the tool ran with invalid arguments")

        explains_itself.handle_validation_error = "steps must be step numbers"

        message = await _run(_real_node(explains_itself), "explains_itself", {"steps": ["x"]})

        assert message.status == "error"
        assert message.content == "steps must be step numbers"

    async def test_an_unknown_tool_is_answered_on_its_own_call_id(self) -> None:
        message = await _run(_real_node(breaks), "ghost", {"query": "q"})
        assert message.content == "Error: ghost is not a valid tool, try one of [breaks]."
        assert message.status == "error"
        assert message.tool_call_id == "call_1"


_STAMPED = worker_context(Trigger.SCHEDULE).acting_as(Actor.AGENT)


@tool
def reports_its_analytics_context(query: str) -> str:
    """Name the analytics context the tool call runs in."""
    return f"{query}:{current_analytics_context().model_dump_json()}"


def _config_stamped() -> RunnableConfig:
    return {"configurable": {"analytics_context": _STAMPED.model_dump(mode="json")}}


class TestToolCallsActAsTheRunsAgent:
    """Every tool call runs as the agent in its run tree's context, never the request's user."""

    @pytest.mark.parametrize(
        "middleware_executor", [None, MiddlewareExecutor([_Passthrough()])], ids=["plain", "chain"]
    )
    async def test_a_tool_call_runs_in_the_stamped_context(
        self, middleware_executor: MiddlewareExecutor | None
    ) -> None:
        node = DynamicToolNode(
            {"reports_its_analytics_context": reports_its_analytics_context},
            middleware_executor=middleware_executor,
        )
        users_request = AnalyticsContext(
            attribution=Attribution(
                actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
            )
        )

        with analytics_context(users_request):
            result = await node._afunc(
                _one_call("reports_its_analytics_context", {"query": "q"}),
                _config_stamped(),
                Runtime(),
            )

        (message,) = result["messages"]
        assert message.content == f"q:{_STAMPED.model_dump_json()}"
        # The binding is scoped to the call: the request's context is untouched after it.
        with analytics_context(users_request):
            assert current_analytics_context() == users_request

    def test_a_sync_tool_call_runs_in_the_stamped_context(self) -> None:
        node = DynamicToolNode({"reports_its_analytics_context": reports_its_analytics_context})

        result = node._func(
            _one_call("reports_its_analytics_context", {"query": "q"}),
            _config_stamped(),
            Runtime(),
        )

        (message,) = result["messages"]
        assert message.content == f"q:{_STAMPED.model_dump_json()}"


@tool
def reports_its_thread(query: str, config: RunnableConfig) -> str:
    """Name the thread of the run config the tool call was handed."""
    return f"{query}:{config['configurable']['thread_id']}"


def _config_with_thread() -> RunnableConfig:
    return {"configurable": {**_config_stamped()["configurable"], "thread_id": "thread-1"}}


class TestToolCallsKeepTheRunConfig:
    """Binding the analytics context must still hand the tool the run's own config."""

    @pytest.mark.parametrize(
        "middleware_executor", [None, MiddlewareExecutor([_Passthrough()])], ids=["plain", "chain"]
    )
    async def test_an_async_tool_call_sees_the_run_config(
        self, middleware_executor: MiddlewareExecutor | None
    ) -> None:
        node = DynamicToolNode(
            {"reports_its_thread": reports_its_thread}, middleware_executor=middleware_executor
        )

        result = await node._afunc(
            _one_call("reports_its_thread", {"query": "q"}), _config_with_thread(), Runtime()
        )

        (message,) = result["messages"]
        assert message.content == "q:thread-1"

    def test_a_sync_tool_call_sees_the_run_config(self) -> None:
        node = DynamicToolNode({"reports_its_thread": reports_its_thread})

        result = node._func(
            _one_call("reports_its_thread", {"query": "q"}), _config_with_thread(), Runtime()
        )

        (message,) = result["messages"]
        assert message.content == "q:thread-1"


class TestProductionStackFailsClosed:
    """The real stack, in its real order, around a tool whose side effect is observable."""

    async def test_a_hil_gate_that_raises_never_runs_the_tool(self) -> None:
        sent: list[str] = []

        @tool
        async def send_email(to: str) -> str:
            """Send an email."""
            sent.append(to)
            return "sent"

        stack = create_middleware_stack(chat_llm=None, context=ContextOptions(summarize=False))
        node = DynamicToolNode(
            {"send_email": send_email}, middleware_executor=MiddlewareExecutor(stack)
        )
        config: RunnableConfig = {
            "configurable": {
                "user_id": "user_1",
                "thread_id": "thread_1",
                "stream_id": "stream_1",
                "conversation_id": "conv_1",
            }
        }

        with (
            patch("app.services.hil.gate.resolve_policy", AsyncMock(return_value="ask")),
            patch(
                "app.services.hil.gate.is_hil_ledger_enabled",
                AsyncMock(side_effect=RuntimeError("flag store down")),
            ),
        ):
            result = await node._afunc(
                _one_call("send_email", {"to": "bob@example.com"}), config, Runtime()
            )

        (message,) = result["messages"]
        assert sent == []
        assert message.status == "error"
        assert message.tool_call_id == "call_1"
        assert message.content == MIDDLEWARE_FAILURE_TEMPLATE.format(tool="send_email")
