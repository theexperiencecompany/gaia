"""Persistent `write` tool — overwrite files in the user's E2B workspace."""

from __future__ import annotations

from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._artifacts import publish_artifact_write
from app.agents.tools.coding._context import (
    atomic_write,
    canonical_path,
    get_session_id,
    get_user_id,
    safe_emit,
)
from app.agents.workspace.paths import MountRole
from app.decorators import with_doc, with_rate_limiting
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import FsOps, add_fs_bytes, fs_timer
from app.templates.docstrings.coding_tools_docs import WRITE_TOOL
from shared.py.wide_events import log

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB


@tool
@with_rate_limiting("workspace_write")
@with_doc(WRITE_TOOL)
async def write(
    config: RunnableConfig,
    path: Annotated[str, "Path inside the workspace (relative = session scratch)"],
    content: Annotated[str, "Full file contents"],
) -> str:
    """Write content to a file in the persistent workspace, creating parents."""

    log.set(tool={"name": "write", "action": "write"})

    try:
        user_id = get_user_id(config)
        session_id = get_session_id(config)
        abs_path, role, role_conv = canonical_path(path, session_id=session_id)
    except ValueError as e:
        return f"Error: {e}"

    if role == MountRole.USER_UPLOADED:
        return (
            "Error: user-uploaded/ is read-only. Copy the file to scratch "
            "first: cp user-uploaded/<name> scratch/"
        )

    encoded = content.encode("utf-8")
    if len(encoded) > MAX_CONTENT_BYTES:
        return f"Error: content exceeds {MAX_CONTENT_BYTES} bytes"

    try:
        async with fs_timer(FsOps.TOOL_WRITE), acquire_sandbox(user_id) as sbx:
            real_mtime = await atomic_write(sbx, abs_path, encoded)
        add_fs_bytes(FsOps.TOOL_WRITE, len(encoded))
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"write tool failed: {e}", exc_info=True)
        return f"Error writing file: {e}"

    safe_emit(
        {
            "file_data": {
                "operation": "write",
                "path": abs_path,
                "size_bytes": len(encoded),
            }
        },
        session_id=session_id,
    )

    # Real-time artifact push: the instant a `artifacts/` file is written we
    # publish to the artifacts channel. The chat stream's forwarder relays it as
    # an SSE `artifact_data` chunk *during the active turn*, so the card renders
    # immediately — no polling, no dependence on the sandbox-side watcher.
    await publish_artifact_write(
        user_id, role, role_conv, abs_path, content, len(encoded), real_mtime
    )

    return f"Wrote {len(encoded)} bytes to {abs_path}"
