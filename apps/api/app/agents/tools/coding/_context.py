"""Shared helpers for the persistent coding tools.

Centralizes:
  - user_id extraction from RunnableConfig
  - path canonicalization + workspace-containment checks
  - shorthand for emitting custom stream events to the frontend
"""

from __future__ import annotations

import posixpath
from typing import Any, Dict, Optional

from shared.py.wide_events import log
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

WORKSPACE_ROOT = "/workspace"


def get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config or raise a clear error."""
    configurable = config.get("configurable", {}) if config else {}
    metadata = config.get("metadata", {}) if config else {}
    user_id = configurable.get("user_id") or metadata.get("user_id")
    if not user_id:
        raise ValueError("user_id not found in RunnableConfig")
    return user_id


def canonical_workspace_path(path: str) -> str:
    """Resolve `path` to an absolute path under `/workspace`.

    - Relative paths are joined to `/workspace`.
    - Absolute paths are normalized.
    - Paths that escape `/workspace` raise ValueError.
    """
    if not path:
        raise ValueError("path is required")
    if not path.startswith("/"):
        path = posixpath.join(WORKSPACE_ROOT, path)
    canonical = posixpath.normpath(path)
    if canonical != WORKSPACE_ROOT and not canonical.startswith(WORKSPACE_ROOT + "/"):
        raise ValueError(f"Path escapes /workspace: {path}")
    return canonical


def safe_emit(event: Dict[str, Any]) -> None:
    """Emit a custom stream event, swallowing 'no writer' errors silently.

    Tools are invoked both during live chat (writer present) and during
    silent/background runs (no writer). Don't fail the tool just because
    nobody is listening.
    """
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(event)
    except Exception as e:
        log.debug(f"Stream writer failed silently: {e}")


def is_user_visible(path: str) -> bool:
    """True if the path lives under `/workspace/.user-visible/`."""
    return path.startswith(f"{WORKSPACE_ROOT}/.user-visible/") or path == (
        f"{WORKSPACE_ROOT}/.user-visible"
    )


def detect_content_type(path: str) -> Optional[str]:
    """Best-effort MIME type from extension. Returns None if unknown."""
    ext_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
        "json": "application/json",
        "md": "text/markdown",
        "txt": "text/plain",
        "csv": "text/csv",
        "html": "text/html",
    }
    _, _, ext = path.rpartition(".")
    return ext_map.get(ext.lower())
