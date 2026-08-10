"""
LANGGRAPH BIGTOOL OVERRIDE

This overrides `create_agent` from langgraph_bigtool to support dynamic model configuration
and LangChain AgentMiddleware integration.

WHY THIS EXISTS:
- Need to switch between OpenAI and Gemini models dynamically at runtime
- Extract model_name and provider from config and apply to LLM before tool binding
- Support LangChain's official AgentMiddleware system (before_model, after_model, wrap_model_call, wrap_tool_call)

WHAT'S MODIFIED:
In acall_model() (nodes.py):
- Dynamic model configuration from config.configurable
- Middleware execution via MiddlewareExecutor

Node bodies live in nodes.py; this module wires them into the StateGraph.

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

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import LanguageModelLike
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, StructuredTool

# Imported from the defining module, as langgraph's own prebuilt/ package does.
# langgraph.utils.runnable is a compat shim ("to be removed in v1" — we are on
# 1.2.7) that re-exports without __all__, so it is both deprecated and invisible
# to no_implicit_reexport.
from langgraph._internal._runnable import RunnableCallable
from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy
from langgraph_bigtool.tools import get_default_retrieval_tool, get_store_arg

from app.agents.llm.client import get_default_llm
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.middleware.executor import MiddlewareExecutor
from app.constants.general import FINISH_TASK_NAME
from app.override.langgraph_bigtool.dynamic_tool_node import (
    DynamicToolNode,
    format_tool_error,
    hil_and_timeout_guarded_tool_call,
)
from app.override.langgraph_bigtool.hooks import HookType
from app.override.langgraph_bigtool.nodes import (
    afinish_task_node,
    areject_unbound_tools,
    finish_task_node,
    make_bound_tool_names,
    make_build_tools_to_bind,
    make_dispatch_tools,
    make_end_graph_hooks_nodes,
    make_executable_calls,
    make_model_nodes,
    make_select_tools_nodes,
    make_should_continue,
    reject_unbound_tools,
)
from app.override.langgraph_bigtool.utils import RetrieveToolsResult, State

RetrieveToolsResponse = RetrieveToolsResult | list[str]


def create_agent(
    llm: LanguageModelLike,
    tool_registry: Mapping[str, BaseTool],
    *,
    limit: int = 2,
    filter: dict[str, Any] | None = None,
    namespace_prefix: tuple[str, ...] = ("tools",),
    retrieve_tools_function: Callable[..., RetrieveToolsResponse] | None = None,
    retrieve_tools_coroutine: Callable[..., Awaitable[RetrieveToolsResponse]] | None = None,
    initial_tool_ids: list[str] | None = None,
    disable_retrieve_tools: bool = False,
    context_schema: type[Any] | None = None,
    agent_name: str = "main_agent",
    middleware: Sequence["AgentMiddleware"] | None = None,
    pre_model_hooks: list[HookType] | None = None,
    end_graph_hooks: list[HookType] | None = None,
) -> StateGraph:
    """Create an agent with a registry of tools.

    The agent will function as a typical ReAct agent, but is equipped with a tool
    for retrieving tools from a registry. The agent will start with only this tool.
    As it is executed, retrieved tools will be bound to the model.

    Args:
        llm: Language model to use for the agent.
        tool_registry: a dict mapping string IDs to BaseTool instances.
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

    retrieve_tools: StructuredTool | None = None
    store_arg = None
    if not disable_retrieve_tools:
        if retrieve_tools_function is None and retrieve_tools_coroutine is None:
            retrieve_tools_function, retrieve_tools_coroutine = get_default_retrieval_tool(
                namespace_prefix, limit=limit, filter=filter
            )
        retrieve_tools = StructuredTool.from_function(
            func=retrieve_tools_function, coroutine=retrieve_tools_coroutine
        )
        store_arg = get_store_arg(retrieve_tools)

    # Default model used as the last-resort fallback when the selected model
    # keeps failing; None when Google isn't configured (fallback then skipped).
    try:
        fallback_llm: Runnable | None = get_default_llm()
    except LLMNotConfiguredError:
        fallback_llm = None

    build_tools_to_bind = make_build_tools_to_bind(
        tool_registry, retrieve_tools, middleware_tools, initial_tool_ids
    )
    call_model, acall_model = make_model_nodes(
        llm, agent_name, pre_model_hooks, middleware_executor, build_tools_to_bind, fallback_llm
    )
    select_tools, aselect_tools = make_select_tools_nodes(retrieve_tools, store_arg, tool_registry)
    execute_end_graph_hooks_node, aexecute_end_graph_hooks_node = make_end_graph_hooks_nodes(
        end_graph_hooks
    )
    get_bound_tool_names = make_bound_tool_names(
        retrieve_tools, tool_registry, initial_tool_ids, middleware_tools
    )
    executable_calls = make_executable_calls(get_bound_tool_names, retrieve_tools)
    dispatch_tools = make_dispatch_tools(executable_calls)
    should_continue = make_should_continue(
        get_bound_tool_names, retrieve_tools, dispatch_tools, bool(end_graph_hooks)
    )

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
                "One of retrieve_tools_function or retrieve_tools_coroutine must be provided."
            )

    tool_node = DynamicToolNode(
        tool_registry,  # type: ignore[arg-type]
        middleware_executor=middleware_executor,
        middleware_tools=middleware_tools,
        # Parent-routed tools (InjectedState / middleware tools) previously
        # re-raised non-validation exceptions and crashed the whole run;
        # convert every failure into an error ToolMessage, matching the
        # middleware dispatch path. The per-call timeout wrapper bounds hung
        # tools (orchestration tools exempt).
        handle_tool_errors=format_tool_error,
        awrap_tool_call=hil_and_timeout_guarded_tool_call,
    )

    builder.set_entry_point("agent")
    builder.add_node(
        "agent",
        RunnableCallable(call_model, acall_model),
    )
    if not disable_retrieve_tools:
        # Tool retrieval is a pure read (Chroma/Postgres searches), so the
        # default retry predicate is safe here. The tools node deliberately has
        # NO retry policy: exceptions escaping it come from parent-routed tool
        # execution, and re-running a side-effectful tool can double-execute it.
        builder.add_node(
            "select_tools",
            select_tools_node,  # type: ignore[possibly-undefined]
            retry_policy=RetryPolicy(),
        )
    builder.add_node("tools", tool_node)
    builder.add_node(
        FINISH_TASK_NAME,
        RunnableCallable(finish_task_node, afinish_task_node),
    )
    builder.add_node(
        "reject_unbound_tools",
        RunnableCallable(reject_unbound_tools, areject_unbound_tools),
    )

    path_map = ["tools", FINISH_TASK_NAME, "reject_unbound_tools", END]
    if not disable_retrieve_tools:
        path_map.insert(0, "select_tools")
    if end_graph_hooks:
        builder.add_node(
            "end_graph_hooks",
            RunnableCallable(execute_end_graph_hooks_node, aexecute_end_graph_hooks_node),
        )
        builder.add_edge("end_graph_hooks", END)
        path_map.append("end_graph_hooks")

    builder.add_conditional_edges(
        "agent",
        should_continue,
        path_map=path_map,
    )

    builder.add_edge("tools", "agent")
    builder.add_edge(
        FINISH_TASK_NAME,
        "end_graph_hooks" if end_graph_hooks else END,
    )
    builder.add_edge("reject_unbound_tools", "agent")
    if not disable_retrieve_tools:
        builder.add_edge("select_tools", "agent")

    return builder
