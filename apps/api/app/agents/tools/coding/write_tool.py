"""Persistent `write` tool — overwrite files in the user's E2B workspace."""

from __future__ import annotations

import base64
from typing import Annotated

from shared.py.wide_events import log
from app.agents.tools.coding._context import (
    canonical_workspace_path,
    detect_content_type,
    get_user_id,
    is_user_visible,
    safe_emit,
)
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
    path: Annotated[str, "Path inside /workspace"],
    content: Annotated[str, "Full file contents"],
) -> str:
    """Write content to a file in the persistent workspace, creating parents."""

    log.set(tool={"name": "write", "action": "write"})

    try:
        user_id = get_user_id(config)
        abs_path = canonical_workspace_path(path)
    except ValueError as e:
        return f"Error: {e}"

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

    safe_emit(
        {
            "file_data": {
                "operation": "write",
                "path": abs_path,
                "size_bytes": len(encoded),
            }
        }
    )
    if is_user_visible(abs_path):
        filename = abs_path.rsplit("/", 1)[-1]
        safe_emit(
            {
                "artifact_data": {
                    "path": abs_path,
                    "filename": filename,
                    "content_type": detect_content_type(filename),
                    "size_bytes": len(encoded),
                }
            }
        )

    return f"Wrote {len(encoded)} bytes to {abs_path}"


async def _atomic_write(sbx: object, abs_path: str, content: bytes) -> None:
    """Base64-pipe the content into a temp file then atomically rename."""
    parent = abs_path.rsplit("/", 1)[0] or "/"
    tmp_path = f"{abs_path}.gaia-tmp"
    payload = base64.b64encode(content).decode("ascii")
    cmd = (
        f"mkdir -p {_q(parent)} && "
        f"printf %s {_q(payload)} | base64 -d > {_q(tmp_path)} && "
        f"mv {_q(tmp_path)} {_q(abs_path)}"
    )
    result = await sbx.commands.run(cmd, timeout=30)  # type: ignore[attr-defined]
    if getattr(result, "exit_code", 1) != 0:
        raise RuntimeError(
            f"write failed (exit {getattr(result, 'exit_code', None)}): "
            f"{getattr(result, 'stderr', '')}"
        )


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"
