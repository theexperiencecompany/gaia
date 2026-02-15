"""
LANGGRAPH BIGTOOL OVERRIDE

This overrides `create_agent` from langgraph_bigtool to support dynamic model configuration
and LangChain AgentMiddleware integration.

WHY THIS EXISTS:
- Need to switch between OpenAI and Gemini models dynamically at runtime
- Extract model_name and provider from config and apply to LLM before tool binding
- Support LangChain's official AgentMiddleware system (before_model, after_model, wrap_model_call, wrap_tool_call)

WHAT'S MODIFIED:
In acall_model():
- Dynamic model configuration from config.configurable
- Middleware execution via MiddlewareExecutor

IMPORT CHANGE REQUIRED:
Replace library import in build_graph.py:
```python
# Change this:
from langgraph_bigtool import create_agent
# To this:
from app.override.langgraph_bigtool.create_agent import create_agent
```

NOTE: Type/linting errors in this file are expected since it's copied from external library.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Send
from langgraph.utils.runnable import RunnableCallable
from langgraph_bigtool.graph import State as _BigtoolState
from langgraph_bigtool.tools import get_default_retrieval_tool, get_store_arg

from app.agents.middleware.executor import MiddlewareExecutor
from app.constants.general import NEW_MESSAGE_BREAKER
from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode
from app.override.langgraph_bigtool.hooks import (
    HookType,
    execute_hooks,
    sync_execute_hooks,
)
from app.override.langgraph_bigtool.utils import (
    RetrieveToolsResult,
    format_selected_tools,
)


def _replace_todos(left: list, right: list) -> list:
    """Last-write-wins reducer for the todos channel."""
    return right


class State(_BigtoolState):
    """Extended state with todos channel for agent task management."""

    todos: Annotated[list, _replace_todos]


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
    middleware: Sequence["AgentMiddleware"] | None = None,
    extra_tools: list[BaseTool] | None = None,
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
        middleware: Optional list of LangChain AgentMiddleware instances. These provide hooks:
            - before_model: Called before each LLM invocation
            - after_model: Called after each LLM response
            - wrap_model_call: Wraps the model invocation
            - wrap_tool_call: Wraps each tool execution (replaces post_tool_hooks)
        extra_tools: Optional list of additional BaseTool instances to bind to the model
            and register with DynamicToolNode (e.g., todo tools from create_todo_tools).
        pre_model_hooks: Optional list of callables to process state before model calls.
            Hooks are executed in sequence as provided. Each hook has signature:
            (state: State, config: RunnableConfig, store: BaseStore) -> State.
        end_graph_hooks: Optional list of callables to handle final processing before graph ends.
            Hooks are executed in sequence as provided. Each hook has signature:
            (state: State, config: RunnableConfig, store: BaseStore) -> State.
    """
    middleware_executor = MiddlewareExecutor(list(middleware)) if middleware else None

    # Extract tools from middleware (e.g., SubagentMiddleware)
    middleware_tools: list[BaseTool] = []
    for mw in middleware or []:
        mw_tools = getattr(mw, "tools", [])
        for tool in mw_tools:
            if isinstance(tool, BaseTool):
                middleware_tools.append(tool)

    # Merge extra_tools (e.g., todo tools via InjectedState)
    if extra_tools:
        middleware_tools.extend(extra_tools)

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

    def call_model(state: State, config: RunnableConfig, *, store: BaseStore) -> State:
        sync_execute_hooks(pre_model_hooks, state, config, store)

        model_configurations = config.get("configurable", {})
        _llm = llm.with_config(configurable=model_configurations)
        selected_tools = [tool_registry[id] for id in state["selected_tool_ids"]]
        initial_tools = [tool_registry[id] for id in (initial_tool_ids or [])]
        tools_to_bind: list[Any] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(selected_tools)
        tools_to_bind.extend(initial_tools)
        tools_to_bind.extend(middleware_tools)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]
        response = llm_with_tools.invoke(state["messages"])

        if not response.tool_calls and not response.content:
            response.content = "Empty response from model."

        if isinstance(response.content, str) and agent_name == "comms_agent":
            response.content = response.content + NEW_MESSAGE_BREAKER

        return {"messages": [response]}  # type: ignore[return-value]

    async def acall_model(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        """Async model invocation with middleware support."""
        state = await execute_hooks(pre_model_hooks, state, config, store)

        if middleware_executor:
            state = await middleware_executor.execute_before_model(state, config, store)

        model_configurations = config.get("configurable", {})
        _llm = llm.with_config(configurable=model_configurations)

        selected_tools = [tool_registry[id] for id in state["selected_tool_ids"]]
        initial_tools = [tool_registry[id] for id in (initial_tool_ids or [])]
        tools_to_bind: list[Any] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(selected_tools)
        tools_to_bind.extend(initial_tools)
        tools_to_bind.extend(middleware_tools)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]

        if middleware_executor and middleware_executor.has_wrap_model_call():
            response = await middleware_executor.wrap_model_invocation(
                model=_llm,
                state=state,
                config=config,
                store=store,
                tools=tools_to_bind,
                invoke_fn=llm_with_tools.ainvoke,
            )
        else:
            response = await llm_with_tools.ainvoke(state["messages"])

        if not response.tool_calls and not response.content:
            response.content = "Empty response from model."

        if isinstance(response.content, str) and agent_name == "comms_agent":
            response.content = response.content + NEW_MESSAGE_BREAKER

        # Build updated state with response for after_model hooks
        updated_state: State = dict(state)  # type: ignore[assignment]
        updated_state["messages"] = list(state.get("messages", [])) + [response]

        # Execute middleware after_model hooks
        if middleware_executor:
            updated_state = await middleware_executor.execute_after_model(
                updated_state, config, store
            )

        # Return partial state update: new message + any keys added by
        # after_model (e.g. todos). Messages use an append reducer, so only
        # return the new response — not the full list.
        result: dict[str, Any] = {"messages": [response]}
        base_keys = {"messages", "selected_tool_ids"}
        for key, value in updated_state.items():
            if key not in base_keys:
                result[key] = value
        return result  # type: ignore[return-value]

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
            if config:
                user_id = config.get("configurable", {}).get("user_id")
                if user_id:
                    kwargs["user_id"] = user_id

            result = retrieve_tools.invoke(kwargs, config=config)

            # Handle both RetrieveToolsResult dict and plain list
            if isinstance(result, dict):
                tools_to_bind = result.get("tools_to_bind", [])
                response = result.get("response", [])
            else:
                tools_to_bind = result if isinstance(result, list) else []
                response = tools_to_bind

            # Filter out subagent: prefixed tools from binding
            filtered_bind = [
                tool_id
                for tool_id in tools_to_bind
                if not tool_id.startswith("subagent:")
            ]
            selected_tools[tool_call["id"]] = filtered_bind
            response_tools[tool_call["id"]] = response

        tool_messages, _ = format_selected_tools(response_tools, tool_registry)  # type: ignore[arg-type]
        _, bind_ids = format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
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
            if config:
                user_id = config.get("configurable", {}).get("user_id")
                if user_id:
                    kwargs["user_id"] = user_id

            result = await retrieve_tools.ainvoke(kwargs, config=config)

            # Handle both RetrieveToolsResult dict and plain list
            if isinstance(result, dict):
                tools_to_bind = result.get("tools_to_bind", [])
                response = result.get("response", [])
            else:
                tools_to_bind = result if isinstance(result, list) else []
                response = tools_to_bind

            # Filter out subagent: prefixed tools from binding
            filtered_bind = [
                tool_id
                for tool_id in tools_to_bind
                if not tool_id.startswith("subagent:")
            ]
            selected_tools[tool_call["id"]] = filtered_bind
            response_tools[tool_call["id"]] = response

        tool_messages, _ = format_selected_tools(response_tools, tool_registry)  # type: ignore[arg-type]
        _, bind_ids = format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]

    def execute_end_graph_hooks_node(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        return sync_execute_hooks(end_graph_hooks, state, config, store)

    async def aexecute_end_graph_hooks_node(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        return await execute_hooks(end_graph_hooks, state, config, store)

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
                    # Tool args injection handled internally by ToolNode during execution
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

    tool_node = DynamicToolNode(
        tool_registry,  # type: ignore[arg-type]
        middleware_executor=middleware_executor,
        middleware_tools=middleware_tools,
    )

    builder.set_entry_point("agent")
    builder.add_node("agent", RunnableCallable(call_model, acall_model))
    if not disable_retrieve_tools:
        builder.add_node("select_tools", select_tools_node)  # type: ignore[possibly-undefined]
    builder.add_node("tools", tool_node)

    path_map = ["tools", END]
    if not disable_retrieve_tools:
        path_map.insert(0, "select_tools")
    if end_graph_hooks:
        builder.add_node(
            "end_graph_hooks",
            RunnableCallable(
                execute_end_graph_hooks_node, aexecute_end_graph_hooks_node
            ),
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
