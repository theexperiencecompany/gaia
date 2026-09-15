"""Shared helpers for the persistent coding tools.

Centralizes:
  - user_id / session_id extraction from RunnableConfig
  - path canonicalization + workspace-containment checks (session-aware)
  - shell quoting
  - shorthand for emitting custom stream events to the frontend
"""

from __future__ import annotations

import contextlib
from datetime import UTC
import posixpath
import time
from typing import Any

from e2b import AsyncSandbox
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
from app.constants.sandbox import WORKSPACE_TMP_SUFFIX
from app.models.agent_models import agent_configurable
from shared.py.wide_events import log

_SESSION_EVENT_KEYS = ("bash_data", "file_data", "artifact_data")


def get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config or raise a clear error."""
    configurable = agent_configurable(config)
    metadata = config.get("metadata", {}) if config else {}
    user_id = configurable.get("user_id") or metadata.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("user_id not found in RunnableConfig")
    return user_id


def get_session_id(config: RunnableConfig) -> str | None:
    """Resolve the workspace session id from RunnableConfig.

    Prefer vfs_session_id: subagent_runner pins it to the *parent*
    conversation thread so artifacts are visible across executor calls
    (thread_id differs and would split the session dir). May be None for
    non-chat invocations (workflows, background tasks).
    """
    configurable = agent_configurable(config)
    metadata = config.get("metadata", {}) if config else {}
    session_id = (
        configurable.get("vfs_session_id")
        or configurable.get("conversation_id")
        or metadata.get("conversation_id")
        or configurable.get("thread_id")
    )
    return session_id if isinstance(session_id, str) else None


def canonical_path(path: str, *, session_id: str | None) -> tuple[str, MountRole, str | None]:
    """Resolve a tool-supplied path to an absolute /workspace path.

    Relative paths join to the session root (or /workspace); absolute paths
    must stay under /workspace. Returns (abs_path, role, role_conv_id).
    """
    if not path:
        raise ValueError("path is required")
    if not path.startswith("/"):
        base = session_dir(session_id) if session_id else WORKSPACE_ROOT
        path = posixpath.join(base, path)
    canonical = posixpath.normpath(path)
    if not is_under_workspace(canonical):
        raise ValueError("path must stay inside /workspace")
    role, conv = classify(canonical)
    return canonical, role, conv


def canonical_rel(path: str, *, session_id: str | None) -> tuple[str, str]:
    """Resolve a tool-supplied path to (abs_path, workspace_rel).

    Raises ValueError if the path resolves to the workspace root itself
    (rel == "", not a file) or escapes /workspace.
    """
    abs_path, _, _ = canonical_path(path, session_id=session_id)
    rel = abs_path[len(WORKSPACE_ROOT) + 1 :] if abs_path != WORKSPACE_ROOT else ""
    if not rel:
        raise ValueError("path must be a file inside the workspace, not the workspace root")
    return abs_path, rel


def sh_quote(s: str) -> str:
    """Single-quote a string for safe inclusion in a shell command."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


async def atomic_write(sbx: AsyncSandbox, abs_path: str, data: bytes) -> float:
    """Write bytes into the sandbox atomically; return the file's mtime (epoch s).

    Writes to a temp path then renames into place, atomic on the same FS.
    EntryInfo.modified_time is a NAIVE UTC datetime, so it MUST be tagged UTC
    before .timestamp() or a non-UTC worker's epoch is off, breaking dedup.
    """
    tmp_path = f"{abs_path}{WORKSPACE_TMP_SUFFIX}"
    await sbx.files.write(tmp_path, data)
    try:
        info = await sbx.files.rename(tmp_path, abs_path)
    except Exception:
        # Don't leave a half-written temp littering the workspace if the rename
        # fails (e.g. a transient sandbox blip). Best-effort — on a dead sandbox
        # the remove fails too, which is fine.
        with contextlib.suppress(Exception):
            await sbx.files.remove(tmp_path)
        raise
    mtime = getattr(info, "modified_time", None)
    return mtime.replace(tzinfo=UTC).timestamp() if mtime is not None else time.time()


def safe_emit(event: dict[str, Any], *, session_id: str | None = None) -> None:
    """Emit a custom stream event, swallowing 'no writer' errors silently.

    Tools run both during live chat (writer present) and silent/background
    runs (no writer). session_id, when given, is stamped into the payload
    so the frontend can route the event to the right conversation.
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
        log.debug("Stream writer failed silently", error_type=type(e).__name__)


# Re-exported from the pure workspace.paths module so non-agent callers
# (storage, HTTP endpoints) can reuse it without importing langchain.
__all__ = [
    "atomic_write",
    "canonical_path",
    "canonical_rel",
    "detect_content_type",
    "get_session_id",
    "get_user_id",
    "safe_emit",
    "sh_quote",
]
