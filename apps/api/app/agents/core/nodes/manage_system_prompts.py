"""
Manage System Prompts Node for the conversational graph.

Keeps exactly ONE static main prompt and ONE dynamic-context prompt per run.
Stacking ten timestamped dynamic-context messages across a ten-turn
conversation is what shatters the LLM's implicit prompt-cache prefix — this
node discards every older copy so the LLM sees a stable
`[static_main, dynamic_context_latest, time_human, ...conversation]` shape on
every turn.

The bigtool override's ``acall_model`` calls hooks via
``state = await execute_hooks(...)`` and then invokes the LLM with
``state["messages"]`` directly — the hook's return value is what the LLM
sees on that single call. The persistent checkpoint state still grows
unfiltered (LangGraph's ``add_messages`` reducer never reorders by ID), but
that doesn't matter for the cache: only the per-call request bytes do.
"""

from typing import cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log


def _has_marker(msg: AnyMessage, name: str) -> bool:
    """Return whether `msg` carries the given marker flag.

    Checks both `additional_kwargs` (where LangChain persists custom kwargs)
    and `model_extra` (Pydantic) for back-compat with older messages written
    before the marker migration.
    """
    if bool(msg.additional_kwargs.get(name, False)):
        return True
    model_extra = getattr(msg, "model_extra", None)
    if isinstance(model_extra, dict) and bool(model_extra.get(name, False)):
        return True
    return False


def _is_dynamic_context(msg: AnyMessage) -> bool:
    """Dynamic-context messages carry either the new or legacy marker."""
    return _has_marker(msg, "dynamic_context") or _has_marker(msg, "memory_message")


def _is_todo_context(msg: AnyMessage) -> bool:
    """Todo-context messages are emitted by ``todo_pre_model_hook`` each step."""
    return _has_marker(msg, "todo_context")


def _is_time_context(msg: AnyMessage) -> bool:
    """Time-context HumanMessages carry the current clock — emitted each turn
    by ``build_current_time_message``. We keep only the latest so checkpointed
    threads don't accumulate stale clocks that contradict the current time.
    """
    return _has_marker(msg, "time_context")


def manage_system_prompts_node(state: State, config: RunnableConfig, store: BaseStore) -> State:
    """Keep only the latest system message in each of three slots.

    Logic:
    - At most ONE static (non-dynamic, non-todo) system prompt is kept — the latest.
    - At most ONE dynamic-context system prompt is kept — the latest.
    - At most ONE todo-context system prompt is kept — the latest. Emitted by
      ``todo_pre_model_hook``; kept in its own slot so it does not collide with
      the real static prompt when accumulated snapshots exist in state.
    - At most ONE time-context HumanMessage is kept — the latest. Emitted each
      turn by ``build_current_time_message``; older copies are dropped so the
      LLM never sees contradictory clocks across a checkpointed thread.
    - All other system messages are dropped. Non-time-context non-system
      messages pass through.

    Runs as a pre-model hook so this also fires when a generation is cancelled
    (end-of-graph hooks don't run on cancellation).
    """
    try:
        messages = state.get("messages", [])
        if not messages:
            return state

        latest_static_idx: int | None = None
        latest_dynamic_idx: int | None = None
        latest_todo_idx: int | None = None
        latest_time_idx: int | None = None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.type == "system":
                if _is_todo_context(msg):
                    if latest_todo_idx is None:
                        latest_todo_idx = idx
                elif _is_dynamic_context(msg):
                    if latest_dynamic_idx is None:
                        latest_dynamic_idx = idx
                elif latest_static_idx is None:
                    latest_static_idx = idx
            elif _is_time_context(msg) and latest_time_idx is None:
                latest_time_idx = idx
            if (
                latest_static_idx is not None
                and latest_dynamic_idx is not None
                and latest_todo_idx is not None
                and latest_time_idx is not None
            ):
                break

        # Load-bearing ordering choice: the kept system messages MUST appear
        # at the FRONT of the output list. ``langchain-google-genai``'s
        # ``_parse_chat_history`` only promotes a SystemMessage to Gemini's
        # ``system_instruction`` if it appears at index 0 (or immediately
        # after another SystemMessage — i.e. contiguous at the start). Any
        # SystemMessage encountered after a non-system message is silently
        # dropped. Preserving original order on multi-turn runs leaves system
        # messages at idx > 0, which wipes out the entire system prompt and
        # kills implicit caching. So we rebuild the list as
        # ``[static, dynamic, todo_context, time, ...non_system...]`` — the
        # ``todo_context`` slot sits at the tail of ``system_instruction``
        # so its per-step churn does not shift the cacheable prefix.
        #
        # The latest time HumanMessage is hoisted to the FRONT of contents
        # (right after the system block) so its byte position is constant
        # across turns. If it stayed at its original position, every new
        # turn would shift it later in the list (because new dialogue is
        # appended before it), and the contents prefix would diverge at byte 0
        # on every turn — making cache hits impossible across turns.
        dropped_system = 0
        dropped_time = 0
        static_msg: AnyMessage | None = None
        dynamic_msg: AnyMessage | None = None
        todo_msg: AnyMessage | None = None
        time_msg: AnyMessage | None = None
        non_system: list[AnyMessage] = []
        for idx, msg in enumerate(messages):
            if msg.type == "system":
                if idx == latest_static_idx:
                    static_msg = msg
                elif idx == latest_dynamic_idx:
                    dynamic_msg = msg
                elif idx == latest_todo_idx:
                    todo_msg = msg
                else:
                    dropped_system += 1
            elif _is_time_context(msg):
                if idx == latest_time_idx:
                    time_msg = msg
                else:
                    dropped_time += 1
            else:
                non_system.append(msg)

        filtered: list[AnyMessage] = []
        if static_msg is not None:
            filtered.append(static_msg)
        if dynamic_msg is not None:
            filtered.append(dynamic_msg)
        if todo_msg is not None:
            filtered.append(todo_msg)
        if time_msg is not None:
            filtered.append(time_msg)
        filtered.extend(non_system)

        log.set(
            prompt_pruning={
                "messages_in": len(messages),
                "messages_out": len(filtered),
                "dropped_system_prompts": dropped_system,
                "dropped_time_context": dropped_time,
                "kept_static": static_msg is not None,
                "kept_dynamic": dynamic_msg is not None,
                "kept_todo": todo_msg is not None,
                "kept_time": time_msg is not None,
            }
        )

        # ``acall_model`` (in the bigtool override) calls the hooks via
        # ``state = await execute_hooks(...)`` and then invokes the LLM with
        # ``state["messages"]`` directly — the hook's return value is used
        # for that single LLM call without going through LangGraph's
        # ``add_messages`` reducer. So returning the filtered/reordered list
        # here is what controls the per-call shape that the provider sees,
        # which is what implicit caching keys on.
        return cast(State, {**state, "messages": filtered})

    except Exception as e:
        log.error(f"Error in manage system prompts node: {e}")
        return state
