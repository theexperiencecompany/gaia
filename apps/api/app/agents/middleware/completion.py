"""Harness-owned completion: the executor cannot silently quit early.

``work_looks_unfinished`` is the prematurity check the executor's graph loop
runs before honouring a plain-text stop. True on a concrete "too shallow"
signal: a tracked todo still pending, fewer than ``COMPLETION_MIN_TOOL_CALLS``
tools executed on a delegated task, or a final reply that PROMISES future work
("hang tight", "still digging") — nothing runs after the reply ends, so a
promise-to-continue is never a valid ending. Kept here so the graph builder
stays generic; only the executor opts in via
``create_agent(require_finish_to_end=True)``.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from app.constants.llm import COMPLETION_MIN_TOOL_CALLS, COMPLETION_PROMISE_MARKERS
from app.override.langgraph_bigtool.utils import State
from app.utils.multimodal import extract_text_content


def reply_promises_future_work(state: State) -> bool:
    """True when the final reply commits to work that will never happen."""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage):
        return False
    text = extract_text_content(last.content).lower()
    return any(marker in text for marker in COMPLETION_PROMISE_MARKERS)


def work_looks_unfinished(state: State) -> bool:
    """True when the executor's plain-text stop is not backed by completed work."""
    todos = state.get("todos") or []
    if any(isinstance(t, dict) and t.get("status") in ("pending", "in_progress") for t in todos):
        return True
    if reply_promises_future_work(state):
        return True
    tool_calls = sum(1 for m in state.get("messages", []) if isinstance(m, ToolMessage))
    return tool_calls < COMPLETION_MIN_TOOL_CALLS
