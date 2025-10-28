"""
LANGGRAPH BIGTOOL OVERRIDE

This overrides `create_agent` from langgraph_bigtool to support dynamic model configuration.

WHY THIS EXISTS:
- Need to switch between OpenAI, Gemini, and Cerebras models dynamically at runtime
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
import re
from typing import Any, Awaitable, Callable, Union

from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import Send
from langgraph.utils.runnable import RunnableCallable
from langgraph_bigtool.graph import State, _format_selected_tools
from langgraph_bigtool.tools import get_default_retrieval_tool, get_store_arg

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

    # Run async hooks in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        state = loop.run_until_complete(_run_with_hooks())
    finally:
        loop.close()

    return state


def create_agent(
    llm: LanguageModelLike,
    tool_registry: dict[str, BaseTool | Callable],
    *,
    limit: int = 2,
    filter: dict[str, Any] | None = None,
    namespace_prefix: tuple[str, ...] = ("tools",),
    retrieve_tools_function: Callable[..., list[str]] | None = None,
    retrieve_tools_coroutine: Callable[..., Awaitable[list[str]]] | None = None,
    initial_tool_ids: list[str] | None = None,
    disable_retrieve_tools: bool = False,
    context_schema=None,
    agent_name: str = "main_agent",
    sub_agents: dict[str, Union[CompiledStateGraph, RunnableCallable]] = {},
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
        is_sub_agent: Whether this agent is a sub-agent (affects hook execution).
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
        # If needed, get argument name to inject Store
        store_arg = get_store_arg(retrieve_tools)

    def execute_end_graph_hooks(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        # For sync context, we need to run hooks in a new event loop
        return _sync_execute_hooks(end_graph_hooks, state, config, store)

    def call_model(state: State, config: RunnableConfig, *, store: BaseStore) -> State:
        # For sync context, we need to run hooks in a new event loop
        _sync_execute_hooks(end_graph_hooks, state, config, store)

        model_configurations = config.get("configurable", {}).get(
            "model_configurations", {}
        )
        model_name = model_configurations.get("model_name", "gpt-4o-mini")
        provider = model_configurations.get("provider", None)

        _llm = llm.with_config(
            configurable={
                "model_name": model_name,
                "model": model_name,  # Gemini uses "model" instead of "model_name"
                "provider": provider,
            }
        )
        selected_tools = [tool_registry[id] for id in state["selected_tool_ids"]]
        initial_tools = [tool_registry[id] for id in (initial_tool_ids or [])]
        tools_to_bind: list[Any] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(selected_tools)
        tools_to_bind.extend(initial_tools)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[arg-type]
        response = llm_with_tools.invoke(state["messages"])

        # Set the name for the response for filtering
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

        model_configurations = config.get("configurable", {}).get(
            "model_configurations", {}
        )
        model_name = model_configurations.get("model_name", "gpt-4o-mini")
        provider = model_configurations.get("provider", None)
        selected_tools = [tool_registry[id] for id in state["selected_tool_ids"]]
        initial_tools = [tool_registry[id] for id in (initial_tool_ids or [])]
        _llm = llm.with_config(
            configurable={"model_name": model_name, "provider": provider}
        )
        tools_to_bind: list[Any] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(selected_tools)
        tools_to_bind.extend(initial_tools)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[arg-type]
        response = await llm_with_tools.ainvoke(state["messages"])

        # Set the name for the response for filtering
        response.additional_kwargs = {"visible_to": {agent_name}}
        return {"messages": [response]}  # type: ignore[return-value]

    tool_node = ToolNode(tool for tool in tool_registry.values())  # type: ignore[arg-type]

    def select_tools(
        tool_calls: list[dict], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        assert retrieve_tools is not None, (
            "retrieve_tools is disabled and select_tools should not be called"
        )
        selected_tools = {}
        for tool_call in tool_calls:
            kwargs = {**tool_call["args"]}
            if store_arg:
                kwargs[store_arg] = store
            result = retrieve_tools.invoke(kwargs)
            selected_tools[tool_call["id"]] = result

        tool_messages, tool_ids = _format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": tool_ids}  # type: ignore[return-value]

    async def aselect_tools(
        tool_calls: list[dict], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        assert retrieve_tools is not None, (
            "retrieve_tools is disabled and aselect_tools should not be called"
        )
        selected_tools = {}
        for tool_call in tool_calls:
            kwargs = {**tool_call["args"]}
            if store_arg:
                kwargs[store_arg] = store
            result = await retrieve_tools.ainvoke(kwargs)
            selected_tools[tool_call["id"]] = result

        tool_messages, tool_ids = _format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": tool_ids}  # type: ignore[return-value]

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
                    tool_call = tool_node.inject_tool_args(call, state, store)  # type: ignore[arg-type]
                    destinations.append(Send("tools", [tool_call]))

            return destinations

    builder = StateGraph(State, context_schema=context_schema)

    if not disable_retrieve_tools:
        if retrieve_tools_function is not None and retrieve_tools_coroutine is not None:
            select_tools_node = RunnableCallable(select_tools, aselect_tools)
        elif retrieve_tools_function is not None and retrieve_tools_coroutine is None:
            select_tools_node = select_tools
        elif retrieve_tools_coroutine is not None and retrieve_tools_function is None:
            select_tools_node = aselect_tools
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
        builder.add_node("end_graph_hooks", execute_end_graph_hooks)
        builder.add_edge("end_graph_hooks", END)
        path_map.append("end_graph_hooks")

    builder.add_conditional_edges(
        "agent",
        should_continue,
        path_map=path_map,
    )

    # TODO: Remove this conditional edge if issue #19 is resolved in langgraph_bigtool
    # This is a temporary fix to prevent redundant LLM calls after subagent handoff
    def should_continue_after_tool(state: State):
        # CRITICAL: Prevent LLM call after subagent handoff
        # Issue: https://github.com/langchain-ai/langgraph-bigtool/issues/19
        #
        # When a subagent is called (e.g., "call_gmail_agent"), it adds a ToolMessage
        # with content like "Successfully transferred to gmail". Without this check,
        # the main agent would unnecessarily invoke the LLM again after the handoff.
        # This optimization prevents redundant LLM calls.
        messages = state["messages"]
        last_message = messages[-1]

        if isinstance(last_message, ToolMessage):
            tool_name = last_message.name or "Unknown"
            content = last_message.content or ""
            match_tool = re.match(r"call_(\w+)_agent", tool_name)
            match_content = re.match(r"Successfully transferred to (\w+)", content)  # type: ignore[call-arg]
            if match_tool and match_content:
                return END

        return "agent"

    builder.add_conditional_edges(
        "tools",
        should_continue_after_tool,
        path_map=["agent", END],
    )

    # builder.add_edge("tools", "agent")
    if not disable_retrieve_tools:
        builder.add_edge("select_tools", "agent")

    # Handle sub-agents
    for name, sub_agent in sub_agents.items():
        builder.add_node(name, sub_agent)
        builder.add_edge(name, "agent")

    return builder
