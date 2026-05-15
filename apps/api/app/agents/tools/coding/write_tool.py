"""Persistent `write` tool — overwrite files in the user's E2B workspace."""

from __future__ import annotations

import base64
from typing import Annotated

from shared.py.wide_events import log
from app.agents.tools.coding._context import (
    canonical_path,
    get_session_id,
    get_user_id,
    safe_emit,
    sh_quote,
)
from app.agents.workspace.paths import MountRole
from app.decorators import with_doc, with_rate_limiting
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.templates.docstrings.coding_tools_docs import WRITE_TOOL
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

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
        abs_path, role, _ = canonical_path(path, session_id=session_id)
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
        async with acquire_sandbox(user_id) as sbx:
            await _atomic_write(sbx, abs_path, encoded)
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"write tool failed: {e}", exc_info=True)
        return f"Error writing file: {e}"

    # No inline artifact_data emit: the per-sandbox ArtifactWatcher is the
    # single source of truth for `.user-visible/` events (so bash/background
    # writes and tool writes are surfaced identically, with no double cards).
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

    return f"Wrote {len(encoded)} bytes to {abs_path}"


async def _atomic_write(sbx: object, abs_path: str, content: bytes) -> None:
    """Base64-pipe the content into a temp file then atomically rename."""
    parent = abs_path.rsplit("/", 1)[0] or "/"
    tmp_path = f"{abs_path}.gaia-tmp"
    payload = base64.b64encode(content).decode("ascii")
    cmd = (
        f"mkdir -p {sh_quote(parent)} && "
        f"printf %s {sh_quote(payload)} | base64 -d > {sh_quote(tmp_path)} && "
        f"mv {sh_quote(tmp_path)} {sh_quote(abs_path)}"
    )
    result = await sbx.commands.run(cmd, timeout=30)  # type: ignore[attr-defined]
    if getattr(result, "exit_code", 1) != 0:
        raise RuntimeError(
            f"write failed (exit {getattr(result, 'exit_code', None)}): "
            f"{getattr(result, 'stderr', '')}"
        )
