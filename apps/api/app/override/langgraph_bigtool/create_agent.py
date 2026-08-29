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

from collections.abc import Awaitable, Callable, Mapping, Sequence
import dataclasses
import functools
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import LanguageModelLike
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

# Imported from the defining module, as langgraph's own prebuilt/ package does.
# langgraph.utils.runnable is a compat shim ("to be removed in v1" — we are on
# 1.2.7) that re-exports without __all__, so it is both deprecated and invisible
# to no_implicit_reexport.
from langgraph._internal._runnable import RunnableCallable
from langgraph.graph import END, StateGraph
from langgraph.prebuilt.tool_node import ToolCallWithContext
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy, Send
from langgraph_bigtool.tools import get_default_retrieval_tool, get_store_arg

from app.agents.llm.client import LLMInvokeOptions, ainvoke_llm, invoke_llm
from app.agents.llm.lane import ModelLane
from app.agents.middleware.completion import (
    completion_nudges_spent,
    work_looks_unfinished,
)
from app.agents.middleware.executor import MiddlewareExecutor
from app.constants.general import FINISH_TASK_NAME, NEW_MESSAGE_BREAKER
from app.constants.llm import (
    COMPLETION_NUDGE_MESSAGE,
    LANE_FIELD_ID,
    MAX_COMPLETION_NUDGES,
    RECURSION_WRAPUP_THRESHOLD_STEPS,
    STICKY_ROUTING_PROVIDERS,
)
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.override.langgraph_bigtool.agent_config import (
    AgentConfig,
    HookConfig,
    RetrieveToolsResponse,
    ToolRetrievalConfig,
)
from app.override.langgraph_bigtool.dynamic_tool_node import (
    DynamicToolNode,
    ToolNodeOptions,
    format_tool_error,
    hil_and_timeout_guarded_tool_call,
)
from app.override.langgraph_bigtool.hooks import (
    HookType,
    changed_hook_keys,
    execute_hooks,
    sync_execute_hooks,
)
from app.override.langgraph_bigtool.utils import (
    State,
    dedupe_str_list,
    dedupe_tool_bindings,
    format_selected_tools,
    pop_pruned_tombstones,
)
from app.utils.mcp_utils import canonical_tool_name_map
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import log

#: Graph node that answers a tool call the model made without binding the tool.
#: Named here because the router, both edges and the registration must agree —
#: langgraph derives the same name from ``reject_unbound_tools`` itself, so the
#: registration below deliberately does not repeat it.
REJECT_UNBOUND_TOOLS_NODE = "reject_unbound_tools"


@dataclasses.dataclass(frozen=True)
class _AgentDeps:
    """Resolved dependencies the node factories build their closures from."""

    llm: LanguageModelLike
    tool_registry: Mapping[str, BaseTool]
    agent_name: str
    middleware_executor: MiddlewareExecutor | None
    middleware_tools: list[BaseTool]
    retrieve_tools: StructuredTool | None
    store_arg: str | None
    retrieve_tools_function: Callable[..., RetrieveToolsResponse] | None
    retrieve_tools_coroutine: Callable[..., Awaitable[RetrieveToolsResponse]] | None
    initial_tool_ids: list[str] | None
    pre_model_hooks: list[HookType] | None
    end_graph_hooks: list[HookType] | None
    require_finish_to_end: bool


def _fallback_config(config: RunnableConfig, lane: "ModelLane") -> RunnableConfig:
    """``config`` rebound onto ``lane`` — the config the fallback attempt runs under."""
    return cast(
        RunnableConfig,
        {**config, "configurable": lane.rebind(config.get("configurable") or {})},
    )


def _prepare_fallback(
    llm: LanguageModelLike,
    tools_to_bind: list[BaseTool],
    model_configurations: AgentConfigurable,
) -> tuple[Callable[[], Runnable], "ModelLane"] | None:
    """Factory that re-binds this run on the NEXT configured provider, with the
    same tools. Zero-arg so the (per-turn, tool-list-sized) binding only happens
    if the primary actually fails. ``None`` when no other provider is configured.

    The fallback target is a different PROVIDER, not a different model on the
    same one. Falling back to ``get_default_llm()`` was inert in production: it
    was skipped whenever the run already selected the default model, and since
    every tier resolves to that model the graph had no fallback at all — one 402
    or 401 from OpenRouter killed the whole turn on every execution path.
    """
    lane = ModelLane.from_configurable(model_configurations.get(LANE_FIELD_ID))
    fallback_lane = lane.fallback() if lane else None
    if fallback_lane is None:
        return None
    # cast rather than an attr-defined suppression: the registry genuinely holds a
    # tool-binding chat model, LanguageModelLike just doesn't declare bind_tools.
    bindable = cast(BaseChatModel, llm)
    return (lambda: bindable.bind_tools(tools_to_bind), fallback_lane)


def _bind_session_id(
    llm_with_tools: Runnable,
    model_configurations: AgentConfigurable,
    agent_name: str | None = None,
) -> Runnable:
    """Bind the sticky-routing session id onto ``llm_with_tools``, if applicable.

    ``agent_name`` gives each agent CLASS its own cache chain, extending the
    ``-aux`` suffix that already exists for one-shot calls.

    Why: every agent in a turn previously shared the conversation's bare session
    id, so comms, the executor, the subagents and the memory lane all wrote into
    one chain and evicted each other. Measured end-to-end on the real graph, the
    executor — which runs in a burst and re-reads its own chain immediately —
    held 72.2%, while comms, which idles across a turn while the others run,
    collapsed to 26.8%. That comms' own sticky-flip REPLAY of the identical bytes
    read 99.9% seconds later is the proof the bytes were always cacheable: the
    chain existed, something else had taken the slot by the next turn.
    """
    # Must run AFTER bind_tools (which rebuilds the runnable and drops outer bindings), so the
    # call pins to the conversation's provider and its prompt cache chains across turns.
    # Gated on the provider the same way ainvoke_llm gates it: session_id is an
    # OpenRouter routing hint, and Gemini has no stickiness to pin, so sending
    # it there is an unsupported argument on every graph call.
    key = _agent_sticky_key(model_configurations, agent_name)
    return llm_with_tools.bind(session_id=key) if key else llm_with_tools


def _agent_sticky_key(
    model_configurations: AgentConfigurable, agent_name: str | None
) -> str | None:
    """This agent's sticky-routing key for this run, or ``None``.

    One computation, used by the primary's bind AND handed to ``invoke_llm``
    for the fallback. They used to derive it separately — the fallback from
    config, which yields the BARE session id — so a provider hiccup dropped
    every agent back into one shared chain and they resumed evicting each
    other, the exact failure the per-agent key exists to prevent.

    Gated on the provider the same way ainvoke_llm gates it: session_id is an
    OpenRouter routing hint, and Gemini has no stickiness to pin, so sending
    it there is an unsupported argument on every graph call.
    """
    if model_configurations.get("provider") not in STICKY_ROUTING_PROVIDERS:
        return None
    session_id = model_configurations.get("session_id")
    if not session_id:
        return None
    return f"{session_id}-{agent_name}" if agent_name else str(session_id)


def _extract_middleware(
    middleware: Sequence["AgentMiddleware"] | None,
) -> tuple[MiddlewareExecutor | None, list[BaseTool]]:
    executor = MiddlewareExecutor(list(middleware)) if middleware else None

    # Extract tools from middleware (e.g., SubagentMiddleware)
    middleware_tools: list[BaseTool] = []
    for mw in middleware or []:
        mw_tools = getattr(mw, "tools", [])
        for tool in mw_tools:
            if isinstance(tool, BaseTool):
                middleware_tools.append(tool)

    return executor, middleware_tools


def _build_retrieve_tools(
    tools_config: ToolRetrievalConfig,
) -> tuple[StructuredTool | None, str | None]:
    """The retrieve_tools tool plus the store kwarg name it expects to be invoked with."""
    if tools_config.disable_retrieve_tools:
        return None, None

    func = tools_config.retrieve_tools_function
    coroutine = tools_config.retrieve_tools_coroutine
    if func is None and coroutine is None:
        func, coroutine = get_default_retrieval_tool(
            tools_config.namespace_prefix,
            limit=tools_config.limit,
            filter=tools_config.metadata_filter,
        )
    retrieve_tools = StructuredTool.from_function(func=func, coroutine=coroutine)
    return retrieve_tools, get_store_arg(retrieve_tools)


def _maybe_inject_wrapup(state: State) -> State:
    """Warn the model to finish when the recursion budget is nearly spent.

    Injected per model call (never persisted): a trailing HumanMessage,
    because Gemini drops trailing SystemMessages. Without this, the run
    dies mid-exploration with a hard GraphRecursionError the model never
    saw coming.
    """
    remaining = state.get("remaining_steps")
    if not isinstance(remaining, int) or remaining > RECURSION_WRAPUP_THRESHOLD_STEPS:
        return state
    notice = HumanMessage(
        content=(
            "[System notice: you are almost out of steps for this run "
            f"(~{remaining} left). Stop exploring now — summarize what you "
            "found and what remains to be done, and finish your reply.]"
        )
    )
    return cast(State, {**state, "messages": [*state.get("messages", []), notice]})


def _tools_to_bind(deps: _AgentDeps, state: State) -> list[BaseTool]:
    """Assemble the bound-tool list with a cache-stable ordering.

    Fixed tools (``retrieve_tools``, the agent's initial set, middleware)
    are bound first so they form a byte-stable prefix for the whole
    conversation. Dynamically retrieved tools (``selected_tool_ids``, which
    only ever grows via the append-only reducer) are bound LAST, so each
    retrieval appends to the tail instead of shifting the fixed tools. That
    keeps the request's function-declaration prefix stable and lets the
    provider's implicit prompt cache survive across turns instead of
    resetting on every tool retrieval.
    """
    # Skip unknown ids (a stale id in the append-only selected_tool_ids must
    # not crash the model invocation) rather than indexing blindly.
    initial_tools = [
        deps.tool_registry[tool_id]
        for tool_id in (deps.initial_tool_ids or [])
        if tool_id in deps.tool_registry
    ]
    selected_tools = [
        deps.tool_registry[tool_id]
        for tool_id in state["selected_tool_ids"]
        if tool_id in deps.tool_registry
    ]
    tools_to_bind: list[BaseTool] = []
    if deps.retrieve_tools is not None:
        tools_to_bind.append(deps.retrieve_tools)
    tools_to_bind.extend(initial_tools)
    tools_to_bind.extend(deps.middleware_tools)
    tools_to_bind.extend(selected_tools)
    return dedupe_tool_bindings(tools_to_bind)


def _finalize_model_response(response: AIMessage, agent_name: str) -> AIMessage:
    if not response.tool_calls and not response.content:
        response.content = "Empty response from model."

    if isinstance(response.content, str) and agent_name == "comms_agent":
        response.content = response.content + NEW_MESSAGE_BREAKER

    return response


def _log_message_preview(state: State) -> None:
    try:
        recent_messages = state.get("messages", [])[-6:]
        preview = []
        for msg in recent_messages:
            role = msg.__class__.__name__
            # extract_text_content, not the raw content: a tool result carrying
            # inline media holds megabytes of base64 that must never reach a log.
            content = extract_text_content(getattr(msg, "content", ""))
            if len(content) > 200:
                content = content[:197] + "..."
            preview.append({"role": role, "content": content})
        log.info("acall_model message preview", preview=preview)
    except Exception as e:
        log.debug("Failed to log message preview", error_type=type(e).__name__, error=str(e))


def _after_model_result(
    tombstones: list[Any], response: AIMessage, updated_state: State
) -> dict[str, object]:
    # Return partial state update: new message + any keys added by
    # after_model (e.g. todos). Messages use an append reducer, so only
    # return the new response — not the full list. Tombstones prune the
    # slot-stale prompt copies the pre-model hooks dropped, so the
    # checkpointed thread stays bounded too.
    result: dict[str, object] = {"messages": [*tombstones, response]}
    base_keys = {"messages", "selected_tool_ids"}
    result.update({key: value for key, value in updated_state.items() if key not in base_keys})
    return result


def _model_node(deps: _AgentDeps) -> RunnableCallable:
    llm = deps.llm
    middleware_executor = deps.middleware_executor
    pre_model_hooks = deps.pre_model_hooks

    def call_model(state: State, config: RunnableConfig, *, store: BaseStore) -> State:
        state = sync_execute_hooks(pre_model_hooks, state, config, store)
        tombstones = pop_pruned_tombstones(state)

        if middleware_executor:
            raise RuntimeError(
                "Agent middleware is configured but sync execution was requested. "
                "Use the async graph execution path (ainvoke/astream)."
            )

        # The raw bag goes back to LangChain untouched (it owns the keys it
        # merged in); the typed view is what GAIA reads its own keys through.
        _llm = llm.with_config(configurable=config.get("configurable", {}))
        model_configurations = agent_configurable(config)
        tools_to_bind = _tools_to_bind(deps, state)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]  # langchain model-lane stubs omit bind_tools for this lane type
        llm_with_tools = _bind_session_id(llm_with_tools, model_configurations, deps.agent_name)
        prepared = _prepare_fallback(llm, tools_to_bind, model_configurations)
        state = _maybe_inject_wrapup(state)
        response = invoke_llm(
            llm_with_tools,
            state["messages"],
            fallback=prepared[0] if prepared else None,
            config=config,
            label=deps.agent_name,
            options=LLMInvokeOptions(
                fallback_config=_fallback_config(config, prepared[1]) if prepared else None,
                sticky_session_id=_agent_sticky_key(model_configurations, deps.agent_name),
            ),
        )

        return {"messages": [*tombstones, _finalize_model_response(response, deps.agent_name)]}  # type: ignore[return-value]  # helper's declared return is wider than the dict actually built

    async def acall_model(state: State, config: RunnableConfig, *, store: BaseStore) -> State:
        """Async model invocation with middleware support."""
        state = await execute_hooks(pre_model_hooks, state, config, store)
        tombstones = pop_pruned_tombstones(state)

        if middleware_executor:
            state = await middleware_executor.execute_before_model(state, config, store)

        state = _maybe_inject_wrapup(state)

        # The raw bag goes back to LangChain untouched (it owns the keys it
        # merged in); the typed view is what GAIA reads its own keys through.
        _llm = llm.with_config(configurable=config.get("configurable", {}))
        model_configurations = agent_configurable(config)

        tools_to_bind = _tools_to_bind(deps, state)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]  # langchain model-lane stubs omit bind_tools for this lane type
        llm_with_tools = _bind_session_id(llm_with_tools, model_configurations, deps.agent_name)
        prepared = _prepare_fallback(llm, tools_to_bind, model_configurations)
        # LLMAccountingMiddleware already charges this call; auxiliary metering
        # here would book it a second time.
        invoke_fn = functools.partial(
            ainvoke_llm,
            llm_with_tools,
            fallback=prepared[0] if prepared else None,
            config=config,
            label=deps.agent_name,
            options=LLMInvokeOptions(
                meter_auxiliary=False,
                fallback_config=_fallback_config(config, prepared[1]) if prepared else None,
                sticky_session_id=_agent_sticky_key(model_configurations, deps.agent_name),
            ),
        )

        _log_message_preview(state)

        if middleware_executor and middleware_executor.has_wrap_model_call():
            middleware_tools_for_request: list[BaseTool | dict[str, Any]] = [
                tool for tool in tools_to_bind
            ]
            response = await middleware_executor.wrap_model_invocation(
                model=_llm,  # type: ignore[arg-type]  # tool-registry element types are wider than the helper's narrowed params
                state=state,
                config=config,
                store=store,
                tools=middleware_tools_for_request,
                invoke_fn=invoke_fn,
            )
        else:
            response = await invoke_fn(state["messages"])

        response = _finalize_model_response(response, deps.agent_name)

        # Build updated state with response for after_model hooks
        updated_state: State = dict(state)  # type: ignore[assignment]  # langgraph state schema fields are typed loosely upstream
        updated_state["messages"] = list(state.get("messages", [])) + [response]

        # Execute middleware after_model hooks
        if middleware_executor:
            updated_state = await middleware_executor.execute_after_model(
                updated_state, config, store
            )

        return _after_model_result(tombstones, response, updated_state)  # type: ignore[return-value]  # helper's declared return is wider than the dict actually built

    return RunnableCallable(call_model, acall_model)


def _retrieval_call_kwargs(
    tool_call: dict[str, Any],
    store_arg: str | None,
    store: BaseStore,
    config: RunnableConfig,
) -> dict[str, Any]:
    kwargs = {**tool_call["args"]}
    if store_arg:
        kwargs[store_arg] = store
    if config:
        user_id = agent_configurable(config).get("user_id")
        if user_id:
            kwargs["user_id"] = user_id
    return kwargs


def _resolve_retrieval_result(
    result: RetrieveToolsResponse,
    tool_call_id: str,
    response_texts: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Split one retrieve_tools result into (ids to bind, ids to echo back),
    recording any rendered response text under the call's id."""
    # Handle both RetrieveToolsResult dict and plain list
    if isinstance(result, dict):
        tools_to_bind = [
            tool_id for tool_id in result.get("tools_to_bind", []) if isinstance(tool_id, str)
        ]
        response = [tool_id for tool_id in result.get("response", []) if isinstance(tool_id, str)]
        rendered = result.get("response_text")
        if isinstance(rendered, str) and rendered:
            response_texts[tool_call_id] = rendered
    else:
        tools_to_bind = [
            tool_id
            for tool_id in (result if isinstance(result, list) else [])
            if isinstance(tool_id, str)
        ]
        response = tools_to_bind

    # Filter out subagent: prefixed tools from binding
    filtered_bind = [tool_id for tool_id in tools_to_bind if not tool_id.startswith("subagent:")]
    return filtered_bind, response


def _select_tools_node(deps: _AgentDeps) -> RunnableCallable | Callable[..., Any]:
    def select_tools(
        tool_calls: list[dict[str, Any]], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        if deps.retrieve_tools is None:
            raise RuntimeError("retrieve_tools is disabled and select_tools should not be called")

        selected_tools = {}
        response_tools = {}
        response_texts: dict[str, str] = {}
        for tool_call in tool_calls:
            kwargs = _retrieval_call_kwargs(tool_call, deps.store_arg, store, config)
            result = deps.retrieve_tools.invoke(kwargs, config=config)
            filtered_bind, response = _resolve_retrieval_result(
                result, tool_call["id"], response_texts
            )
            selected_tools[tool_call["id"]] = dedupe_str_list(filtered_bind)
            response_tools[tool_call["id"]] = dedupe_str_list(response)

        tool_messages, _ = format_selected_tools(response_tools, deps.tool_registry, response_texts)  # type: ignore[arg-type]  # tool-registry element types are wider than the helper's narrowed params
        _, bind_ids = format_selected_tools(selected_tools, deps.tool_registry)  # type: ignore[arg-type]  # tool-registry element types are wider than the helper's narrowed params
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]  # helper's declared return is wider than the dict actually built

    async def aselect_tools(
        tool_calls: list[dict[str, Any]], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        """Async twin of ``select_tools`` — resolve retrieve_tools calls into bindings."""
        if deps.retrieve_tools is None:
            raise RuntimeError("retrieve_tools is disabled and aselect_tools should not be called")

        selected_tools = {}
        response_tools = {}
        response_texts: dict[str, str] = {}
        for tool_call in tool_calls:
            kwargs = _retrieval_call_kwargs(tool_call, deps.store_arg, store, config)
            result = await deps.retrieve_tools.ainvoke(kwargs, config=config)
            filtered_bind, response = _resolve_retrieval_result(
                result, tool_call["id"], response_texts
            )
            selected_tools[tool_call["id"]] = dedupe_str_list(filtered_bind)
            response_tools[tool_call["id"]] = dedupe_str_list(response)

        tool_messages, _ = format_selected_tools(response_tools, deps.tool_registry, response_texts)  # type: ignore[arg-type]  # tool-registry element types are wider than the helper's narrowed params
        _, bind_ids = format_selected_tools(selected_tools, deps.tool_registry)  # type: ignore[arg-type]  # tool-registry element types are wider than the helper's narrowed params
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]  # helper's declared return is wider than the dict actually built

    select_tools_node: RunnableCallable | Callable[..., Any]
    if deps.retrieve_tools_function is not None and deps.retrieve_tools_coroutine is not None:
        # Custom sync+async retrieval.
        select_tools_node = RunnableCallable(select_tools, aselect_tools)
    elif deps.retrieve_tools_function is not None and deps.retrieve_tools_coroutine is None:
        select_tools_node = select_tools
    elif deps.retrieve_tools_coroutine is not None and deps.retrieve_tools_function is None:
        select_tools_node = aselect_tools
    elif deps.retrieve_tools is not None:
        # Default semantic retrieval: get_default_retrieval_tool supplied BOTH
        # the sync and async functions, so the node needs both paths too.
        select_tools_node = RunnableCallable(select_tools, aselect_tools)
    else:
        raise ValueError(
            "One of retrieve_tools_function or retrieve_tools_coroutine must be provided."
        )
    return select_tools_node


def _end_graph_hooks_node(end_graph_hooks: list[HookType]) -> RunnableCallable:
    def execute_end_graph_hooks_node(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        return changed_hook_keys(state, sync_execute_hooks(end_graph_hooks, state, config, store))

    async def aexecute_end_graph_hooks_node(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        """Run the end-graph hooks; persist only the keys they actually changed."""
        return changed_hook_keys(state, await execute_hooks(end_graph_hooks, state, config, store))

    return RunnableCallable(execute_end_graph_hooks_node, aexecute_end_graph_hooks_node)


def reject_unbound_tools(tool_calls: list[dict[str, Any]], *, store: BaseStore) -> State:  # noqa: ARG001 -- langgraph injects store positionally at graph-execution time
    """Return error ToolMessages for tool calls that were not bound."""
    messages = [
        ToolMessage(
            content=(
                f"Tool '{call['name']}' is not bound. "
                "You must call retrieve_tools(exact_tool_names=['{name}']) "
                "to bind it before calling it.".format(name=call["name"])
            ),
            tool_call_id=call["id"],
            name=call["name"],
        )
        for call in tool_calls
    ]
    return {"messages": messages}  # type: ignore[return-value]  # helper's declared return is wider than the dict actually built


async def areject_unbound_tools(tool_calls: list[dict[str, Any]], *, store: BaseStore) -> State:
    """Async twin of ``reject_unbound_tools`` for the async graph path."""
    return reject_unbound_tools(tool_calls, store=store)


def finish_task_node(tool_calls: list[ToolCall], *, store: BaseStore) -> State:  # noqa: ARG001 -- langgraph injects store positionally at graph-execution time
    messages = []
    for call in tool_calls:
        args = call.get("args", {}) if isinstance(call, dict) else {}
        result = args.get("result")
        content = str(result) if result is not None else "Task completed."
        messages.append(
            ToolMessage(
                content=content,
                tool_call_id=call.get("id", ""),
                name=FINISH_TASK_NAME,
            )
        )
    return {"messages": messages}  # type: ignore[return-value]  # helper's declared return is wider than the dict actually built


async def afinish_task_node(tool_calls: list[ToolCall], *, store: BaseStore) -> State:
    """Async twin of ``finish_task_node`` for the async graph path."""
    return finish_task_node(tool_calls, store=store)


def nudge_continue_node(state: State) -> State:
    # The message IS the tally: completion_nudges_spent counts these back out
    # of the current delegation, so there is no counter to keep in sync.
    del state
    return State(messages=[HumanMessage(content=COMPLETION_NUDGE_MESSAGE)])


def _last_tool_calling_message(state: State) -> AIMessage | None:
    """The AI message whose calls this turn is executing.

    NOT ``messages[-1]``: a resume prepends a current-time HumanMessage
    (``subagent_runner._with_current_time``), so by the time the approvals node has
    paused and woken, the tool-calling message is no longer last. Matches
    ``hil/utils.current_tool_calls``, which the gate resolves siblings with — the two
    must agree on which message is being executed or they gate different call sets.
    """
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage) and message.tool_calls:
            return message
    return None


def _get_bound_tool_names(deps: _AgentDeps, state: State) -> set[str]:
    """Return the set of tool names currently bound to the model."""
    bound: set[str] = set()
    # retrieve_tools itself is always bound when enabled
    if deps.retrieve_tools is not None:
        bound.add(deps.retrieve_tools.name)
    # Tools selected via retrieve_tools
    for tool_id in state.get("selected_tool_ids", []):
        if tool_id in deps.tool_registry:
            bound.add(deps.tool_registry[tool_id].name)
    # Always-bound initial tools
    for tool_id in deps.initial_tool_ids or []:
        if tool_id in deps.tool_registry:
            bound.add(deps.tool_registry[tool_id].name)
    # Middleware tools (e.g. spawn_subagent, plan_tasks)
    for tool in deps.middleware_tools:
        if hasattr(tool, "name"):
            bound.add(tool.name)
    return bound


def _executable_calls(deps: _AgentDeps, state: State) -> list[ToolCall]:
    """The message's tool calls that the tools node will run, names canonicalized.

    Mutates each call's name in place when it maps to a bound tool, so the tools
    node's registry lookup hits the actual BaseTool. Separate from routing because
    both the router and the approvals node's outgoing edge need this same list.
    """
    last_message = _last_tool_calling_message(state)
    if last_message is None:
        return []
    bound_names = _get_bound_tool_names(deps, state)
    canonical_to_bound = canonical_tool_name_map(bound_names)
    runnable: list[ToolCall] = []
    for call in last_message.tool_calls:
        if deps.retrieve_tools is not None and call["name"] == deps.retrieve_tools.name:
            continue
        if call["name"] not in bound_names:
            canonical = canonical_to_bound.get(call["name"].replace("-", "_"))
            if canonical is None:
                continue
            call["name"] = canonical
        runnable.append(call)
    return runnable


def _dispatch_tools(deps: _AgentDeps, state: State) -> list[Send]:
    """Fan the message's calls out to the tools node, one task each.

    ToolCallWithContext carries the full state dict so ToolNode can do InjectedState
    injection. Each call becomes its own task, and a task that pauses for approval
    leaves its completed siblings alone — LangGraph persists their writes.
    """
    return [
        Send(
            "tools",
            ToolCallWithContext(__type="tool_call_with_context", tool_call=call, state=state),
        )
        for call in _executable_calls(deps, state)
    ]


def _should_continue(deps: _AgentDeps) -> Callable[..., str | Send | list[Send]]:
    def should_continue(
        state: State,
        *,
        store: BaseStore,  # noqa: ARG001 -- langgraph injects store positionally at graph-execution time
    ) -> str | Send | list[Send]:
        messages = state["messages"]
        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            # The model is trying to end by replying in plain text. For the
            # executor (require_finish_to_end), don't take that at face value
            # when work is demonstrably unfinished — nudge once and loop instead
            # of ending early. Bounded by MAX_COMPLETION_NUDGES so a genuinely
            # tool-free answer can't loop. Comms never opts in and ends normally.
            if (
                deps.require_finish_to_end
                and completion_nudges_spent(state) < MAX_COMPLETION_NUDGES
                and work_looks_unfinished(state)
            ):
                return "nudge_continue"
            return "end_graph_hooks" if deps.end_graph_hooks else END
        bound_names = _get_bound_tool_names(deps, state)
        canonical_to_bound = canonical_tool_name_map(bound_names)
        destinations: list[Send] = []
        unbound_calls: list[ToolCall] = []

        finish_calls: list[ToolCall] = [
            call for call in last_message.tool_calls if call.get("name") == FINISH_TASK_NAME
        ]
        if finish_calls:
            return Send(FINISH_TASK_NAME, finish_calls)

        for call in last_message.tool_calls:
            if deps.retrieve_tools is not None and call["name"] == deps.retrieve_tools.name:
                destinations.append(Send("select_tools", [call]))
                continue
            if call["name"] not in bound_names and not canonical_to_bound.get(
                call["name"].replace("-", "_")
            ):
                unbound_calls.append(call)

        # ONE task for the whole message, and it runs before any tool: the approvals node
        # settles every HIL decision in its own superstep, then fans out to the tools node.
        # Sending straight to "tools" here is what used to let an ungated call execute
        # beside one that paused — and a pause discards and replays that whole step.
        destinations.extend(_dispatch_tools(deps, state))

        if unbound_calls:
            destinations.append(Send(REJECT_UNBOUND_TOOLS_NODE, unbound_calls))

        return destinations

    return should_continue


def _tool_node(deps: _AgentDeps) -> DynamicToolNode:
    return DynamicToolNode(
        deps.tool_registry,
        ToolNodeOptions(
            # Parent-routed tools (InjectedState / middleware tools) previously
            # re-raised non-validation exceptions and crashed the whole run;
            # convert every failure into an error ToolMessage, matching the
            # middleware dispatch path. The per-call timeout wrapper bounds
            # hung tools (orchestration tools exempt).
            handle_tool_errors=format_tool_error,
            awrap_tool_call=hil_and_timeout_guarded_tool_call,
        ),
        middleware_executor=deps.middleware_executor,
        middleware_tools=deps.middleware_tools,
    )


def _wire_edges(builder: StateGraph, deps: _AgentDeps) -> None:
    retrieve_enabled = deps.retrieve_tools is not None

    path_map = ["tools", FINISH_TASK_NAME, REJECT_UNBOUND_TOOLS_NODE, END]
    if retrieve_enabled:
        path_map.insert(0, "select_tools")
    if deps.require_finish_to_end:
        builder.add_node(
            "nudge_continue",
            # Sync-only: the node ignores state and just emits the nudge, and
            # RunnableCallable runs a sync func on ainvoke when no async twin
            # is given — the twin was a pass-through with nothing to add.
            RunnableCallable(nudge_continue_node),
        )
        builder.add_edge("nudge_continue", "agent")
        path_map.append("nudge_continue")
    if deps.end_graph_hooks:
        builder.add_node("end_graph_hooks", _end_graph_hooks_node(deps.end_graph_hooks))
        builder.add_edge("end_graph_hooks", END)
        path_map.append("end_graph_hooks")

    builder.add_conditional_edges(
        "agent",
        _should_continue(deps),
        path_map=path_map,
    )

    builder.add_edge("tools", "agent")
    builder.add_edge(
        FINISH_TASK_NAME,
        "end_graph_hooks" if deps.end_graph_hooks else END,
    )
    builder.add_edge(REJECT_UNBOUND_TOOLS_NODE, "agent")
    if retrieve_enabled:
        builder.add_edge("select_tools", "agent")


def create_agent(
    llm: LanguageModelLike,
    tool_registry: Mapping[str, BaseTool],
    *,
    tools_config: ToolRetrievalConfig | None = None,
    hooks_config: HookConfig | None = None,
    agent_config: AgentConfig | None = None,
) -> StateGraph:
    """Create an agent with a registry of tools.

    The agent will function as a typical ReAct agent, but is equipped with a tool
    for retrieving tools from a registry. The agent will start with only this tool.
    As it is executed, retrieved tools will be bound to the model.

    Args:
        llm: Language model to use for the agent.
        tool_registry: a dict mapping string IDs to BaseTool instances.
        tools_config: how tools are retrieved and bound (semantic-retrieval
            settings, custom retrieval functions, initial tool IDs, or full
            disablement of the retrieval mechanism).
        hooks_config: lifecycle hooks and end-of-run gating:
            - pre_model_hooks: process state before each model call.
            - end_graph_hooks: final processing before the graph ends; when set,
              routing goes through the end_graph_hooks node before END.
            - require_finish_to_end: nudge-and-loop instead of ending early on
              plain-text replies while work looks unfinished.
        agent_config: identity and middleware:
            - agent_name: label attached to LLM invocations; "comms_agent"
              additionally gets NEW_MESSAGE_BREAKER appended to string replies.
            - context_schema: per-run context schema declared on the graph.
            - middleware: LangChain AgentMiddleware instances providing hooks:
              before_model, after_model, wrap_model_call, wrap_tool_call
              (wrap_tool_call replaces post_tool_hooks).
    """
    tools = tools_config or ToolRetrievalConfig()
    hooks = hooks_config or HookConfig()
    agent_cfg = agent_config or AgentConfig()

    middleware_executor, middleware_tools = _extract_middleware(agent_cfg.middleware)
    retrieve_tools, store_arg = _build_retrieve_tools(tools)

    deps = _AgentDeps(
        llm=llm,
        tool_registry=tool_registry,
        agent_name=agent_cfg.agent_name,
        middleware_executor=middleware_executor,
        middleware_tools=middleware_tools,
        retrieve_tools=retrieve_tools,
        store_arg=store_arg,
        retrieve_tools_function=tools.retrieve_tools_function,
        retrieve_tools_coroutine=tools.retrieve_tools_coroutine,
        initial_tool_ids=tools.initial_tool_ids,
        pre_model_hooks=hooks.pre_model_hooks,
        end_graph_hooks=hooks.end_graph_hooks,
        require_finish_to_end=hooks.require_finish_to_end,
    )

    builder = StateGraph(State, context_schema=agent_cfg.context_schema)

    builder.set_entry_point("agent")
    builder.add_node("agent", _model_node(deps))
    if retrieve_tools is not None:
        # Tool retrieval is a pure read (Chroma/Postgres searches), so the
        # default retry predicate is safe here. The tools node deliberately has
        # NO retry policy: exceptions escaping it come from parent-routed tool
        # execution, and re-running a side-effectful tool can double-execute it.
        builder.add_node(
            "select_tools",
            _select_tools_node(deps),
            retry_policy=RetryPolicy(),
        )
    builder.add_node("tools", _tool_node(deps))
    builder.add_node(
        FINISH_TASK_NAME,
        RunnableCallable(finish_task_node, afinish_task_node),
    )
    # No explicit name: langgraph takes it from the callable, which is already
    # REJECT_UNBOUND_TOOLS_NODE. Passing it again would be the same string in a
    # fifth place with nothing keeping the copies in step.
    builder.add_node(RunnableCallable(reject_unbound_tools, areject_unbound_tools))

    _wire_edges(builder, deps)

    return builder
