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
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import PRUNED_MESSAGE_IDS_KEY, State
from shared.py.wide_events import log

# OpenAI-wire providers (OpenRouter, the env-defined custom endpoint) accept
# system messages anywhere in the message list — DeepSeek applies every system
# message (the earliest wins on a directive conflict, which keeps the static
# prompt's authority). Gemini is different: ``langchain-google-genai`` only
# promotes a LEADING contiguous run of SystemMessages to ``system_instruction``
# and silently drops any system message after a non-system message.
#
# For OpenAI-wire providers the volatile slots therefore move to the TAIL of
# the prompt (after the whole conversation). The byte-stable prefix then
# becomes ``[static, dynamic_stable, ...conversation]`` and the provider's
# implicit prefix cache covers the conversation — measured 97% hit rate vs
# 83% with the leading-block layout (scripts/measure_llm_cache.py). With the
# volatile slots between the stable block and the conversation, the entire
# conversation re-sends uncached on every turn.
TAIL_VOLATILE_PROVIDERS: frozenset[str] = frozenset({"openrouter", "custom"})


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
    """The byte-stable core-memory documents slot emitted by
    ``build_dynamic_context_messages`` (the always-on "what GAIA knows about
    this user" block). Carries its own marker (never ``dynamic_context`` /
    ``memory_message``) so it slots at the tail of the system block instead of
    collapsing into the stable dynamic slot.
    """
    return _has_marker(msg, "memory_recall")


def _is_memory_volatile(msg: AnyMessage) -> bool:
    """The volatile per-turn tail (recent activity, per-query recall, GAIA
    knowledge, skills, todos, run banners) emitted by
    ``build_dynamic_context_messages``. Churns every turn, so it is placed
    AFTER the time message — the last message in the request — where its
    churn never shifts the byte-stable prefix ahead of it.
    """
    return _has_marker(msg, "memory_volatile")


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
    return bool(getattr(msg, "name", None) == "background_executor")


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
      per-turn content; churns turn-to-turn.
    - At most ONE time-context HumanMessage is kept — the latest. Emitted each
      turn by ``build_current_time_message``; older copies are dropped so the
      LLM never sees contradictory clocks across a checkpointed thread.
    - All other system messages are dropped. Non-time-context non-system
      messages pass through.

    Layout is provider-aware (see ``TAIL_VOLATILE_PROVIDERS``):

    - Gemini keeps the legacy leading-block layout
      ``[static, dynamic_stable, todo, bg_exec, exec_status, memory_recall,
      ...conversation, time]`` — Gemini only accepts system messages in the
      leading contiguous block, and its cache can only cover the stable
      ``[static, dynamic_stable]`` prefix.
    - OpenAI-wire providers (OpenRouter / custom — the production default
      route) get the tail layout
      ``[static, dynamic_stable, ...conversation, todo, bg_exec, exec_status,
      memory_recall, time]`` — every volatile slot moves AFTER the
      conversation so the cacheable prefix extends across the whole history.
      Measured on the real lane: 97% vs 83% hit rate on a growing
      conversation, because the conversation joins the cached prefix instead
      of re-sending uncached every turn.

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
        latest_memory_volatile_idx: int | None = None
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
                elif _is_memory_volatile(msg):
                    if latest_memory_volatile_idx is None:
                        latest_memory_volatile_idx = idx
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
                and latest_memory_volatile_idx is not None
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
        # Relayed via PRUNED_MESSAGE_IDS_KEY so the model node tombstones the
        # stale copies out of the checkpoint, not just the per-call view.
        pruned_ids: list[str] = []
        static_msg: AnyMessage | None = None
        dynamic_msg: AnyMessage | None = None
        todo_msg: AnyMessage | None = None
        bg_exec_msg: AnyMessage | None = None
        exec_status_msg: AnyMessage | None = None
        memory_recall_msg: AnyMessage | None = None
        memory_volatile_msg: AnyMessage | None = None
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
                elif idx == latest_memory_volatile_idx:
                    memory_volatile_msg = msg
                else:
                    dropped_system += 1
                    if msg.id:
                        pruned_ids.append(msg.id)
            elif _is_time_context(msg):
                if idx == latest_time_idx:
                    time_msg = msg
                else:
                    dropped_time += 1
                    if msg.id:
                        pruned_ids.append(msg.id)
            else:
                non_system.append(msg)

        filtered: list[AnyMessage] = []
        if static_msg is not None:
            filtered.append(static_msg)
        if dynamic_msg is not None:
            filtered.append(dynamic_msg)
        # Provider-aware placement of the volatile slots: leading-block layout
        # for Gemini (system messages must stay in the leading run), tail
        # layout for OpenAI-wire providers (system messages are accepted
        # anywhere; the conversation joins the cacheable prefix).
        volatile_msgs = [
            msg
            for msg in (todo_msg, bg_exec_msg, exec_status_msg, memory_recall_msg)
            if msg is not None
        ]
        use_tail_layout = agent_configurable(config).get("provider") in TAIL_VOLATILE_PROVIDERS
        if use_tail_layout:
            filtered.extend(non_system)
            filtered.extend(volatile_msgs)
        else:
            # Gemini keeps every system message in the leading run.
            if memory_volatile_msg is not None:
                volatile_msgs.append(memory_volatile_msg)
            filtered.extend(volatile_msgs)
            filtered.extend(non_system)
        if time_msg is not None:
            filtered.append(time_msg)
        # The volatile per-turn tail is the LAST message in the request (after
        # the clock): it churns every turn and its bytes must never sit inside
        # the cached prefix (measured: it was the dominant per-turn uncached
        # chunk, capping the comms hit rate ~10 points below the harness
        # ceiling).
        if use_tail_layout and memory_volatile_msg is not None:
            filtered.append(memory_volatile_msg)

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
                "tail_layout": use_tail_layout,
            }
        )

        # ``acall_model`` (in the bigtool override) calls the hooks via
        # ``state = await execute_hooks(...)`` and then invokes the LLM with
        # ``state["messages"]`` directly — the hook's return value is used
        # for that single LLM call without going through LangGraph's
        # ``add_messages`` reducer. So returning the filtered/reordered list
        # here is what controls the per-call shape that the provider sees,
        # which is what implicit caching keys on. The pruned ids ride along so
        # the model node can tombstone the stale copies out of the checkpoint.
        return cast(State, {**state, "messages": filtered, PRUNED_MESSAGE_IDS_KEY: pruned_ids})

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in manage system prompts node",
            error_type=type(e).__name__,
            error=str(e),
        )
        return state
