"""
DynamicToolNode - A ToolNode that supports dynamically added tools and middleware.

This module provides a ToolNode subclass that:
1. Looks up tools dynamically from a registry at execution time
2. Supports tools added after graph compilation
3. Integrates with LangChain AgentMiddleware wrap_tool_call hooks
"""

import inspect
from collections.abc import Mapping
from typing import Callable

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command
from langgraph_bigtool.graph import State

from app.agents.middleware.executor import MiddlewareExecutor


class DynamicToolNode(ToolNode):
    """
    A ToolNode that supports dynamically added tools and middleware.

    Wraps a tool_registry (DynamicToolDict) and looks up tools at execution time,
    allowing tools added after graph compilation to be executed.

    Also supports LangChain AgentMiddleware wrap_tool_call hooks.
    """

    def __init__(
        self,
        tool_registry: Mapping[str, BaseTool | Callable],
        middleware_executor: "MiddlewareExecutor | None" = None,
        middleware_tools: list[BaseTool] | None = None,
        **kwargs,
    ):
        """Initialize DynamicToolNode.

        Args:
            tool_registry: Mapping of tool names to tool instances or callables
            middleware_executor: Optional middleware executor for wrap_tool_call hooks
            middleware_tools: Optional list of tools from middleware (e.g., TodoMiddleware)
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

    def _get_tool(self, name: str) -> BaseTool | Callable | None:
        """Look up tool dynamically from registry.

        Args:
            name: Tool name to look up

        Returns:
            Tool instance, callable, or None if not found
        """
        # First try the registry (includes dynamically added tools)
        if name in self._tool_registry:
            return self._tool_registry[name]
        # Fall back to parent's tools_by_name
        return self.tools_by_name.get(name)

    def _sync_registry(self):
        """Sync tools_by_name with current registry state."""
        for name in self._tool_registry:
            if name not in self.tools_by_name:
                self.tools_by_name[name] = self._tool_registry[name]  # type: ignore[assignment]

    def _func(self, input, config, runtime: "Runtime"):
        """Override to inject dynamically added tools before execution."""
        self._sync_registry()
        return super()._func(input, config, runtime)

    async def _afunc(self, input, config, runtime: "Runtime"):
        """Override to inject dynamically added tools before execution and apply middleware."""
        self._sync_registry()

        # If we have middleware with wrap_tool_call, use custom handling
        if self._middleware_executor and self._middleware_executor.has_wrap_tool_call():
            return await self._afunc_with_middleware(input, config, runtime)

        return await super()._afunc(input, config, runtime)

    async def _afunc_with_middleware(self, input, config, runtime: "Runtime"):
        """Execute tools with middleware wrap_tool_call hooks.

        This method is called when middleware with wrap_tool_call is present.
        It wraps each tool invocation with the middleware hooks.

        Middleware tools (plan_tasks, mark_task, add_task) return Command objects
        that LangGraph must process directly. These are delegated to the parent
        ToolNode._afunc which handles Commands, arg injection, and validation.
        Only non-middleware, non-Command tool calls go through the middleware
        wrap_tool_call chain (e.g. VFSCompactionMiddleware).
        """
        # Middleware tool names — these return Command and must bypass wrapping
        mw_tool_names = {t.name for t in self._middleware_tools if hasattr(t, "name")}

        # Check if input contains ONLY middleware tool calls
        tool_calls = input if isinstance(input, list) else [input]
        all_middleware = all(tc.get("name", "") in mw_tool_names for tc in tool_calls)

        # If all calls are middleware tools, delegate entirely to parent
        # which properly handles Command returns, arg injection, etc.
        if all_middleware:
            return await super()._afunc(input, config, runtime)

        # Get store from runtime if available
        store: BaseStore | None = getattr(runtime, "store", None)

        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")

            # Middleware tools: delegate to parent's execution path
            if tool_name in mw_tool_names:
                # Use parent _afunc for this single call — it handles
                # Command returns, InjectedToolCallId, validation, etc.
                single_result = await super()._afunc([tool_call], config, runtime)
                # Parent returns {"messages": [...]} or list — extract results
                if isinstance(single_result, dict):
                    results.extend(single_result.get("messages", []))
                elif isinstance(single_result, list):
                    results.extend(single_result)
                else:
                    results.append(single_result)
                continue

            tool = self._get_tool(tool_name)

            # Create minimal state dict for middleware
            state: State = {
                "messages": [],
                "selected_tool_ids": [],
            }

            # Define the actual tool invocation function
            async def invoke_tool(tc):
                """Actual tool invocation."""
                resolved_tool = self._get_tool(tc.get("name", ""))
                if resolved_tool is None:
                    return ToolMessage(
                        content=f"Tool '{tc.get('name')}' not found",
                        tool_call_id=tc.get("id", ""),
                    )

                if isinstance(resolved_tool, BaseTool):
                    result = await resolved_tool.ainvoke(
                        {**tc, "type": "tool_call"}, config=config
                    )
                else:
                    result = resolved_tool(**tc.get("args", {}))
                    if inspect.iscoroutine(result):
                        result = await result

                # If tool returned a Command, pass through directly
                if isinstance(result, Command):
                    return result

                # If tool returned a ToolMessage, pass through
                if isinstance(result, ToolMessage):
                    return result

                return ToolMessage(
                    content=str(result) if not isinstance(result, str) else result,
                    tool_call_id=tc.get("id", ""),
                    name=tc.get("name", ""),
                )

            # Wrap with middleware
            result = await self._middleware_executor.wrap_tool_invocation(  # type: ignore[union-attr]
                tool_call=tool_call,
                tool=tool if isinstance(tool, BaseTool) else None,
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
