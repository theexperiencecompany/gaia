"""
LANGGRAPH BIGTOOL OVERRIDE

This overrides `create_agent` from langgraph_bigtool to support dynamic model configuration.

WHY THIS EXISTS:
- Need to switch between OpenAI and Gemini models dynamically at runtime
- Extract model_name and provider from config and apply to LLM before tool binding

WHAT'S MODIFIED:
In call_model() and acall_model():
```python
# Added dynamic model configuration:
model_name = config.get("configurable").get("model_name", "gpt-4o-mini")
provider = config.get("configurable").get("provider", None)
_llm = llm.with_config(configurable={"model_name": model_name, "provider": provider})
```

IMPORT CHANGE REQUIRED:
Replace library import intool_to build_graph.py:
```python
# Change this:
from langgraph_bigtool import create_agent
# To this:
from app.override.langgraph_bigtool.create_agent import create_agent
```

NOTE: Type/linting errors in this file are expected since it's copied from external library.
"""

import asyncio
import inspect
from collections.abc import Mapping
from typing import Any, Awaitable, Callable, TypedDict, Union

from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import Send
from langgraph.utils.runnable import RunnableCallable
from langgraph_bigtool.graph import State
from langgraph_bigtool.tools import get_default_retrieval_tool, get_store_arg

from app.constants.general import NEW_MESSAGE_BREAKER


class DynamicToolNode(ToolNode):
    """
    A ToolNode that supports dynamically added tools.

    Wraps a tool_registry (DynamicToolDict) and looks up tools at execution time,
    allowing tools added after graph compilation to be executed.

    Also auto-emits structured progress messages with tool category for frontend
    icon display.
    """

    def __init__(self, tool_registry: Mapping[str, BaseTool | Callable], **kwargs):
        # Initialize with current tools
        super().__init__(list(tool_registry.values()), **kwargs)
        self._tool_registry = tool_registry

    def _get_tool(self, name: str) -> BaseTool | Callable | None:
        """Look up tool dynamically from registry."""
        # First try the registry (includes dynamically added tools)
        if name in self._tool_registry:
            return self._tool_registry[name]
        # Fall back to parent's tools_by_name
        return self.tools_by_name.get(name)

    async def _afunc(self, input, config, **kwargs):
        """Override to inject dynamically added tools before execution."""
        # Sync tools_by_name with current registry state before execution
        for name in self._tool_registry:
            if name not in self.tools_by_name:
                self.tools_by_name[name] = self._tool_registry[name]

        return await super()._afunc(input, config, **kwargs)


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function."""

    tools_to_bind: list[str]
    response: list[str]


def _format_selected_tools(
    selected_tools: dict, tool_registry: dict[str, BaseTool]
) -> tuple[list[ToolMessage], list[str]]:
    """Format selected tools, gracefully handling tools not in registry (like subagent: prefixed).

    Args:
        selected_tools: Dict mapping tool_call_id to list of tool IDs
        tool_registry: Dict mapping tool ID to tool instance

    Returns:
        Tuple of (tool_messages, tool_ids) where tool_messages show available tools
        and tool_ids are the IDs to bind
    """
    tool_messages = []
    tool_ids = []
    for tool_call_id, batch in selected_tools.items():
        tool_names = []
        for result in batch:
            # Handle tools that exist in registry
            if result in tool_registry:
                if isinstance(tool_registry[result], BaseTool):
                    tool_names.append(tool_registry[result].name)
                else:
                    tool_names.append(
                        getattr(tool_registry[result], "__name__", result)
                    )
            else:
                # Handle tools not in registry (e.g., subagent: prefixed)
                tool_names.append(result)

        tool_messages.append(
            ToolMessage(f"Available tools: {tool_names}", tool_call_id=tool_call_id)
        )
        tool_ids.extend(batch)

    return tool_messages, tool_ids


HookType = Union[
    Callable[[State, RunnableConfig, BaseStore], State],
    Callable[[State, RunnableConfig, BaseStore], Awaitable[State]],
]


async def _execute_hooks(
    hooks: list[HookType] | None,
    state: State,
    config: RunnableConfig,
    store: BaseStore,
) -> State:
    """Execute post-model hooks conditionally based on agent type."""
    if not hooks:
        return state

    for hook in hooks:
        result = hook(state, config, store)
        if inspect.iscoroutine(result):
            state = await result  # type: ignore[misc]
        else:
            state = result  # type: ignore[assignment]
    return state


def _sync_execute_hooks(
    hooks: list[HookType] | None,
    state: State,
    config: RunnableConfig,
    store: BaseStore,
) -> State:
    """Execute post-model hooks conditionally based on agent type in sync context."""
    if not hooks:
        return state

    async def _run_with_hooks():
        return await _execute_hooks(hooks, state, config, store)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        state = loop.run_until_complete(_run_with_hooks())
    finally:
        loop.close()

    return state


def create_agent(
    llm: LanguageModelLike,
    tool_registry: Mapping[str, BaseTool | Callable],
    *,
    limit: int = 2,
    filter: dict[str, Any] | None = None,
    namespace_prefix: tuple[str, ...] = ("tools",),
    retrieve_tools_function: Callable[..., RetrieveToolsResult] | None = None,
    retrieve_tools_coroutine: Callable[..., Awaitable[RetrieveToolsResult]]
    | None = None,
    initial_tool_ids: list[str] | None = None,
    disable_retrieve_tools: bool = False,
    context_schema=None,
    agent_name: str = "main_agent",
    pre_model_hooks: list[HookType] | None = None,
    end_graph_hooks: list[HookType] | None = None,
) -> StateGraph:
    """Create an agent with a registry of tools.

    The agent will function as a typical ReAct agent, but is equipped with a tool
    for retrieving tools from a registry. The agent will start with only this tool.
    As it is executed, retrieved tools will be bound to the model.

    Args:
        llm: Language model to use for the agent.
        tool_registry: a dict mapping string IDs to tools or callables.
        limit: Maximum number of tools to retrieve with each tool selection step.
        filter: Optional key-value pairs with which to filter results.
        namespace_prefix: Hierarchical path prefix to search within the Store. Defaults
            to ("tools",).
        retrieve_tools_function: Optional function to use for retrieving tools. This
            function should return a list of tool IDs. If not specified, uses semantic
            against the Store with limit, filter, and namespace_prefix set above.
        retrieve_tools_coroutine: Optional coroutine to use for retrieving tools. This
            function should return a list of tool IDs. If not specified, uses semantic
            against the Store with limit, filter, and namespace_prefix set above.
        initial_tool_ids: Optional list of tool IDs to bind directly without using retrieve_tools.
            If provided, these tools will be bound from the start and no retrieve_tools mechanism
            will be used. This improves performance by eliminating the tool retrieval step.
        disable_retrieve_tools: If True, do not bind or use the retrieve_tools mechanism at all.
            This disables tool retrieval and select_tools path; only initially bound tools and
            any already-selected tools will be available.
        pre_model_hooks: Optional list of callables to process state after model calls.
            Hooks are executed in sequence as provided. Each hook has signature:
            (state: State, config: RunnableConfig, store: BaseStore) -> State.
        end_graph_hooks: Optional list of callables to handle final processing before graph ends.
            Hooks are executed in sequence as provided. Each hook has signature:
            (state: State, config: RunnableConfig, store: BaseStore) -> State.
    """
    retrieve_tools: StructuredTool | None = None
    store_arg = None
    if not disable_retrieve_tools:
        if retrieve_tools_function is None and retrieve_tools_coroutine is None:
            retrieve_tools_function, retrieve_tools_coroutine = (
                get_default_retrieval_tool(namespace_prefix, limit=limit, filter=filter)
            )
        retrieve_tools = StructuredTool.from_function(
            func=retrieve_tools_function, coroutine=retrieve_tools_coroutine
        )
        store_arg = get_store_arg(retrieve_tools)

    def execute_end_graph_hooks(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        return _sync_execute_hooks(end_graph_hooks, state, config, store)

    async def aexecute_end_graph_hooks(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        return await _execute_hooks(end_graph_hooks, state, config, store)

    def call_model(state: State, config: RunnableConfig, *, store: BaseStore) -> State:
        _sync_execute_hooks(end_graph_hooks, state, config, store)

        model_configurations = config.get("configurable", {})
        _llm = llm.with_config(configurable=model_configurations)
        selected_tools = [tool_registry[id] for id in state["selected_tool_ids"]]
        initial_tools = [tool_registry[id] for id in (initial_tool_ids or [])]
        tools_to_bind: list[Any] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(selected_tools)
        tools_to_bind.extend(initial_tools)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]
        response = llm_with_tools.invoke(state["messages"])

        if not response.tool_calls and not response.content:
            response.content = "Empty response from model."

        if isinstance(response.content, str) and agent_name == "comms_agent":
            response.content = response.content + NEW_MESSAGE_BREAKER

        response.additional_kwargs = {"visible_to": {agent_name}}
        return {"messages": [response]}  # type: ignore[return-value]

    async def acall_model(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        state = await _execute_hooks(
            pre_model_hooks,
            state,
            config,
            store,
        )

        model_configurations = config.get("configurable", {})
        _llm = llm.with_config(configurable=model_configurations)
        selected_tools = [tool_registry[id] for id in state["selected_tool_ids"]]
        initial_tools = [tool_registry[id] for id in (initial_tool_ids or [])]
        tools_to_bind: list[Any] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(selected_tools)
        tools_to_bind.extend(initial_tools)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]
        response: AIMessage = await llm_with_tools.ainvoke(state["messages"])

        if not response.tool_calls and not response.content:
            response.content = "Empty response from model."

        if isinstance(response.content, str) and agent_name == "comms_agent":
            response.content = response.content + NEW_MESSAGE_BREAKER

        response.additional_kwargs = {"visible_to": {agent_name}}
        return {"messages": [response]}  # type: ignore[return-value]

    # Use DynamicToolNode to support tools added after graph compilation
    tool_node = DynamicToolNode(tool_registry)  # type: ignore[arg-type]

    def select_tools(
        tool_calls: list[dict], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        if retrieve_tools is None:
            raise RuntimeError(
                "retrieve_tools is disabled and select_tools should not be called"
            )
        selected_tools = {}
        response_tools = {}
        for tool_call in tool_calls:
            kwargs = {**tool_call["args"]}
            if store_arg:
                kwargs[store_arg] = store
            # Pass config for user_id extraction and namespace filtering
            # Explicitly pass user_id in kwargs if available in config
            if config:
                user_id = config.get("configurable", {}).get("user_id")
                if user_id:
                    kwargs["user_id"] = user_id

            result = retrieve_tools.invoke(kwargs, config=config)

            # Handle both RetrieveToolsResult dict and plain list (from default langgraph_bigtool)
            if isinstance(result, dict):
                tools_to_bind = result.get("tools_to_bind", [])
                response = result.get("response", [])
            else:
                # Default langgraph_bigtool returns list[str]
                tools_to_bind = result if isinstance(result, list) else []
                response = tools_to_bind

            # Filter out subagent: prefixed tools from binding
            filtered_bind = [
                tool_id
                for tool_id in tools_to_bind
                if not tool_id.startswith("subagent:")
            ]
            selected_tools[tool_call["id"]] = filtered_bind
            response_tools[tool_call["id"]] = response  # Keep all tools in response

        tool_messages, tool_ids = _format_selected_tools(response_tools, tool_registry)  # type: ignore[arg-type]
        _, bind_ids = _format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]

    async def aselect_tools(
        tool_calls: list[dict], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        if retrieve_tools is None:
            raise RuntimeError(
                "retrieve_tools is disabled and aselect_tools should not be called"
            )
        selected_tools = {}
        response_tools = {}
        for tool_call in tool_calls:
            kwargs = {**tool_call["args"]}
            if store_arg:
                kwargs[store_arg] = store
            # Pass config for user_id extraction and namespace filtering
            # Explicitly pass user_id in kwargs if available in config
            if config:
                user_id = config.get("configurable", {}).get("user_id")
                if user_id:
                    kwargs["user_id"] = user_id

            result = await retrieve_tools.ainvoke(kwargs, config=config)

            # Handle both RetrieveToolsResult dict and plain list (from default langgraph_bigtool)
            if isinstance(result, dict):
                tools_to_bind = result.get("tools_to_bind", [])
                response = result.get("response", [])
            else:
                # Default langgraph_bigtool returns list[str]
                tools_to_bind = result if isinstance(result, list) else []
                response = tools_to_bind

            # Filter out subagent: prefixed tools from binding
            filtered_bind = [
                tool_id
                for tool_id in tools_to_bind
                if not tool_id.startswith("subagent:")
            ]
            selected_tools[tool_call["id"]] = filtered_bind
            response_tools[tool_call["id"]] = response  # Keep all tools in response

        tool_messages, tool_ids = _format_selected_tools(response_tools, tool_registry)  # type: ignore[arg-type]
        _, bind_ids = _format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]

    def should_continue(state: State, *, store: BaseStore):
        messages = state["messages"]
        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return "end_graph_hooks" if end_graph_hooks else END
        else:
            destinations = []
            for call in last_message.tool_calls:
                if retrieve_tools is not None and call["name"] == retrieve_tools.name:
                    destinations.append(Send("select_tools", [call]))
                else:
                    # tool_call = tool_node._inject_tool_args(call, state, store)  # type: ignore[arg-type]
                    # destinations.append(Send("tools", [tool_call]))
                    # Tool args injection is now handled internally by ToolNode during execution
                    destinations.append(Send("tools", [call]))

            return destinations

    builder = StateGraph(State, context_schema=context_schema)

    if not disable_retrieve_tools:
        if retrieve_tools_function is not None and retrieve_tools_coroutine is not None:
            select_tools_node = RunnableCallable(select_tools, aselect_tools)
        elif retrieve_tools_function is not None and retrieve_tools_coroutine is None:
            select_tools_node = select_tools  # type: ignore[assignment]
        elif retrieve_tools_coroutine is not None and retrieve_tools_function is None:
            select_tools_node = aselect_tools  # type: ignore[assignment]
        else:
            raise ValueError(
                "One of retrieve_tools_function or retrieve_tools_coroutine must be "
                "provided."
            )

    builder.set_entry_point("agent")

    builder.add_node("agent", RunnableCallable(call_model, acall_model))
    if not disable_retrieve_tools:
        builder.add_node("select_tools", select_tools_node)  # type: ignore[call-arg]
    builder.add_node("tools", tool_node)

    path_map = ["tools", END]
    if not disable_retrieve_tools:
        path_map.insert(0, "select_tools")
    if end_graph_hooks:
        builder.add_node(
            "end_graph_hooks",
            RunnableCallable(execute_end_graph_hooks, aexecute_end_graph_hooks),
        )
        builder.add_edge("end_graph_hooks", END)
        path_map.append("end_graph_hooks")

    builder.add_conditional_edges(
        "agent",
        should_continue,
        path_map=path_map,
    )

    builder.add_edge("tools", "agent")
    if not disable_retrieve_tools:
        builder.add_edge("select_tools", "agent")

    return builder
