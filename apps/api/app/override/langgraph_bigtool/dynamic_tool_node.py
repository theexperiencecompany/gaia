"""
DynamicToolNode - A ToolNode that supports dynamically added tools and middleware.

This module provides a ToolNode subclass that:
1. Looks up tools dynamically from a registry at execution time
2. Supports tools added after graph compilation
3. Integrates with LangChain AgentMiddleware wrap_tool_call hooks
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import (
    AsyncToolCallWrapper,
    ToolCallRequest,
    ToolCallWrapper,
    _default_handle_tool_errors,
    _get_all_injected_args,
)
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.middleware.executor import MiddlewareExecutor
from app.agents.workspace.offload import mark_offload, pop_offload_descriptor
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS, TOOL_TIMEOUT_EXEMPT_TOOLS
from app.override.langgraph_bigtool.utils import State
from app.services.hil.gate import decide_tool_call


def format_tool_error(exc: Exception) -> str:
    """Uniform error text for a failed tool call, with the exception type.

    Passed to ToolNode as ``handle_tool_errors`` so parent-routed tools
    (InjectedState / middleware tools) convert failures into error
    ToolMessages instead of crashing the whole run; also used by the
    middleware dispatch path so both paths speak the same format. The type
    name matters: it's how the model distinguishes a transient network error
    from a permanently invalid request.
    """
    return f"Error: {type(exc).__name__}: {exc}"


def _timeout_error_text(tool_name: str) -> str:
    return (
        f"Error: TimeoutError: '{tool_name}' timed out after "
        f"{TOOL_EXECUTION_TIMEOUT_SECONDS}s. The operation may or may not have "
        "completed on the provider side — verify its effect before retrying."
    )


async def timeout_guarded_tool_call(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    """Per-call execution wrapper (ToolNode ``awrap_tool_call``): bound hung tools.

    A hung integration call previously hung the entire run forever. Long-running
    orchestration tools manage their own lifecycles and are exempt.
    """
    tool_call = request.tool_call
    tool_name = tool_call.get("name", "")
    if tool_name in TOOL_TIMEOUT_EXEMPT_TOOLS:
        return await execute(request)
    try:
        async with asyncio.timeout(TOOL_EXECUTION_TIMEOUT_SECONDS):
            return await execute(request)
    except TimeoutError:
        return ToolMessage(
            content=_timeout_error_text(tool_name),
            tool_call_id=tool_call.get("id", ""),
            name=tool_name,
            status="error",
        )


async def hil_and_timeout_guarded_tool_call(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    """Parent ToolNode ``awrap_tool_call`` for InjectedState/middleware tools.

    The gate is asked first and separately: it only ever reads a decision the
    ``approvals`` node already settled, so a blocked call costs nothing and never
    enters the timeout window meant for the tool itself.
    """
    blocked = await decide_tool_call(request)
    if blocked is not None:
        return blocked
    return await timeout_guarded_tool_call(request, execute)


class DynamicToolNode(ToolNode):
    """
    A ToolNode that supports dynamically added tools and middleware.

    Wraps a tool_registry (DynamicToolDict) and looks up tools at execution time,
    allowing tools added after graph compilation to be executed.

    Also supports LangChain AgentMiddleware wrap_tool_call hooks.
    """

    def __init__(
        self,
        tool_registry: Mapping[str, BaseTool],
        middleware_executor: "MiddlewareExecutor | None" = None,
        middleware_tools: list[BaseTool] | None = None,
        *,
        name: str = "tools",
        tags: list[str] | None = None,
        handle_tool_errors: bool
        | str
        | Callable[..., str]
        | type[Exception]
        | tuple[type[Exception], ...] = _default_handle_tool_errors,
        messages_key: str = "messages",
        wrap_tool_call: ToolCallWrapper | None = None,
        awrap_tool_call: AsyncToolCallWrapper | None = None,
    ) -> None:
        """Initialize DynamicToolNode.

        Args:
            tool_registry: Mapping of tool names to tool instances
            middleware_executor: Optional middleware executor for wrap_tool_call hooks
            middleware_tools: Optional list of tools from middleware (e.g., SubagentMiddleware)
                that need parent ToolNode handling (InjectedToolCallId, Command returns)
            name, tags, handle_tool_errors, messages_key, wrap_tool_call, awrap_tool_call:
                Forwarded verbatim to ``ToolNode.__init__`` — see its docstring.
        """
        # Combine registry tools with middleware tools for initialization
        all_tools = list(tool_registry.values())
        if middleware_tools:
            all_tools.extend(middleware_tools)

        super().__init__(
            all_tools,
            name=name,
            tags=tags,
            handle_tool_errors=handle_tool_errors,
            messages_key=messages_key,
            wrap_tool_call=wrap_tool_call,
            awrap_tool_call=awrap_tool_call,
        )
        self._tool_registry = tool_registry
        self._middleware_executor = middleware_executor
        self._middleware_tools = middleware_tools or []

        # Register middleware tools in tools_by_name for lookup
        for tool in self._middleware_tools:
            if hasattr(tool, "name"):
                self.tools_by_name[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool | None:
        """Look up tool dynamically from registry.

        Args:
            name: Tool name to look up

        Returns:
            Tool instance or None if not found
        """
        # First try the registry (includes dynamically added tools)
        if name in self._tool_registry:
            return self._tool_registry[name]
        # Fall back to parent's tools_by_name
        return self.tools_by_name.get(name)

    def _sync_registry(self) -> None:
        """Sync tools_by_name and _injected_args with current registry state."""
        for name in self._tool_registry:
            if name not in self.tools_by_name:
                raw_tool = self._tool_registry[name]
                self.tools_by_name[name] = raw_tool
                # Build injected args for newly added tools so parent
                # ToolNode._afunc can handle InjectedState injection
                if name not in self._injected_args:
                    self._injected_args[name] = _get_all_injected_args(raw_tool)

    def _func(
        self,
        tool_input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ) -> Any:  # noqa: ANN401 -- mirrors LangGraph ToolNode methods typed Any upstream
        """Override to inject dynamically added tools before execution.

        Return type mirrors ``ToolNode._func``, which is itself typed ``Any``
        upstream (its shape varies: dict[str, list[BaseMessage]], a list of
        results, or a Command).
        """
        self._sync_registry()
        return super()._func(tool_input, config, runtime)

    async def _afunc(
        self,
        tool_input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ) -> Any:  # noqa: ANN401 -- mirrors LangGraph ToolNode methods typed Any upstream
        """Override to inject dynamically added tools before execution and apply middleware.

        Return type mirrors ``ToolNode._afunc``, which is itself typed ``Any``
        upstream — see ``_func`` above.
        """
        self._sync_registry()

        # If we have middleware with wrap_tool_call, use custom handling
        if self._middleware_executor and self._middleware_executor.has_wrap_tool_call():
            return await self._afunc_with_middleware(tool_input, config, runtime)

        return await super()._afunc(tool_input, config, runtime)

    def _needs_parent_routing(self, tool_name: str) -> bool:
        """Check if a tool needs parent ToolNode execution path.

        Returns True for middleware tools (e.g. spawn_subagent) and tools
        with InjectedState which need state injection only the parent handles.
        """
        mw_names = {t.name for t in self._middleware_tools if hasattr(t, "name")}
        if tool_name in mw_names:
            return True
        injected = self._injected_args.get(tool_name)
        return injected is not None and bool(injected.state)

    async def _afunc_with_middleware(
        self,
        tool_input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ) -> Any:  # noqa: ANN401 -- mirrors LangGraph ToolNode methods typed Any upstream
        """Execute tools with middleware wrap_tool_call hooks.

        Return type is ``Any``: two branches delegate straight to
        ``ToolNode._afunc`` (itself typed ``Any`` upstream); the rest return
        ``dict[str, list[ToolMessage | Command]] | list[ToolMessage | Command]``.

        This method is called when middleware with wrap_tool_call is present.
        It wraps each tool invocation with the middleware hooks.

        Tools that use InjectedState or come from middleware are delegated to
        the parent ToolNode._afunc which handles InjectedState injection,
        Command returns, InjectedToolCallId, and validation.
        Only regular tool calls go through the middleware wrap_tool_call chain
        (e.g. WorkspaceCompactionMiddleware).
        """
        tool_calls, _ = self._parse_input(tool_input)
        all_parent_routed = all(self._needs_parent_routing(tc.get("name", "")) for tc in tool_calls)
        if all_parent_routed:
            return await super()._afunc(tool_input, config, runtime)
        delegate_state = self._extract_state(tool_input, config)
        middleware_state = self._coerce_middleware_state(delegate_state)

        # Get store from runtime if available
        store: BaseStore | None = getattr(runtime, "store", None)
        middleware_executor = self._middleware_executor
        if middleware_executor is None:
            return await super()._afunc(tool_input, config, runtime)

        results: list[ToolMessage | Command] = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")

            # Parent-routed tools: delegate to parent's execution path
            if self._needs_parent_routing(tool_name):
                results.extend(
                    await self._run_parent_for_tool_call(
                        dict(cast(Mapping[str, Any], tool_call)),
                        delegate_state,
                        config,
                        runtime,
                    )
                )
                continue

            results.append(
                await self._run_tool_call_with_middleware(
                    tool_call=dict(cast(Mapping[str, Any], tool_call)),
                    tool=self.get_tool(tool_name),
                    middleware_executor=middleware_executor,
                    store=store,
                    config=config,
                    state=middleware_state,
                )
            )

        # Separate Commands from ToolMessages for proper LangGraph handling
        has_commands = any(isinstance(r, Command) for r in results)
        if not has_commands:
            return {"messages": results}

        # Mixed results: return as list so LangGraph handles Commands
        return results

    async def _run_parent_for_tool_call(
        self,
        tool_call: dict[str, Any],
        delegate_state: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ) -> list[ToolMessage | Command]:
        single_call_with_context = {
            "__type": "tool_call_with_context",
            "tool_call": dict(cast(Mapping[str, Any], tool_call)),
            "state": delegate_state,
        }
        single_result = await super()._afunc(single_call_with_context, config, runtime)
        if isinstance(single_result, dict):
            return list(single_result.get("messages", []))
        if isinstance(single_result, list):
            return single_result
        return [single_result]

    async def _run_tool_call_with_middleware(
        self,
        *,
        tool_call: dict[str, Any],
        tool: BaseTool | None,
        middleware_executor: MiddlewareExecutor,
        store: BaseStore | None,
        config: RunnableConfig,
        state: State,
    ) -> ToolMessage | Command:
        """Result is normally a ToolMessage; a middleware (e.g. workspace
        compaction) may replace it with a Command graph update instead — see
        MiddlewareExecutor.wrap_tool_invocation.
        """

        async def invoke_tool(tc: dict[str, Any]) -> ToolMessage | Command:
            resolved_tool = self.get_tool(tc.get("name", ""))
            if resolved_tool is None:
                return ToolMessage(
                    content=f"Tool '{tc.get('name')}' not found",
                    tool_call_id=tc.get("id", ""),
                )

            tool_input = dict(tc)
            tool_input["type"] = "tool_call"
            tool_name = tc.get("name", "")
            try:
                if tool_name in TOOL_TIMEOUT_EXEMPT_TOOLS:
                    result = await resolved_tool.ainvoke(tool_input, config=config)
                else:
                    async with asyncio.timeout(TOOL_EXECUTION_TIMEOUT_SECONDS):
                        result = await resolved_tool.ainvoke(tool_input, config=config)
            except GraphBubbleUp:
                # Control flow, not a failure: a GraphInterrupt raised by a gated
                # tool — or bubbled up by ``handoff`` when its subagent graph
                # interrupts — must reach the runtime so the run checkpoints and
                # pauses. Converting it to an error ToolMessage would silently
                # drop the approval request. Mirrors upstream ToolNode.
                raise
            except TimeoutError:
                return ToolMessage(
                    content=_timeout_error_text(tool_name),
                    tool_call_id=tc.get("id", ""),
                    name=tool_name,
                    status="error",
                )
            except Exception as exc:
                return ToolMessage(
                    content=format_tool_error(exc),
                    tool_call_id=tc.get("id", ""),
                    name=tool_name,
                    status="error",
                )

            # A state-mutating tool (plan_tasks, and any tool whose effect IS a
            # graph update) returns a Command. Pass it through untouched: the
            # caller separates Commands from ToolMessages so LangGraph applies
            # the update. Falling through to the str() below would render the
            # Command's repr into the model's context and drop the state change
            # silently -- the tool looks like it worked and nothing it wrote
            # survives. The parent-routing path already handles this; only tools
            # without InjectedState reach here.
            if isinstance(result, (ToolMessage, Command)):
                return result

            # A self-offloading tool (returns a dict) can't set additional_kwargs
            # itself — lift its offload descriptor into the structured marker here,
            # the one seam where dict results become ToolMessages. pop_* strips the
            # descriptor so it never leaks into the model-facing content.
            info = pop_offload_descriptor(result)
            additional_kwargs = mark_offload({}, info) if info else {}
            return ToolMessage(
                content=str(result) if not isinstance(result, str) else result,
                tool_call_id=tc.get("id", ""),
                name=tc.get("name", ""),
                additional_kwargs=additional_kwargs,
            )

        return await middleware_executor.wrap_tool_invocation(
            tool_call=dict(cast(Mapping[str, Any], tool_call)),
            tool=tool,
            state=state,
            config=config,
            store=store,
            invoke_fn=invoke_tool,
        )

    def _coerce_middleware_state(
        self,
        delegate_state: list[AnyMessage] | dict[str, Any] | BaseModel,
    ) -> State:
        """Normalize tool-call input state for middleware consumption.

        Preserve all state channels when available (dict/BaseModel), while ensuring
        a stable messages channel for middleware that relies on context size.
        """
        if isinstance(delegate_state, list):
            return cast(State, {"messages": list(delegate_state)})

        # _extract_state (upstream ToolNode) returns exactly
        # list[AnyMessage] | dict[str, Any] | BaseModel; list is handled above,
        # so only BaseModel and dict remain here.
        if isinstance(delegate_state, BaseModel):
            raw_state = cast(dict[str, Any], delegate_state.model_dump())
        else:
            raw_state = dict(delegate_state)

        messages = raw_state.get("messages")
        if isinstance(messages, list):
            raw_state["messages"] = list(messages)
        else:
            raw_state["messages"] = []

        return cast(State, raw_state)
