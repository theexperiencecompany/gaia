"""
DynamicToolNode - A ToolNode that supports dynamically added tools and middleware.

This module provides a ToolNode subclass that:
1. Looks up tools dynamically from a registry at execution time
2. Supports tools added after graph compilation
3. Runs every tool call through LangGraph's own execution, wrapped by the
   AgentMiddleware wrap_tool_call chain, an argument check and a timeout
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import (
    ToolCallRequest,
    ToolInvocationError,
    _filter_validation_errors,
    _get_all_injected_args,
)
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from app.agents.middleware.executor import MiddlewareExecutor
from app.agents.tools.execute.unwrap import unwrap_execute_call
from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.llm import (
    TOOL_EXECUTION_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS,
    TOOL_TIMEOUT_EXEMPT_TOOLS,
)
from app.models.agent_models import agent_configurable, run_analytics_context
from shared.py.analytics.context import analytics_context

ToolCallExecutor = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]


def format_tool_error(exc: Exception) -> str:
    """Uniform error text for a tool call that failed while running, including the exception type.

    Arguments are checked before the tool starts, so a ToolInvocationError here wraps a
    ValidationError the running tool raised: it reports that error, never a call that did not run.
    """
    if isinstance(exc, GraphBubbleUp):
        # ToolNode hands its wrapper's exceptions here unfiltered; an interrupt must reach the runtime.
        raise exc
    cause = exc.source if isinstance(exc, ToolInvocationError) else exc
    return f"Error: {type(cause).__name__}: {cause}"


def _invalid_arguments_text(tool_name: str, errors: Sequence[ErrorDetails]) -> str:
    """Name each model-controlled argument that failed validation, one 'field: problem' line each."""
    lines = "\n".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in errors
    )
    return (
        f"Error: {ToolInvocationError.__name__}: '{tool_name}' was not run, its arguments "
        f"are invalid:\n{lines}\n"
        "Nothing happened yet. Call it again with these arguments fixed."
    )


def _timeout_error_text(tool_name: str, seconds: float | None) -> str:
    """Build the timeout error text; seconds is None when an exempt tool timed out itself."""
    after = f" after {seconds:g}s" if seconds is not None else ""
    return (
        f"Error: TimeoutError: '{tool_name}' timed out{after}. The operation may or "
        "may not have completed on the provider side. Verify its effect before retrying."
    )


def _node_timeout_seconds(tool_call: Mapping[str, Any]) -> float | None:
    """Return the timeout this node puts on one call; None when it applies none.

    Unwrapped first so a proxied call is judged as its real tool. A proxied call
    gets the backstop window, not the plain bound: dispatch_tool already bounds the
    tool at the same deadline, so an equal outer bound made its structured error
    unreachable. The node backstops what dispatch does not cover (resolution).
    """
    name = tool_call["name"]
    real_name, _ = unwrap_execute_call(name, tool_call.get("args") or {})
    if real_name in TOOL_TIMEOUT_EXEMPT_TOOLS:
        return None
    if name == EXECUTE_TOOL_NAME:
        return TOOL_EXECUTION_TIMEOUT_SECONDS + TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS
    return TOOL_EXECUTION_TIMEOUT_SECONDS


async def timeout_guarded_tool_call(
    request: ToolCallRequest, execute: ToolCallExecutor
) -> ToolMessage | Command:
    """Bound one tool run, so a hung integration call cannot hang the whole run.

    Long-running orchestration tools manage their own lifecycles and are exempt.
    """
    tool_call = request.tool_call
    # Reported on timeout as the real tool, not as the proxy.
    tool_name, _ = unwrap_execute_call(tool_call["name"], tool_call.get("args", {}) or {})
    bound = _node_timeout_seconds(tool_call)
    try:
        # asyncio.timeout(None) applies no deadline — an exempt tool runs unbounded.
        async with asyncio.timeout(bound):
            return await execute(request)
    except TimeoutError:
        return ToolMessage(
            content=_timeout_error_text(tool_name, bound),
            tool_call_id=tool_call.get("id", ""),
            name=tool_call["name"],
            status="error",
        )


class DynamicToolNode(ToolNode):
    """A ToolNode whose tools come from a live registry, so tools bound after compilation run.

    Every call takes LangGraph's one execution path (injection, Command validation,
    GraphBubbleUp propagation, error handling), wrapped per call by the middleware
    chain, then the argument check, then the timeout.
    """

    def __init__(
        self,
        tool_registry: Mapping[str, BaseTool],
        *,
        middleware_executor: MiddlewareExecutor | None = None,
        middleware_tools: Sequence[BaseTool] = (),
    ) -> None:
        """Register middleware_tools (e.g. spawn_subagent) alongside the registry's tools."""
        super().__init__(
            [*tool_registry.values(), *middleware_tools],
            handle_tool_errors=format_tool_error,
            awrap_tool_call=self._run_tool_call,
        )
        self._tool_registry = tool_registry
        self._middleware_executor = middleware_executor or MiddlewareExecutor()

    def _sync_registry(self) -> None:
        """Sync tools_by_name and _injected_args with current registry state."""
        for name, tool in self._tool_registry.items():
            if name not in self.tools_by_name:
                self.tools_by_name[name] = tool
                self._injected_args[name] = _get_all_injected_args(tool)

    def _func(
        self,
        tool_input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ) -> Any:  # noqa: ANN401 -- mirrors LangGraph ToolNode methods typed Any upstream
        """Override to inject dynamically added tools before execution.

        Return type mirrors ToolNode._func, which is itself typed Any
        upstream (its shape varies: dict[str, list[BaseMessage]], a list of
        results, or a Command).
        """
        self._sync_registry()
        with analytics_context(run_analytics_context(agent_configurable(config))):
            return super()._func(tool_input, config, runtime)

    async def _afunc(
        self,
        tool_input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ) -> Any:  # noqa: ANN401 -- mirrors LangGraph ToolNode methods typed Any upstream
        """Override to inject dynamically added tools before execution.

        Return type mirrors ToolNode._afunc, which is itself typed Any
        upstream — see _func above.
        """
        self._sync_registry()
        # Every tool call is the agent's action, whoever started the run.
        with analytics_context(run_analytics_context(agent_configurable(config))):
            return await super()._afunc(tool_input, config, runtime)

    async def _run_tool_call(
        self, request: ToolCallRequest, execute: ToolCallExecutor
    ) -> ToolMessage | Command:
        """Run one call through the middleware chain; its innermost link checks arguments, then runs bounded."""

        async def run_checked(checked: ToolCallRequest) -> ToolMessage | Command:
            invalid = self._reject_invalid_arguments(checked)
            if invalid is not None:
                return invalid
            return await timeout_guarded_tool_call(checked, execute)

        return await self._middleware_executor.wrap_tool_invocation(request, run_checked)

    def _reject_invalid_arguments(self, request: ToolCallRequest) -> ToolMessage | None:
        """Validate the call exactly as its tool will, before the body runs; a failure is the model's to fix.

        Injected state/store/runtime are filled first, as LangGraph's execute does, so
        only arguments the model controls can fail. An unknown tool is execute's to answer, and
        a tool with its own handle_validation_error (write_playbook, Composio) keeps its own text.
        """
        tool = request.tool
        if tool is None or tool.handle_validation_error:
            return None
        call = self._inject_tool_args(request.tool_call, request.runtime, tool)
        try:
            # The exact parse BaseTool.arun runs before the body; langchain exposes no public twin.
            tool._to_args_and_kwargs(dict(call["args"]), call["id"])
        except ValidationError as exc:
            name = call["name"]
            return ToolMessage(
                content=_invalid_arguments_text(
                    name, _filter_validation_errors(exc, self._injected_args.get(name))
                ),
                tool_call_id=call["id"],
                name=name,
                status="error",
            )
        return None
