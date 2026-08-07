"""Harness-owned completion: the executor cannot silently quit early.

``work_looks_unfinished`` is the prematurity check the executor's graph loop
runs before honouring a plain-text stop. True on a concrete "too shallow"
signal: a tracked todo still pending, or fewer than ``COMPLETION_MIN_TOOL_CALLS``
tools executed on a delegated task (the "one lookup then assert a conclusion"
failure a good model digs past). Kept here so the graph builder stays generic;
only the executor opts in via ``create_agent(require_finish_to_end=True)``.
"""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from app.constants.llm import COMPLETION_MIN_TOOL_CALLS
from app.override.langgraph_bigtool.utils import State


def work_looks_unfinished(state: State) -> bool:
    """True when the executor's plain-text stop is not backed by completed work."""
    todos = state.get("todos") or []
    if any(isinstance(t, dict) and t.get("status") in ("pending", "in_progress") for t in todos):
        return True
    tool_calls = sum(1 for m in state.get("messages", []) if isinstance(m, ToolMessage))
    return tool_calls < COMPLETION_MIN_TOOL_CALLS
