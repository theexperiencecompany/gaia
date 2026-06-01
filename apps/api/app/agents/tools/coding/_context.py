"""Shared helpers for the persistent coding tools.

Centralizes:
  - user_id / session_id extraction from RunnableConfig
  - path canonicalization + workspace-containment checks (session-aware)
  - shell quoting
  - shorthand for emitting custom stream events to the frontend
"""

from __future__ import annotations

import posixpath
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from app.agents.workspace.paths import (
    WORKSPACE_ROOT,
    MountRole,
    classify,
    detect_content_type,
    is_under_workspace,
    session_dir,
)
from shared.py.wide_events import log

_SESSION_EVENT_KEYS = ("bash_data", "file_data", "artifact_data")


def get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config or raise a clear error."""
    configurable = config.get("configurable", {}) if config else {}
    metadata = config.get("metadata", {}) if config else {}
    user_id = configurable.get("user_id") or metadata.get("user_id")
    if not user_id:
        raise ValueError("user_id not found in RunnableConfig")
    return user_id


def get_session_id(config: RunnableConfig) -> str | None:
    """Resolve the workspace session id from RunnableConfig.

    Prefer `vfs_session_id`: subagent_runner pins it to the *parent*
    conversation thread so artifacts written by one executor call are visible
    to the next (`thread_id` is the ephemeral `executor_<conv>_<hex>` wrapper
    and differs from the conversation_id that `ensure_session_dirs` and the
    chat artifact forwarder key on — using it would split the session dir and
    drop every artifact event). May be None for non-chat invocations
    (workflows, background tasks)."""
    configurable = config.get("configurable", {}) if config else {}
    metadata = config.get("metadata", {}) if config else {}
    return (
        configurable.get("vfs_session_id")
        or configurable.get("conversation_id")
        or metadata.get("conversation_id")
        or configurable.get("thread_id")
    )


def canonical_path(path: str, *, session_id: str | None) -> tuple[str, MountRole, str | None]:
    """Resolve a tool-supplied path to an absolute `/workspace` path.

    - Relative paths join to the session root (when `session_id` is known)
      else to `/workspace`. The session root is the base so that
      `artifacts/`, `user-uploaded/`, and `scratch/` are all reachable
      as plain `./X` and classify to the correct role (the artifact watcher
      keys off the real on-disk path, so they must not be scratch-nested).
    - Absolute paths must stay under `/workspace`.

    Returns (abs_path, role, role_conv_id).
    """
    if not path:
        raise ValueError("path is required")
    if not path.startswith("/"):
        base = session_dir(session_id) if session_id else WORKSPACE_ROOT
        path = posixpath.join(base, path)
    canonical = posixpath.normpath(path)
    if not is_under_workspace(canonical):
        raise ValueError(f"Path escapes /workspace: {path}")
    role, conv = classify(canonical)
    return canonical, role, conv


def sh_quote(s: str) -> str:
    """Single-quote a string for safe inclusion in a shell command."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def safe_emit(event: dict[str, Any], *, session_id: str | None = None) -> None:
    """Emit a custom stream event, swallowing 'no writer' errors silently.

    Tools are invoked both during live chat (writer present) and during
    silent/background runs (no writer). Don't fail the tool just because
    nobody is listening. When `session_id` is given it is stamped into the
    artifact/bash/file payloads so the frontend can route the event to the
    right conversation.
    """
    if session_id is not None:
        for key in _SESSION_EVENT_KEYS:
            payload = event.get(key)
            if isinstance(payload, dict):
                payload.setdefault("session_id", session_id)
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(event)
    except Exception as e:
        log.debug(f"Stream writer failed silently: {e}")


# Re-exported from the pure workspace.paths module so non-agent callers
# (storage, HTTP endpoints) can reuse it without importing langchain.
__all__ = [
    "canonical_path",
    "detect_content_type",
    "get_session_id",
    "get_user_id",
    "safe_emit",
    "sh_quote",
]
