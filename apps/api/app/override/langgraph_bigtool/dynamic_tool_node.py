"""
DynamicToolNode - A ToolNode that supports dynamically added tools and middleware.

This module provides a ToolNode subclass that:
1. Looks up tools dynamically from a registry at execution time
2. Supports tools added after graph compilation
3. Integrates with LangChain AgentMiddleware wrap_tool_call hooks
"""

from collections.abc import Mapping
from typing import Any, cast

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import _get_all_injected_args
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.middleware.executor import MiddlewareExecutor
from app.override.langgraph_bigtool.utils import State


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
        **kwargs,
    ):
        """Initialize DynamicToolNode.

        Args:
            tool_registry: Mapping of tool names to tool instances
            middleware_executor: Optional middleware executor for wrap_tool_call hooks
            middleware_tools: Optional list of tools from middleware (e.g., SubagentMiddleware)
                that need parent ToolNode handling (InjectedToolCallId, Command returns)
            **kwargs: Additional arguments passed to ToolNode
        """
        # Combine registry tools with middleware tools for initialization
        all_tools = list(tool_registry.values())
        if middleware_tools:
            all_tools.extend(middleware_tools)

        super().__init__(all_tools, **kwargs)
        self._tool_registry = tool_registry
        self._middleware_executor = middleware_executor
        self._middleware_tools = middleware_tools or []

        # Register middleware tools in tools_by_name for lookup
        for tool in self._middleware_tools:
            if hasattr(tool, "name"):
                self.tools_by_name[tool.name] = tool

    def _get_tool(self, name: str) -> BaseTool | None:
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

    def _sync_registry(self):
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
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ):
        """Override to inject dynamically added tools before execution."""
        self._sync_registry()
        return super()._func(input, config, runtime)

    async def _afunc(
        self,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ):
        """Override to inject dynamically added tools before execution and apply middleware."""
        self._sync_registry()

        # If we have middleware with wrap_tool_call, use custom handling
        if self._middleware_executor and self._middleware_executor.has_wrap_tool_call():
            return await self._afunc_with_middleware(input, config, runtime)

        return await super()._afunc(input, config, runtime)

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
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: "Runtime",
    ):
        """Execute tools with middleware wrap_tool_call hooks.

        This method is called when middleware with wrap_tool_call is present.
        It wraps each tool invocation with the middleware hooks.

        Tools that use InjectedState or come from middleware are delegated to
        the parent ToolNode._afunc which handles InjectedState injection,
        Command returns, InjectedToolCallId, and validation.
        Only regular tool calls go through the middleware wrap_tool_call chain
        (e.g. VFSCompactionMiddleware).
        """
        tool_calls, _ = self._parse_input(input)
        all_parent_routed = all(
            self._needs_parent_routing(tc.get("name", "")) for tc in tool_calls
        )
        if all_parent_routed:
            return await super()._afunc(input, config, runtime)
        delegate_state: list[AnyMessage] | dict[str, Any] | BaseModel = (
            input["state"]
            if isinstance(input, dict)
            and input.get("__type") == "tool_call_with_context"
            else input
        )

        # Get store from runtime if available
        store: BaseStore | None = getattr(runtime, "store", None)
        middleware_executor = self._middleware_executor
        if middleware_executor is None:
            return await super()._afunc(input, config, runtime)

        results: list[ToolMessage | Command] = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")

            # Parent-routed tools: delegate to parent's execution path
            if self._needs_parent_routing(tool_name):
                single_call_with_context = {
                    "__type": "tool_call_with_context",
                    "tool_call": tool_call,
                    "state": delegate_state,
                }
                single_result = await super()._afunc(
                    single_call_with_context, config, runtime
                )
                if isinstance(single_result, dict):
                    results.extend(single_result.get("messages", []))
                elif isinstance(single_result, list):
                    results.extend(single_result)
                else:
                    results.append(single_result)
                continue

            tool = self._get_tool(tool_name)

            # Create minimal state dict for middleware
            state = cast(
                State,
                {
                    "messages": [],
                    "selected_tool_ids": [],
                    "todos": [],
                },
            )

            # Define the actual tool invocation function
            async def invoke_tool(tc: dict[str, Any]) -> ToolMessage:
                """Actual tool invocation."""
                resolved_tool = self._get_tool(tc.get("name", ""))
                if resolved_tool is None:
                    return ToolMessage(
                        content=f"Tool '{tc.get('name')}' not found",
                        tool_call_id=tc.get("id", ""),
                    )

                result = await resolved_tool.ainvoke(
                    {**tc, "type": "tool_call"}, config=config
                )

                # If tool returned a ToolMessage, pass through
                if isinstance(result, ToolMessage):
                    return result

                return ToolMessage(
                    content=str(result) if not isinstance(result, str) else result,
                    tool_call_id=tc.get("id", ""),
                    name=tc.get("name", ""),
                )

            # Wrap with middleware
            tool_call_payload: dict[str, Any] = dict(tool_call)
            result = await middleware_executor.wrap_tool_invocation(
                tool_call=tool_call_payload,
                tool=tool,
                state=state,
                config=config,
                store=store,
                invoke_fn=invoke_tool,
            )
            results.append(result)

        # Separate Commands from ToolMessages for proper LangGraph handling
        has_commands = any(isinstance(r, Command) for r in results)
        if not has_commands:
            return {"messages": results}

        # Mixed results: return as list so LangGraph handles Commands
        return results
