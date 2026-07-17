"""Typed shape of the LangGraph ``configurable`` bag every agent run threads.

The ``configurable`` dict is the single context surface carried across the whole
agent tree (comms → executor → handoff subagents) and read by the accounting
middleware for budget enforcement. Typing it here makes the required keys — the
ones every run MUST carry, like ``root_request_id`` and ``user_id`` — a mypy
error to omit at the one construction seam (``build_agent_config``), so a new
entry point cannot silently reintroduce a threading gap.

Only the construction seam (``build_agent_config``) is typed against this; the
bag is read back elsewhere via LangGraph's ``get_config()`` as ``dict[str, Any]``
and threaded through many ``dict``-typed helpers, so typing it here — where a key
can actually be dropped — is what makes the guarantee without forcing an
invariance-driven ripple across every reader.
"""

from typing import Any, NotRequired, TypedDict

AgentConfigurable = TypedDict(
    "AgentConfigurable",
    {
        # --- Identity: present on every agent run ---
        "thread_id": str,
        "user_id": str | None,
        "email": str | None,
        "user_name": str,
        "user_timezone": str,
        # One id for the WHOLE user turn: minted at the top-level build and
        # inherited by every child agent. The accounting middleware keys the
        # request tree's aggregate token ceiling on it — REQUIRED here so a new
        # entry point cannot drop it (build_agent_config always sets it).
        "root_request_id": str,
        # --- Model routing ---
        "provider": str,
        "model_name": str,
        "model": str,
        "max_tokens": int,
        # --- Execution context ---
        "selected_tool": str | None,
        "tool_category": str | None,
        "subagent_id": str | None,
        "vfs_session_id": str | None,
        "stream_id": str | None,
        "active_todo_id": str | None,
        "execution_mode": str,
        "conversation_source": str | None,
        "source_category": str,
        # Pre-fetched memory/skill sections passed through to subagents to avoid
        # repeat ChromaDB lookups (always set, may be None).
        "__pinned_memories__": Any,
        "__pinned_skills__": Any,
        # --- Stamped after construction (apply_plan_model / dev override / inheritance) ---
        "plan_type": NotRequired[str],
        "reasoning": NotRequired[dict[str, Any]],
        "model_kwargs": NotRequired[dict[str, Any]],
        "__dev_executor_model__": NotRequired[str | None],
        # --- Langfuse tracing (set only when a trace is bound) ---
        "langfuse_trace_id": NotRequired[str],
        "langfuse_tags": NotRequired[list[str]],
        # --- Workflow context (stamped onto trigger runs) ---
        "workflow_id": NotRequired[str | None],
        "workflow_title": NotRequired[str],
        "workflow_notify_on_completion": NotRequired[bool],
        "user_message_id": NotRequired[str | None],
        "conversation_id": NotRequired[str],
    },
)
