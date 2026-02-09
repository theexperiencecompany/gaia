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

import inspect
from typing import Any, Callable, Optional, Awaitable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)

from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
    create_model_request,
    create_tool_call_request,
)
from app.config.loggers import app_logger as logger


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

    def __init__(self, middleware: list[AgentMiddleware] | None = None):
        """
        Initialize with a list of middleware instances.

        Args:
            middleware: List of AgentMiddleware instances to execute
        """
        self.middleware = middleware or []

    def _create_runtime(
        self,
        config: RunnableConfig,
        store: Optional[BaseStore] = None,
    ) -> BigtoolRuntime:
        """Create a BigtoolRuntime from graph context."""
        return BigtoolRuntime.from_graph_context(
            config=config,
            store=store,
        )

    def _create_tool_runtime(
        self,
        config: RunnableConfig,
        store: Optional[BaseStore] = None,
        tool_name: Optional[str] = None,
    ) -> BigtoolToolRuntime:
        """Create a BigtoolToolRuntime for tool execution."""
        return BigtoolToolRuntime(
            config=config,
            store=store,
            tool_name=tool_name,
        )

    async def execute_before_model(
        self,
        state: State,
        config: RunnableConfig,
        store: Optional[BaseStore] = None,
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
        current_state = dict(state)

        for mw in self.middleware:
            try:
                # Try async version first
                if hasattr(mw, "abefore_model"):
                    result = await mw.abefore_model(current_state, runtime)
                elif hasattr(mw, "before_model"):
                    result = mw.before_model(current_state, runtime)
                    if inspect.iscoroutine(result):
                        result = await result
                else:
                    continue

                if result is not None:
                    current_state.update(result)

            except Exception as e:
                logger.warning(
                    f"Middleware {mw.__class__.__name__}.before_model failed: {e}"
                )

        return current_state  # type: ignore

    async def execute_after_model(
        self,
        state: State,
        config: RunnableConfig,
        store: Optional[BaseStore] = None,
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
        current_state = dict(state)

        for mw in self.middleware:
            try:
                # Try async version first
                if hasattr(mw, "aafter_model"):
                    result = await mw.aafter_model(current_state, runtime)
                elif hasattr(mw, "after_model"):
                    result = mw.after_model(current_state, runtime)
                    if inspect.iscoroutine(result):
                        result = await result
                else:
                    continue

                if result is not None:
                    current_state.update(result)

            except Exception as e:
                logger.warning(
                    f"Middleware {mw.__class__.__name__}.after_model failed: {e}"
                )

        return current_state  # type: ignore

    async def wrap_model_invocation(
        self,
        model: BaseChatModel,
        state: State,
        config: RunnableConfig,
        store: Optional[BaseStore],
        tools: list[BaseTool],
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
            response = await invoke_fn(req.state.messages)
            return ModelResponse(response=response)

        # Wrap with middleware (reverse order so first middleware is outermost)
        current_handler = final_handler
        for mw in reversed(self.middleware):
            if hasattr(mw, "awrap_model_call"):
                # Create closure to capture current handler and middleware
                def make_wrapper(middleware, handler):
                    async def wrapped(req: ModelRequest) -> ModelResponse:
                        return await middleware.awrap_model_call(req, handler)

                    return wrapped

                current_handler = make_wrapper(mw, current_handler)
            elif hasattr(mw, "wrap_model_call"):

                def make_sync_wrapper(middleware, handler):
                    async def wrapped(req: ModelRequest) -> ModelResponse:
                        # Sync version - call and await if needed
                        result = middleware.wrap_model_call(req, handler)
                        if inspect.iscoroutine(result):
                            result = await result
                        return result

                    return wrapped

                current_handler = make_sync_wrapper(mw, current_handler)

        # Execute the chain
        try:
            result = await current_handler(request)
            return result.response if hasattr(result, "response") else result
        except Exception as e:
            logger.error(f"Middleware wrap_model_call chain failed: {e}")
            # Fallback to direct invocation
            return await invoke_fn(state.get("messages", []))

    async def wrap_tool_invocation(
        self,
        tool_call: dict[str, Any],
        tool: Optional[BaseTool],
        state: State,
        config: RunnableConfig,
        store: Optional[BaseStore],
        invoke_fn: Callable[..., Awaitable[ToolMessage]],
    ) -> ToolMessage:
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
            ToolMessage result (possibly modified by middleware)
        """
        tool_name = tool_call.get("name", "unknown")
        runtime = self._create_tool_runtime(config, store, tool_name)
        request = create_tool_call_request(tool_call, tool, state, runtime)

        # Build the handler chain from inside out
        async def final_handler(req: ToolCallRequest) -> ToolMessage:
            """Innermost handler - actually calls the tool."""
            return await invoke_fn(req.tool_call)

        # Wrap with middleware (reverse order so first middleware is outermost)
        current_handler = final_handler
        for mw in reversed(self.middleware):
            if hasattr(mw, "awrap_tool_call"):

                def make_wrapper(middleware, handler):
                    async def wrapped(req: ToolCallRequest) -> ToolMessage:
                        return await middleware.awrap_tool_call(req, handler)

                    return wrapped

                current_handler = make_wrapper(mw, current_handler)
            elif hasattr(mw, "wrap_tool_call"):

                def make_sync_wrapper(middleware, handler):
                    async def wrapped(req: ToolCallRequest) -> ToolMessage:
                        result = middleware.wrap_tool_call(req, handler)
                        if inspect.iscoroutine(result):
                            result = await result
                        return result

                    return wrapped

                current_handler = make_sync_wrapper(mw, current_handler)

        # Execute the chain
        try:
            return await current_handler(request)
        except Exception as e:
            logger.error(f"Middleware wrap_tool_call chain failed for {tool_name}: {e}")
            # Fallback to direct invocation
            return await invoke_fn(tool_call)

    def has_wrap_model_call(self) -> bool:
        """Check if any middleware has wrap_model_call."""
        return any(
            hasattr(mw, "wrap_model_call") or hasattr(mw, "awrap_model_call")
            for mw in self.middleware
        )

    def has_wrap_tool_call(self) -> bool:
        """Check if any middleware has wrap_tool_call."""
        return any(
            hasattr(mw, "wrap_tool_call") or hasattr(mw, "awrap_tool_call")
            for mw in self.middleware
        )
