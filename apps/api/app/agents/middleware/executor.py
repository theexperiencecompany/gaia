"""
Middleware Executor - Runs LangChain AgentMiddleware hooks.

This module provides a MiddlewareExecutor class that bridges LangChain's
AgentMiddleware system with langgraph_bigtool's graph structure.

It handles executing middleware hooks at appropriate points:
- before_model: Before each LLM call
- after_model: After each LLM response
- wrap_model_call: Around the actual model invocation
- wrap_tool_call: Around each tool execution
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import inspect
from time import perf_counter
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.graph.message import Messages
from langgraph.store.base import BaseStore
from langgraph.types import Command

from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
    create_model_request,
    create_tool_call_request,
    to_agent_state,
)
from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.log_tags import LogTag
from app.models.agent_models import (
    AgentConfigurable,
    AgentMiddlewareStack,
    agent_configurable,
)
from app.override.langgraph_bigtool.utils import (
    State,
    messages_delta_reducer,
)
from app.services.analytics_service import capture
from app.services.latency_metrics import observe_tool_call
from shared.py.analytics import UserId
from shared.py.analytics.catalog.agents import ToolUsed
from shared.py.wide_events import log

# The handler chains built below. LangChain's hooks accept a wider return union
# (a bare AIMessage / ExtendedModelResponse for the model hook); this executor only
# ever feeds and consumes ModelResponse, so the model chain is narrowed to it.
ModelCallHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]
ToolCallHandler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[str]]]

MIDDLEWARE_FAILURE_TEMPLATE = (
    "`{tool}` was NOT run: a safety check that runs before every tool call failed "
    "with an internal error. Tell the user a system error prevented the action and "
    "they can retry."
)


@dataclass
class BeforeModelResult:
    """State after every before_model hook, plus the messages they staged in order."""

    state: State
    message_writes: list[BaseMessage]


class _ToolChainState:
    """Per-call mutable state for one wrap_tool_invocation chain."""

    def __init__(self) -> None:
        self.tool_result: ToolMessage | Command[str] | None = None
        self.tool_attempted = False
        self.failed_middleware: str | None = None


def _bind_async_tool_wrapper(
    middleware: AgentMiddleware, handler: ToolCallHandler
) -> ToolCallHandler:
    """Bind this middleware and handler by value, so every link does not close over the loop's last middleware."""

    async def wrapped(req: ToolCallRequest) -> ToolMessage | Command[str]:
        """Run the middleware's async wrap_tool_call hook around the rest of the chain."""
        return await middleware.awrap_tool_call(req, handler)

    return wrapped


def _bind_sync_tool_wrapper(
    middleware: AgentMiddleware, handler: ToolCallHandler
) -> ToolCallHandler:
    """Bind a sync-hook middleware by value into the chain, which stays async end to end."""

    async def wrapped(req: ToolCallRequest) -> ToolMessage | Command[str]:
        """Run the sync wrap_tool_call hook, awaiting its result when the hook turns out to be a coroutine."""
        # Async handler into the sync hook — see wrap_model_invocation.
        result: Any = middleware.wrap_tool_call(
            req,
            cast(Callable[[ToolCallRequest], ToolMessage | Command[str]], handler),
        )
        if inspect.iscoroutine(result):
            result = await result
        return cast(ToolMessage | Command[str], result)

    return wrapped


def _guard_tool_link(
    chain: _ToolChainState, middleware: AgentMiddleware, link: ToolCallHandler
) -> ToolCallHandler:
    """Record this middleware as the failure's source unless an inner link or the tool raised it."""

    async def guarded(req: ToolCallRequest) -> ToolMessage | Command[str]:
        try:
            return await link(req)
        except GraphBubbleUp:
            raise
        except Exception:
            tool_raised = chain.tool_attempted and chain.tool_result is None
            if chain.failed_middleware is None and not tool_raised:
                chain.failed_middleware = type(middleware).__name__
            raise

    return guarded


def _emit_bound_tool_used(tool_user_id: str | None, tool_name: str) -> None:
    """Attribute one bound-path tool run, skipping personless runs and the execute proxy."""
    # Proxied calls are counted by dispatch_tool under the REAL tool
    # name — emitting here too would double-count every proxied run
    # (root CLAUDE.md: one action, one event, one emitter).
    if tool_user_id and tool_name != EXECUTE_TOOL_NAME:
        # via segments the bound path from the execute path so the
        # migration's before/after cuts stay computable in PostHog.
        capture(UserId(tool_user_id), ToolUsed(tool_name=tool_name, via="bound"))


def _middleware_failure_message(tool_name: str, tool_call_id: str) -> ToolMessage:
    """Fail closed when a pre-tool middleware broke: the tool never runs."""
    return ToolMessage(
        content=MIDDLEWARE_FAILURE_TEMPLATE.format(tool=tool_name),
        tool_call_id=tool_call_id,
        name=tool_name,
        status="error",
    )


def _tool_metric_name(tool_name: str, tool: BaseTool | None) -> str:
    """Return the Prometheus label for a tool call.

    MCP/dynamic tools carry user-defined names, so they collapse to "mcp";
    the adapter class is method-local, so its tool_connector field is the
    structural signal.
    """
    if tool is not None and hasattr(tool, "tool_connector"):
        return "mcp"
    return tool_name or "unknown"


def _apply_state_update(current_state: State, update: Mapping[str, object]) -> None:
    """Merge a middleware hook's return into current_state, in place.

    A hook returns a LangGraph state update resolved through each channel's reducer, so a
    plain dict.update erases "messages" instead of appending and lets SummarizationMiddleware's
    RemoveMessage(REMOVE_ALL_MESSAGES) tombstone reach the model, 500ing the run. Every other
    channel is last-write-wins, which plain assignment already does.
    """
    for key, value in update.items():
        if key == "messages":
            current_state["messages"] = messages_delta_reducer(
                current_state.get("messages", []), [cast(Messages, value)]
            )
        else:
            cast(dict[str, object], current_state)[key] = value


def _has_override(mw: AgentMiddleware, method_name: str) -> bool:
    """Check if middleware actually overrides a method.

    The base AgentMiddleware defines all hook methods but their default
    implementations raise NotImplementedError, so a naive hasattr() check
    always returns True. Walks the MRO and returns True only if a concrete
    subclass defines the method.
    """
    for cls in type(mw).__mro__:
        if cls is AgentMiddleware or cls is object:
            continue
        if method_name in cls.__dict__:
            return True
    return False


class MiddlewareExecutor:
    """Executes LangChain AgentMiddleware hooks in langgraph_bigtool context.

    Runs before_model/after_model hooks on all middleware, and wraps model
    and tool calls with wrap_model_call/wrap_tool_call middleware.
    """

    def __init__(self, middleware: AgentMiddlewareStack | None = None) -> None:
        """Initialize with a list of middleware instances to execute."""
        self.middleware = middleware or []
        #: The stack's loop guard, for the one tool call that never reaches the
        #: tool node: retrieve_tools runs in the select_tools node, which
        #: consults this guard directly instead of the full tool-call chain.
        self.loop_guard: LoopGuardMiddleware | None = next(
            (mw for mw in self.middleware if isinstance(mw, LoopGuardMiddleware)), None
        )

    def _create_runtime(
        self,
        config: RunnableConfig,
        store: BaseStore | None = None,
    ) -> BigtoolRuntime:
        """Create a BigtoolRuntime from graph context."""
        return BigtoolRuntime.from_graph_context(
            config=config,
            store=store,
        )

    def _create_tool_runtime(
        self,
        config: RunnableConfig,
        store: BaseStore | None = None,
        tool_name: str | None = None,
    ) -> BigtoolToolRuntime:
        """Create a BigtoolToolRuntime for tool execution."""
        return BigtoolToolRuntime.from_graph_context(
            config=config,
            store=store,
            tool_name=tool_name,
        )

    async def execute_before_model(
        self,
        state: State,
        config: RunnableConfig,
        store: BaseStore | None = None,
    ) -> BeforeModelResult:
        """Execute before_model hooks on all middleware, in order.

        Updates merge through each channel's reducer; message writes are
        returned alongside the state so the caller commits them with the model
        response — a hook write is not a graph node write and would be dropped.
        """
        if not self.middleware:
            return BeforeModelResult(state=state, message_writes=[])

        runtime = self._create_runtime(config, store)
        current_state: State = state.copy()
        message_writes: list[BaseMessage] = []

        for mw in self.middleware:
            try:
                middleware_state = to_agent_state(current_state)
                # Try async version first
                if _has_override(mw, "abefore_model"):
                    result = await mw.abefore_model(middleware_state, runtime)
                elif _has_override(mw, "before_model"):
                    result = mw.before_model(middleware_state, runtime)
                else:
                    continue

                if result is not None:
                    _apply_state_update(current_state, result)
                    if "messages" in result:
                        written = result["messages"]
                        message_writes.extend(written if isinstance(written, list) else [written])

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(
                    f"{LogTag.AGENT} Middleware before_model failed",
                    middleware=mw.__class__.__name__,
                    error_type=type(e).__name__,
                )

        return BeforeModelResult(state=State(**current_state), message_writes=message_writes)

    async def execute_after_model(
        self,
        state: State,
        config: RunnableConfig,
        store: BaseStore | None = None,
    ) -> State:
        """Execute after_model hooks on all middleware, in order.

        Each middleware can modify the state by returning a dict merged
        into it.
        """
        if not self.middleware:
            return state

        runtime = self._create_runtime(config, store)
        current_state: State = state.copy()

        for mw in self.middleware:
            try:
                middleware_state = to_agent_state(current_state)
                # Try async version first
                if _has_override(mw, "aafter_model"):
                    result = await mw.aafter_model(middleware_state, runtime)
                elif _has_override(mw, "after_model"):
                    result = mw.after_model(middleware_state, runtime)
                else:
                    continue

                if result is not None:
                    _apply_state_update(current_state, result)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(
                    f"{LogTag.AGENT} Middleware after_model failed",
                    middleware=mw.__class__.__name__,
                    error_type=type(e).__name__,
                )

        return State(**current_state)

    async def wrap_model_invocation(
        self,
        model: BaseChatModel,
        state: State,
        config: RunnableConfig,
        store: BaseStore | None,
        tools: list[BaseTool | dict[str, object]],
        invoke_fn: Callable[..., Awaitable[AIMessage]],
    ) -> AIMessage:
        """Wrap the model invocation with all wrap_model_call middleware.

        Creates a chain of handlers where each middleware wraps the next;
        the innermost handler calls the actual model.
        """
        runtime = self._create_runtime(config, store)
        request = create_model_request(model, state, runtime, tools)

        # Build the handler chain from inside out
        async def final_handler(req: ModelRequest) -> ModelResponse:
            """Innermost handler - actually calls the model."""
            # Build messages list: prepend system_message if present, then messages
            messages_to_send: list[AnyMessage] = []
            if req.system_message:
                messages_to_send.append(req.system_message)
            messages_to_send.extend(req.messages)
            response = await invoke_fn(messages_to_send)
            return ModelResponse(result=[response])

        # Wrap with middleware (reverse order so first middleware is outermost)
        current_handler: ModelCallHandler = final_handler
        for mw in reversed(self.middleware):
            if _has_override(mw, "awrap_model_call"):
                # Create closure to capture current handler and middleware
                def make_wrapper(
                    middleware: AgentMiddleware, handler: ModelCallHandler
                ) -> ModelCallHandler:
                    """Bind this middleware and handler by value, so every link does not close over the loop's last middleware."""

                    async def wrapped(req: ModelRequest) -> ModelResponse:
                        """Run the middleware's async wrap_model_call hook around the rest of the chain."""
                        return cast(ModelResponse, await middleware.awrap_model_call(req, handler))

                    return wrapped

                current_handler = make_wrapper(mw, current_handler)
            elif _has_override(mw, "wrap_model_call"):

                def make_sync_wrapper(
                    middleware: AgentMiddleware, handler: ModelCallHandler
                ) -> ModelCallHandler:
                    """Bind a sync-hook middleware by value into the chain, which stays async end to end."""

                    async def wrapped(req: ModelRequest) -> ModelResponse:
                        """Run the sync wrap_model_call hook, awaiting its result when the hook turns out to be a coroutine."""
                        # Sync version - call and await if needed
                        # This bridge is async-only, so the sync hook is handed the
                        # async handler and its awaitable result is awaited below.
                        result: Any = middleware.wrap_model_call(
                            req, cast(Callable[[ModelRequest], ModelResponse], handler)
                        )
                        if inspect.iscoroutine(result):
                            result = await result
                        return cast(ModelResponse, result)

                    return wrapped

                current_handler = make_sync_wrapper(mw, current_handler)

        # Execute the chain
        try:
            result = await current_handler(request)
            if not result.result:
                raise ValueError("Model middleware returned empty result list")

            message = result.result[0]
            if isinstance(message, AIMessage):
                return message

            return AIMessage(content=str(getattr(message, "content", message)))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Middleware wrap_model_call chain failed",
                error_type=type(e).__name__,
            )
            # Fallback to direct invocation
            return await invoke_fn(state.get("messages", []))

    def _build_tool_chain(
        self, final_handler: ToolCallHandler, chain: _ToolChainState
    ) -> ToolCallHandler:
        """Wrap the innermost handler with each middleware, outermost first."""
        current_handler = final_handler
        for mw in reversed(self.middleware):
            if _has_override(mw, "awrap_tool_call"):
                current_handler = _guard_tool_link(
                    chain, mw, _bind_async_tool_wrapper(mw, current_handler)
                )
            elif _has_override(mw, "wrap_tool_call"):
                current_handler = _guard_tool_link(
                    chain, mw, _bind_sync_tool_wrapper(mw, current_handler)
                )
        return current_handler

    async def wrap_tool_invocation(
        self,
        tool_call: ToolCall,
        tool: BaseTool | None,
        state: State,
        config: RunnableConfig,
        store: BaseStore | None,
        invoke_fn: Callable[..., Awaitable[ToolMessage | Command[str]]],
    ) -> ToolMessage | Command[str]:
        """Wrap a tool invocation with all wrap_tool_call middleware.

        Creates a chain of handlers where each middleware wraps the next;
        the innermost handler calls the actual tool. Returns the tool
        result, or a Command when a middleware replaces it with a graph
        update (e.g. workspace compaction).
        """
        tool_name = tool_call.get("name", "unknown")
        # Attribute the capture by the run's user; personless runs are skipped.
        configurable: AgentConfigurable = agent_configurable(config)
        tool_user_id = configurable.get("user_id")
        runtime = self._create_tool_runtime(config, store, tool_name)
        # A ToolCall is a plain dict at runtime; create_tool_call_request re-normalizes it.
        request = create_tool_call_request(cast(dict[str, object], tool_call), tool, state, runtime)
        # Where the chain broke decides the outcome below: before the tool (refuse),
        # in the tool (tool_attempted with no result: propagate), or after it (ship
        # the result). failed_middleware names the innermost hook that raised.
        chain = _ToolChainState()

        # Build the handler chain from inside out
        async def final_handler(req: ToolCallRequest) -> ToolMessage | Command[str]:
            """Innermost handler - actually calls the tool."""
            chain.tool_attempted = True
            chain.tool_result = await invoke_fn(req.tool_call)
            _emit_bound_tool_used(tool_user_id, tool_name)
            return chain.tool_result

        current_handler = self._build_tool_chain(final_handler, chain)

        # Execute the chain
        metric_name = _tool_metric_name(tool_name, tool)
        chain_start = perf_counter()
        try:
            result = await current_handler(request)
        except GraphBubbleUp:
            # A GraphInterrupt is control flow, not a failure: it MUST propagate
            # so the run pauses for approval instead of returning a refusal.
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Middleware wrap_tool_call chain failed",
                tool_name=tool_name,
                middleware=chain.failed_middleware,
                error_type=type(e).__name__,
            )
            # The tool already ran and succeeded: re-invoking would repeat its side
            # effects, so ship the raw result (losing only the post-tool transforms)
            # and record a success, since the status label is the tool's outcome.
            if chain.tool_result is not None:
                result = chain.tool_result
            else:
                observe_tool_call(
                    perf_counter() - chain_start, tool_name=metric_name, status="error"
                )
                if chain.tool_attempted:
                    # The tool itself raised: retrying would run its side effects again.
                    raise
                # A pre-tool middleware broke, and it may be the approval gate: fail
                # closed. The tool never runs on a check that did not complete.
                return _middleware_failure_message(tool_name, tool_call.get("id") or "")
        observe_tool_call(perf_counter() - chain_start, tool_name=metric_name, status="success")
        return result

    def has_wrap_model_call(self) -> bool:
        """Check if any middleware has wrap_model_call."""
        return any(
            _has_override(mw, "wrap_model_call") or _has_override(mw, "awrap_model_call")
            for mw in self.middleware
        )

    def has_wrap_tool_call(self) -> bool:
        """Check if any middleware has wrap_tool_call."""
        return any(
            _has_override(mw, "wrap_tool_call") or _has_override(mw, "awrap_tool_call")
            for mw in self.middleware
        )
