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
import inspect
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.store.base import BaseStore
from langgraph.types import Command

from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
    create_model_request,
    create_tool_call_request,
    to_agent_state,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentMiddlewareStack
from app.override.langgraph_bigtool.utils import State, messages_delta_reducer
from app.services.analytics_service import AnalyticsEvents, capture_event
from shared.py.wide_events import log

# The handler chains built below. LangChain's hooks accept a wider return union
# (a bare AIMessage / ExtendedModelResponse for the model hook); this executor only
# ever feeds and consumes ModelResponse, so the model chain is narrowed to it.
ModelCallHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]
ToolCallHandler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]


def _apply_state_update(current_state: dict[str, Any], update: Mapping[str, Any]) -> None:
    """Merge a middleware hook's return into ``current_state``, in place.

    A hook returns a LangGraph *state update* — channel writes the graph
    resolves through each channel's reducer — not replacement state. This
    executor runs the hooks inside a single bigtool node, so the reducers are
    its job to apply; ``dict.update`` alone is a replacement and gets
    ``messages`` wrong in both directions. A hook appending one message
    (``LLMAccountingMiddleware``'s planned credit-gate reply) would erase the
    conversation, and ``SummarizationMiddleware``'s history-clearing
    ``RemoveMessage(REMOVE_ALL_MESSAGES)`` tombstone survived into the list
    handed to the model, where the provider serializer rejected it and 500ed
    the run.

    Every other channel in ``State`` is last-write-wins, which is what plain
    assignment already does.
    """
    for key, value in update.items():
        if key == "messages":
            current_state["messages"] = messages_delta_reducer(
                current_state.get("messages", []), [value]
            )
        else:
            current_state[key] = value


def _has_override(mw: AgentMiddleware, method_name: str) -> bool:
    """Check if middleware actually overrides a method.

    The base AgentMiddleware defines all hook methods (awrap_model_call,
    wrap_model_call, etc.) but their default implementations raise
    NotImplementedError. A naive hasattr() check always returns True,
    causing the executor to call unimplemented methods.

    This function walks the MRO and returns True only if a concrete
    subclass (not the AgentMiddleware base) defines the method.

    Args:
        mw: Middleware instance to check
        method_name: Name of the method to look for

    Returns:
        True if the method is overridden by a subclass
    """
    for cls in type(mw).__mro__:
        if cls is AgentMiddleware or cls is object:
            continue
        if method_name in cls.__dict__:
            return True
    return False


class MiddlewareExecutor:
    """
    Executes LangChain AgentMiddleware hooks in langgraph_bigtool context.

    This class provides methods to run middleware at various points:
    - execute_before_model: Run before_model hooks on all middleware
    - execute_after_model: Run after_model hooks on all middleware
    - wrap_model_invocation: Wrap the model call with all wrap_model_call middleware
    - wrap_tool_invocation: Wrap a tool call with all wrap_tool_call middleware

    Usage:
        executor = MiddlewareExecutor(middleware_list)

        # In acall_model:
        state = await executor.execute_before_model(state, config, store)
        response = await executor.wrap_model_invocation(model, state, config, store, tools)
        state = await executor.execute_after_model(state, config, store)

        # In DynamicToolNode:
        result = await executor.wrap_tool_invocation(tool_call, tool, state, config, store, handler)
    """

    def __init__(self, middleware: AgentMiddlewareStack | None = None) -> None:
        """
        Initialize with a list of middleware instances.

        Args:
            middleware: List of AgentMiddleware instances to execute
        """
        self.middleware = middleware or []

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
    ) -> State:
        """
        Execute before_model hooks on all middleware.

        Middleware are executed in order. Each middleware can modify the state
        by returning a dict that will be merged into the state.

        Args:
            state: Current graph state
            config: RunnableConfig from graph invocation
            store: Optional BaseStore instance

        Returns:
            Updated state after all middleware have run
        """
        if not self.middleware:
            return state

        runtime = self._create_runtime(config, store)
        current_state: dict[str, Any] = dict(state)

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

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(
                    f"{LogTag.AGENT} Middleware before_model failed",
                    middleware=mw.__class__.__name__,
                    error_type=type(e).__name__,
                )

        return State(**current_state)

    async def execute_after_model(
        self,
        state: State,
        config: RunnableConfig,
        store: BaseStore | None = None,
    ) -> State:
        """
        Execute after_model hooks on all middleware.

        Middleware are executed in order. Each middleware can modify the state
        by returning a dict that will be merged into the state.

        Args:
            state: Current graph state (after model response)
            config: RunnableConfig from graph invocation
            store: Optional BaseStore instance

        Returns:
            Updated state after all middleware have run
        """
        if not self.middleware:
            return state

        runtime = self._create_runtime(config, store)
        current_state: dict[str, Any] = dict(state)

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
        tools: list[BaseTool | dict[str, Any]],
        invoke_fn: Callable[..., Awaitable[AIMessage]],
    ) -> AIMessage:
        """
        Wrap the model invocation with all wrap_model_call middleware.

        Creates a chain of handlers where each middleware wraps the next.
        The innermost handler calls the actual model.

        Args:
            model: The LLM being used
            state: Current graph state
            config: RunnableConfig from graph invocation
            store: Optional BaseStore instance
            tools: List of tools bound to the model
            invoke_fn: The actual model invocation function

        Returns:
            AIMessage response from the model (possibly modified by middleware)
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
                    async def wrapped(req: ModelRequest) -> ModelResponse:
                        return cast(ModelResponse, await middleware.awrap_model_call(req, handler))

                    return wrapped

                current_handler = make_wrapper(mw, current_handler)
            elif _has_override(mw, "wrap_model_call"):

                def make_sync_wrapper(
                    middleware: AgentMiddleware, handler: ModelCallHandler
                ) -> ModelCallHandler:
                    async def wrapped(req: ModelRequest) -> ModelResponse:
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

    async def wrap_tool_invocation(
        self,
        tool_call: dict[str, Any],
        tool: BaseTool | None,
        state: State,
        config: RunnableConfig,
        store: BaseStore | None,
        invoke_fn: Callable[..., Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """
        Wrap a tool invocation with all wrap_tool_call middleware.

        Creates a chain of handlers where each middleware wraps the next.
        The innermost handler calls the actual tool.

        Args:
            tool_call: The tool call dict with id, name, args
            tool: The resolved BaseTool instance (if found)
            state: Current graph state
            config: RunnableConfig from graph invocation
            store: Optional BaseStore instance
            invoke_fn: The actual tool invocation function

        Returns:
            The tool result, or a ``Command`` when a middleware replaces the
            result with a graph update (e.g. workspace compaction).
        """
        tool_name = tool_call.get("name", "unknown")
        # Attribute the capture by the run's user; personless runs are skipped.
        configurable = config.get("configurable") or {}
        tool_user_id = configurable.get("user_id") if isinstance(configurable, dict) else None
        runtime = self._create_tool_runtime(config, store, tool_name)
        request = create_tool_call_request(tool_call, tool, state, runtime)

        # Holds the tool's own result once it has run, so the fallback below can
        # tell a middleware that failed *before* the tool from one that failed
        # after it — only the former is safe to retry.
        tool_result: ToolMessage | Command[Any] | None = None

        # Build the handler chain from inside out
        async def final_handler(req: ToolCallRequest) -> ToolMessage | Command[Any]:
            """Innermost handler - actually calls the tool."""
            nonlocal tool_result
            tool_result = await invoke_fn(req.tool_call)
            if tool_user_id:
                capture_event(
                    tool_user_id,
                    AnalyticsEvents.TOOL_USED,
                    {"tool_name": tool_name},
                )
            return tool_result

        # Wrap with middleware (reverse order so first middleware is outermost)
        current_handler: ToolCallHandler = final_handler
        for mw in reversed(self.middleware):
            if _has_override(mw, "awrap_tool_call"):

                def make_wrapper(
                    middleware: AgentMiddleware, handler: ToolCallHandler
                ) -> ToolCallHandler:
                    async def wrapped(req: ToolCallRequest) -> ToolMessage | Command[Any]:
                        return await middleware.awrap_tool_call(req, handler)

                    return wrapped

                current_handler = make_wrapper(mw, current_handler)
            elif _has_override(mw, "wrap_tool_call"):

                def make_sync_wrapper(
                    middleware: AgentMiddleware, handler: ToolCallHandler
                ) -> ToolCallHandler:
                    async def wrapped(req: ToolCallRequest) -> ToolMessage | Command[Any]:
                        # Async handler into the sync hook — see wrap_model_invocation.
                        result: Any = middleware.wrap_tool_call(
                            req,
                            cast(Callable[[ToolCallRequest], ToolMessage | Command[Any]], handler),
                        )
                        if inspect.iscoroutine(result):
                            result = await result
                        return cast(ToolMessage | Command[Any], result)

                    return wrapped

                current_handler = make_sync_wrapper(mw, current_handler)

        # Execute the chain
        try:
            return await current_handler(request)
        except GraphBubbleUp:
            # A GraphInterrupt (from the HIL gate's interrupt()) is control flow, not
            # a failure. It MUST propagate so LangGraph can checkpoint and pause —
            # the generic handler below would swallow it and then run the tool via
            # the direct-invocation fallback, executing a gated action unapproved.
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Middleware wrap_tool_call chain failed",
                tool_name=tool_name,
                error_type=type(e).__name__,
            )
            # The tool already ran — re-invoking would fire its side effects a
            # second time (another screen capture, another write). Ship the raw
            # result and lose only the post-tool middleware's transforms.
            if tool_result is not None:
                return tool_result
            # Nothing ran yet: a pre-tool middleware broke, so invoke directly.
            return await invoke_fn(tool_call)

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
