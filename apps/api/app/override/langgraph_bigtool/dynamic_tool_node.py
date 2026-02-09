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
        **kwargs,
    ):
        """Initialize DynamicToolNode.

        Args:
            tool_registry: Mapping of tool names to tool instances or callables
            middleware_executor: Optional middleware executor for wrap_tool_call hooks
            **kwargs: Additional arguments passed to ToolNode
        """
        # Initialize with current tools
        super().__init__(list(tool_registry.values()), **kwargs)
        self._tool_registry = tool_registry
        self._middleware_executor = middleware_executor

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
        """
        # Get store from runtime if available
        store: BaseStore | None = getattr(runtime, "store", None)

        # The input is a list of tool calls from Send
        tool_calls = input if isinstance(input, list) else [input]
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")
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
                        tc.get("args", {}), config=config
                    )
                else:
                    # Callable
                    result = resolved_tool(**tc.get("args", {}))
                    if inspect.iscoroutine(result):
                        result = await result

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

        return {"messages": results}
