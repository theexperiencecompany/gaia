"""
Manage System Prompts Node for the conversational graph.

Keeps exactly ONE static main prompt and ONE dynamic-context prompt per run.
Stacking ten timestamped dynamic-context messages across a ten-turn
conversation is what shatters the LLM's implicit prompt-cache prefix — this
node discards every older copy so the LLM sees a stable
`[static_main, dynamic_context_latest, ...conversation]` shape on every turn.
"""

from typing import cast

from shared.py.wide_events import log
from app.override.langgraph_bigtool.utils import State
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore


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


def manage_system_prompts_node(
    state: State, config: RunnableConfig, store: BaseStore
) -> State:
    """Keep only the latest static main prompt and the latest dynamic-context message.

    Logic:
    - At most ONE static (non-dynamic-context) system prompt is kept — the latest.
    - At most ONE dynamic-context system prompt is kept — the latest.
    - All other system messages are dropped. Non-system messages pass through.

    Runs as a pre-model hook so this also fires when a generation is cancelled
    (end-of-graph hooks don't run on cancellation).
    """
    try:
        messages = state.get("messages", [])
        if not messages:
            return state

        latest_static_idx: int | None = None
        latest_dynamic_idx: int | None = None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.type != "system":
                continue
            if _is_dynamic_context(msg):
                if latest_dynamic_idx is None:
                    latest_dynamic_idx = idx
            else:
                if latest_static_idx is None:
                    latest_static_idx = idx
            if latest_static_idx is not None and latest_dynamic_idx is not None:
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
        # ``[static, dynamic, ...non_system...]``.
        dropped_system = 0
        static_msg: AnyMessage | None = None
        dynamic_msg: AnyMessage | None = None
        non_system: list[AnyMessage] = []
        for idx, msg in enumerate(messages):
            if msg.type == "system":
                if idx == latest_static_idx:
                    static_msg = msg
                elif idx == latest_dynamic_idx:
                    dynamic_msg = msg
                else:
                    dropped_system += 1
            else:
                non_system.append(msg)

        filtered: list[AnyMessage] = []
        if static_msg is not None:
            filtered.append(static_msg)
        if dynamic_msg is not None:
            filtered.append(dynamic_msg)
        filtered.extend(non_system)

        log.set(
            prompt_pruning={
                "messages_in": len(messages),
                "messages_out": len(filtered),
                "dropped_system_prompts": dropped_system,
                "kept_static": static_msg is not None,
                "kept_dynamic": dynamic_msg is not None,
            }
        )

        return cast(State, {**state, "messages": filtered})

    except Exception as e:
        log.error(f"Error in manage system prompts node: {e}")
        return state
