"""
Manage System Prompts Node for the conversational graph.

Keeps exactly ONE message per slot per run. Stacking ten timestamped
dynamic-context messages across a ten-turn conversation is what shatters the
LLM's implicit prompt-cache prefix — this node discards every older copy so the
LLM sees a stable
`[static_main, dynamic_stable, todo, bg_exec, exec_status, memory_recall,
...conversation, time_human]` shape on every turn.

The ordering is deliberate for the implicit prompt cache. Dynamic context is
split into a byte-stable identity block (``dynamic_stable``, index 1) and a
volatile ``memory_recall`` block (memory recall / knowledge / skills / todos)
that churns turn-to-turn: the stable block sits right after the static prompt
so the ``[static, dynamic_stable]`` prefix is cacheable, while ``memory_recall``
is pushed to the TAIL of the system block (Gemini only promotes leading
contiguous SystemMessages to ``system_instruction``, so it must stay in the
leading block). The current-time HumanMessage is pushed to the TAIL of contents
(after the whole conversation) — its content ticks every minute, so keeping it
at the very end lets the append-only history prefix stay byte-stable.

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

from app.constants.log_tags import LogTag
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
    """Dynamic-context messages carry either the new or legacy marker.

    Legacy checkpointed threads written before the dynamic/memory-recall split
    still carry a single combined message with both ``dynamic_context`` and
    ``memory_message`` — those keep working as the stable dynamic slot.
    """
    return _has_marker(msg, "dynamic_context") or _has_marker(msg, "memory_message")


def _is_memory_recall(msg: AnyMessage) -> bool:
    """Volatile memory-recall system message emitted by
    ``build_dynamic_context_messages`` — memory recall / knowledge / skills /
    todos / run banners. Carries its own marker (never ``dynamic_context`` /
    ``memory_message``) so it slots at the tail of the system block instead of
    collapsing into the stable dynamic slot.
    """
    return _has_marker(msg, "memory_recall")


def _is_todo_context(msg: AnyMessage) -> bool:
    """Todo-context messages are emitted by ``todo_pre_model_hook`` each step."""
    return _has_marker(msg, "todo_context")


def _is_background_executor(msg: AnyMessage) -> bool:
    """Background-executor result injected by ``narrate_executor_result``.

    Identified by name (not a marker) because the message is built by the
    background runner without graph-state context. Per-turn content — kept
    in its own slot at the tail of ``system_instruction`` alongside
    ``todo_context`` so the cacheable [static, dynamic] prefix is preserved.
    """
    return getattr(msg, "name", None) == "background_executor"


def _is_executor_status(msg: AnyMessage) -> bool:
    """Live-executor status frame injected per-turn by ``executor_status_hook``."""
    return _has_marker(msg, "executor_status")


def _is_time_context(msg: AnyMessage) -> bool:
    """Time-context HumanMessages carry the current clock — emitted each turn
    by ``build_current_time_message``. We keep only the latest so checkpointed
    threads don't accumulate stale clocks that contradict the current time.
    """
    return _has_marker(msg, "time_context")


def manage_system_prompts_node(state: State, config: RunnableConfig, store: BaseStore) -> State:
    """Keep only the latest system message in each slot, in cache-stable order.

    Logic:
    - At most ONE static (non-dynamic, non-todo) system prompt is kept — the latest.
    - At most ONE stable dynamic-context system prompt is kept — the latest.
    - At most ONE todo-context system prompt is kept — the latest. Emitted by
      ``todo_pre_model_hook``; kept in its own slot so it does not collide with
      the real static prompt when accumulated snapshots exist in state.
    - At most ONE background-executor and ONE executor-status frame are kept.
    - At most ONE memory-recall system message is kept — the latest. Volatile
      per-turn content; slotted at the TAIL of the system block so it never
      shifts the cacheable [static, dynamic_stable] prefix.
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
        latest_bg_exec_idx: int | None = None
        latest_exec_status_idx: int | None = None
        latest_memory_recall_idx: int | None = None
        latest_time_idx: int | None = None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.type == "system":
                if _is_background_executor(msg):
                    if latest_bg_exec_idx is None:
                        latest_bg_exec_idx = idx
                elif _is_executor_status(msg):
                    if latest_exec_status_idx is None:
                        latest_exec_status_idx = idx
                elif _is_memory_recall(msg):
                    if latest_memory_recall_idx is None:
                        latest_memory_recall_idx = idx
                elif _is_todo_context(msg):
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
                and latest_bg_exec_idx is not None
                and latest_exec_status_idx is not None
                and latest_memory_recall_idx is not None
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
        # ``[static, dynamic_stable, todo_context, background_executor,
        # executor_status, memory_recall, ...non_system..., time]``. Only
        # ``[static, dynamic_stable]`` is byte-stable across turns; every slot
        # after it (``todo_context``, ``background_executor``,
        # ``executor_status``, ``memory_recall``) carries per-turn churn and so
        # sits at the tail of ``system_instruction`` where it never shifts the
        # cacheable prefix. ``memory_recall`` is last in the system block, right
        # before contents begin.
        #
        # The latest time HumanMessage is pushed to the TAIL of contents (after
        # the whole conversation). Its content ticks every minute; putting it at
        # the very end keeps the append-only history prefix byte-stable, so the
        # contents prefix (all prior turns) stays cacheable and only the final
        # clock line differs turn-to-turn.
        dropped_system = 0
        dropped_time = 0
        static_msg: AnyMessage | None = None
        dynamic_msg: AnyMessage | None = None
        todo_msg: AnyMessage | None = None
        bg_exec_msg: AnyMessage | None = None
        exec_status_msg: AnyMessage | None = None
        memory_recall_msg: AnyMessage | None = None
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
                elif idx == latest_bg_exec_idx:
                    bg_exec_msg = msg
                elif idx == latest_exec_status_idx:
                    exec_status_msg = msg
                elif idx == latest_memory_recall_idx:
                    memory_recall_msg = msg
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
        if bg_exec_msg is not None:
            filtered.append(bg_exec_msg)
        if exec_status_msg is not None:
            filtered.append(exec_status_msg)
        if memory_recall_msg is not None:
            filtered.append(memory_recall_msg)
        filtered.extend(non_system)
        if time_msg is not None:
            filtered.append(time_msg)

        log.set(
            prompt_pruning={
                "messages_in": len(messages),
                "messages_out": len(filtered),
                "dropped_system_prompts": dropped_system,
                "dropped_time_context": dropped_time,
                "kept_static": static_msg is not None,
                "kept_dynamic": dynamic_msg is not None,
                "kept_todo": todo_msg is not None,
                "kept_bg_exec": bg_exec_msg is not None,
                "kept_exec_status": exec_status_msg is not None,
                "kept_memory_recall": memory_recall_msg is not None,
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
        log.error(f"{LogTag.AGENT} Error in manage system prompts node: {e}")
        return state
