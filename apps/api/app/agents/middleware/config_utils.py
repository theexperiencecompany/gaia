"""
Shared utilities for extracting runtime config in middleware.

Both VFSCompactionMiddleware and VFSArchivingSummarizationMiddleware need
to pull user_id, conversation_id, and written_by from the LangGraph runtime
config. This module provides a single extraction point.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VFSRuntimeContext:
    """Extracted VFS context from LangGraph runtime config."""

    user_id: str
    conversation_id: str
    written_by: str
    thread_id: str | None
    vfs_session_id: str | None


def extract_vfs_context(runtime: Any) -> VFSRuntimeContext:
    """
    Extract VFS context fields from a LangGraph Runtime or ToolCallRequest.

    Raises ValueError if required fields are missing.
    """
    config: dict[str, Any] = getattr(runtime, "config", {}) or {}
    configurable = config.get("configurable", {})
    user_id: str | None = configurable.get("user_id")
    vfs_session_id: str | None = configurable.get("vfs_session_id")
    thread_id: str | None = configurable.get("thread_id")
    subagent_id: str | None = configurable.get("subagent_id")
    metadata_cfg = config.get("metadata", {})
    agent_name_meta: str | None = metadata_cfg.get("agent_name")

    if not user_id:
        raise ValueError("VFS context requires 'user_id' in configurable")

    conversation_id = vfs_session_id or thread_id
    if not conversation_id:
        raise ValueError(
            "VFS context requires 'vfs_session_id' or 'thread_id' in configurable"
        )

    written_by = subagent_id or agent_name_meta
    if not written_by:
        raise ValueError(
            "VFS context requires 'subagent_id' in configurable or 'agent_name' in metadata"
        )

    return VFSRuntimeContext(
        user_id=user_id,
        conversation_id=conversation_id,
        written_by=written_by,
        thread_id=thread_id,
        vfs_session_id=vfs_session_id,
    )
