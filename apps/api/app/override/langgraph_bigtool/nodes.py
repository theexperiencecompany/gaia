"""Node implementations for the bigtool agent graph.

Bodies moved verbatim out of ``create_agent()`` (create_agent.py), where they
lived as closures; each ``make_*`` factory takes exactly the values its closure
captured. ``create_agent`` is now assembly only.
"""

from collections.abc import Callable, Mapping
import functools
from typing import Any, cast

from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallWithContext
from langgraph.store.base import BaseStore
from langgraph.types import Send

from app.agents.llm.client import ainvoke_llm, invoke_llm, is_default_model_config
from app.agents.middleware.executor import MiddlewareExecutor
from app.constants.general import FINISH_TASK_NAME, NEW_MESSAGE_BREAKER
from app.constants.llm import RECURSION_WRAPUP_THRESHOLD_STEPS
from app.models.agent_models import AgentConfigurable, agent_configurable
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

SyncAsyncNodePair = tuple[
    Callable[..., State],
    Callable[..., Any],
]


def _prepare_fallback(
    fallback_llm: Runnable | None,
    tools_to_bind: list[BaseTool],
    model_configurations: AgentConfigurable,
) -> Callable[[], Runnable] | None:
    """Factory that binds the default fallback model with the same tools as the
    primary. Returned as a zero-arg callable so the (per-turn, tool-list-sized)
    binding only happens if the primary actually fails. None when no fallback is
    configured or the selected model already is the default model (no point
    falling back to itself)."""
    if fallback_llm is None or is_default_model_config(model_configurations):
        return None
    return lambda: fallback_llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]


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


def make_build_tools_to_bind(
    tool_registry: Mapping[str, BaseTool],
    retrieve_tools: StructuredTool | None,
    middleware_tools: list[BaseTool],
    initial_tool_ids: list[str] | None,
) -> Callable[[State], list[BaseTool]]:
    """Build the per-call bound-tool assembler."""

    def build_tools_to_bind(state: State) -> list[BaseTool]:
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
            tool_registry[id] for id in (initial_tool_ids or []) if id in tool_registry
        ]
        selected_tools = [
            tool_registry[id] for id in state["selected_tool_ids"] if id in tool_registry
        ]
        tools_to_bind: list[BaseTool] = []
        if retrieve_tools is not None:
            tools_to_bind.append(retrieve_tools)
        tools_to_bind.extend(initial_tools)
        tools_to_bind.extend(middleware_tools)
        tools_to_bind.extend(selected_tools)
        return dedupe_tool_bindings(tools_to_bind)

    return build_tools_to_bind


def make_model_nodes(
    llm: LanguageModelLike,
    agent_name: str,
    pre_model_hooks: list[HookType] | None,
    middleware_executor: MiddlewareExecutor | None,
    build_tools_to_bind: Callable[[State], list[BaseTool]],
    fallback_llm: Runnable | None,
) -> SyncAsyncNodePair:
    """Build the (sync, async) model-invocation nodes."""

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
        tools_to_bind = build_tools_to_bind(state)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]
        fallback = _prepare_fallback(fallback_llm, tools_to_bind, model_configurations)
        state = _maybe_inject_wrapup(state)
        response = invoke_llm(
            llm_with_tools,
            state["messages"],
            fallback=fallback,
            config=config,
            label=agent_name,
        )

        if not response.tool_calls and not response.content:
            response.content = "Empty response from model."

        if isinstance(response.content, str) and agent_name == "comms_agent":
            response.content = response.content + NEW_MESSAGE_BREAKER

        return {"messages": [*tombstones, response]}  # type: ignore[return-value]

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

        tools_to_bind = build_tools_to_bind(state)
        llm_with_tools = _llm.bind_tools(tools_to_bind)  # type: ignore[attr-defined]
        fallback = _prepare_fallback(fallback_llm, tools_to_bind, model_configurations)
        invoke_fn = functools.partial(
            ainvoke_llm, llm_with_tools, fallback=fallback, config=config, label=agent_name
        )

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

        if middleware_executor and middleware_executor.has_wrap_model_call():
            middleware_tools_for_request: list[BaseTool | dict[str, Any]] = [
                tool for tool in tools_to_bind
            ]
            response = await middleware_executor.wrap_model_invocation(
                model=_llm,  # type: ignore[arg-type]
                state=state,
                config=config,
                store=store,
                tools=middleware_tools_for_request,
                invoke_fn=invoke_fn,
            )
        else:
            response = await invoke_fn(state["messages"])

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
        # return the new response — not the full list. Tombstones prune the
        # slot-stale prompt copies the pre-model hooks dropped, so the
        # checkpointed thread stays bounded too.
        result: dict[str, object] = {"messages": [*tombstones, response]}
        base_keys = {"messages", "selected_tool_ids"}
        for key, value in updated_state.items():
            if key not in base_keys:
                result[key] = value
        return result  # type: ignore[return-value]

    return call_model, acall_model


def make_select_tools_nodes(
    retrieve_tools: StructuredTool | None,
    store_arg: str | None,
    tool_registry: Mapping[str, BaseTool],
) -> SyncAsyncNodePair:
    """Build the (sync, async) retrieve_tools resolution nodes."""

    def select_tools(tool_calls: list[dict], config: RunnableConfig, *, store: BaseStore) -> State:
        if retrieve_tools is None:
            raise RuntimeError("retrieve_tools is disabled and select_tools should not be called")

        selected_tools = {}
        response_tools = {}
        for tool_call in tool_calls:
            kwargs = {**tool_call["args"]}
            if store_arg:
                kwargs[store_arg] = store
            if config:
                user_id = agent_configurable(config).get("user_id")
                if user_id:
                    kwargs["user_id"] = user_id

            result = retrieve_tools.invoke(kwargs, config=config)
            selected, response = _split_retrieval_result(result)
            selected_tools[tool_call["id"]] = selected
            response_tools[tool_call["id"]] = response

        tool_messages, _ = format_selected_tools(response_tools, tool_registry)  # type: ignore[arg-type]
        _, bind_ids = format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]

    async def aselect_tools(
        tool_calls: list[dict], config: RunnableConfig, *, store: BaseStore
    ) -> State:
        """Async twin of ``select_tools`` — resolve retrieve_tools calls into bindings."""
        if retrieve_tools is None:
            raise RuntimeError("retrieve_tools is disabled and aselect_tools should not be called")

        selected_tools = {}
        response_tools = {}
        for tool_call in tool_calls:
            kwargs = {**tool_call["args"]}
            if store_arg:
                kwargs[store_arg] = store
            if config:
                user_id = agent_configurable(config).get("user_id")
                if user_id:
                    kwargs["user_id"] = user_id

            result = await retrieve_tools.ainvoke(kwargs, config=config)
            selected, response = _split_retrieval_result(result)
            selected_tools[tool_call["id"]] = selected
            response_tools[tool_call["id"]] = response

        tool_messages, _ = format_selected_tools(response_tools, tool_registry)  # type: ignore[arg-type]
        _, bind_ids = format_selected_tools(selected_tools, tool_registry)  # type: ignore[arg-type]
        return {"messages": tool_messages, "selected_tool_ids": bind_ids}  # type: ignore[return-value]

    return select_tools, aselect_tools


def _split_retrieval_result(result: object) -> tuple[list[str], list[str]]:
    """Normalize a retrieval result (RetrieveToolsResult dict or plain list) into
    deduped (bindable ids, response ids), dropping subagent:-prefixed bindings."""
    if isinstance(result, dict):
        tools_to_bind = [
            tool_id for tool_id in result.get("tools_to_bind", []) if isinstance(tool_id, str)
        ]
        response = [tool_id for tool_id in result.get("response", []) if isinstance(tool_id, str)]
    else:
        tools_to_bind = [
            tool_id
            for tool_id in (result if isinstance(result, list) else [])
            if isinstance(tool_id, str)
        ]
        response = tools_to_bind

    filtered_bind = [tool_id for tool_id in tools_to_bind if not tool_id.startswith("subagent:")]
    return dedupe_str_list(filtered_bind), dedupe_str_list(response)


def make_end_graph_hooks_nodes(end_graph_hooks: list[HookType] | None) -> SyncAsyncNodePair:
    """Build the (sync, async) end-graph hook nodes."""

    def execute_end_graph_hooks_node(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        return changed_hook_keys(state, sync_execute_hooks(end_graph_hooks, state, config, store))

    async def aexecute_end_graph_hooks_node(
        state: State, config: RunnableConfig, *, store: BaseStore
    ) -> State:
        """Run the end-graph hooks; persist only the keys they actually changed."""
        return changed_hook_keys(state, await execute_hooks(end_graph_hooks, state, config, store))

    return execute_end_graph_hooks_node, aexecute_end_graph_hooks_node


def make_bound_tool_names(
    retrieve_tools: StructuredTool | None,
    tool_registry: Mapping[str, BaseTool],
    initial_tool_ids: list[str] | None,
    middleware_tools: list[BaseTool],
) -> Callable[[State], set[str]]:
    """Build the resolver for the tool names currently bound to the model."""

    def get_bound_tool_names(state: State) -> set[str]:
        bound: set[str] = set()
        # retrieve_tools itself is always bound when enabled
        if retrieve_tools is not None:
            bound.add(retrieve_tools.name)
        # Tools selected via retrieve_tools
        for tool_id in state.get("selected_tool_ids", []):
            if tool_id in tool_registry:
                bound.add(tool_registry[tool_id].name)
        # Always-bound initial tools
        for tool_id in initial_tool_ids or []:
            if tool_id in tool_registry:
                bound.add(tool_registry[tool_id].name)
        # Middleware tools (e.g. spawn_subagent, plan_tasks)
        for tool in middleware_tools:
            if hasattr(tool, "name"):
                bound.add(tool.name)
        return bound

    return get_bound_tool_names


def reject_unbound_tools(tool_calls: list[dict], *, store: BaseStore) -> State:
    """Return error ToolMessages for tool calls that were not bound."""
    del store
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
    return {"messages": messages}  # type: ignore[return-value]


async def areject_unbound_tools(tool_calls: list[dict], *, store: BaseStore) -> State:
    """Async twin of ``reject_unbound_tools`` for the async graph path."""
    return reject_unbound_tools(tool_calls, store=store)


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


def make_executable_calls(
    get_bound_tool_names: Callable[[State], set[str]],
    retrieve_tools: StructuredTool | None,
) -> Callable[[State], list[ToolCall]]:
    """Build the resolver for the calls the tools node will actually run."""

    def executable_calls(state: State) -> list[ToolCall]:
        """The message's tool calls that the tools node will run, names canonicalized.

        Mutates each call's name in place when it maps to a bound tool, so the tools
        node's registry lookup hits the actual BaseTool. Separate from routing because
        both the router and the approvals node's outgoing edge need this same list.
        """
        last_message = _last_tool_calling_message(state)
        if last_message is None:
            return []
        bound_names = get_bound_tool_names(state)
        canonical_to_bound = canonical_tool_name_map(bound_names)
        runnable: list[ToolCall] = []
        for call in last_message.tool_calls:
            if retrieve_tools is not None and call["name"] == retrieve_tools.name:
                continue
            if call["name"] not in bound_names:
                canonical = canonical_to_bound.get(call["name"].replace("-", "_"))
                if canonical is None:
                    continue
                call["name"] = canonical
            runnable.append(call)
        return runnable

    return executable_calls


def make_dispatch_tools(
    executable_calls: Callable[[State], list[ToolCall]],
) -> Callable[..., list[Send]]:
    """Build the fan-out that sends each executable call to the tools node."""

    def dispatch_tools(state: State, *, store: BaseStore) -> list[Send]:
        """Fan the message's calls out to the tools node, one task each.

        ToolCallWithContext carries the full state dict so ToolNode can do InjectedState
        injection. Each call becomes its own task, and a task that pauses for approval
        leaves its completed siblings alone — LangGraph persists their writes.
        """
        del store
        return [
            Send(
                "tools",
                ToolCallWithContext(__type="tool_call_with_context", tool_call=call, state=state),
            )
            for call in executable_calls(state)
        ]

    return dispatch_tools


def make_should_continue(
    get_bound_tool_names: Callable[[State], set[str]],
    retrieve_tools: StructuredTool | None,
    dispatch_tools: Callable[..., list[Send]],
    has_end_graph_hooks: bool,
) -> Callable[..., str | Send | list[Send]]:
    """Build the post-model router."""

    def should_continue(state: State, *, store: BaseStore) -> str | Send | list[Send]:
        messages = state["messages"]
        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return "end_graph_hooks" if has_end_graph_hooks else END
        bound_names = get_bound_tool_names(state)
        canonical_to_bound = canonical_tool_name_map(bound_names)
        destinations: list[Send] = []
        unbound_calls: list[ToolCall] = []

        finish_calls: list[ToolCall] = [
            call for call in last_message.tool_calls if call.get("name") == FINISH_TASK_NAME
        ]
        if finish_calls:
            return Send(FINISH_TASK_NAME, finish_calls)

        for call in last_message.tool_calls:
            if retrieve_tools is not None and call["name"] == retrieve_tools.name:
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
        destinations.extend(dispatch_tools(state, store=store))

        if unbound_calls:
            destinations.append(Send("reject_unbound_tools", unbound_calls))

        return destinations

    return should_continue


def finish_task_node(tool_calls: list[ToolCall], *, store: BaseStore) -> State:
    """Convert finish_task calls into their terminal ToolMessages."""
    del store
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
    return {"messages": messages}  # type: ignore[return-value]


async def afinish_task_node(tool_calls: list[ToolCall], *, store: BaseStore) -> State:
    """Async twin of ``finish_task_node`` for the async graph path."""
    return finish_task_node(tool_calls, store=store)
