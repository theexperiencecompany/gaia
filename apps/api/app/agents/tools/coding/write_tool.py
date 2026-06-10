"""Persistent `write` tool — overwrite files in the user's E2B workspace."""

from __future__ import annotations

import base64
import contextlib
import time
from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._context import (
    canonical_path,
    get_session_id,
    get_user_id,
    safe_emit,
    sh_quote,
)
from app.agents.workspace.paths import (
    INLINE_ARTIFACT_MAX_BYTES,
    MountRole,
    detect_content_type,
    is_inlineable_content_type,
    session_artifacts,
)
from app.decorators import with_doc, with_rate_limiting
from app.services.artifact_events import publish_artifact_event, upsert_event
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import ArtifactInfo, FsOps, add_fs_bytes, fs_timer
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
            real_mtime = await _atomic_write(sbx, abs_path, encoded)
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

    # Real-time artifact push: the instant a `artifacts/` file is written
    # we publish to the artifacts channel. The chat stream's forwarder relays
    # it as an SSE `artifact_data` chunk *during the active turn*, so the card
    # renders immediately — no polling, no dependence on the sandbox-side
    # watcher (which only catches bash/background writes as a best-effort
    # latency path). De-duped downstream by (session_id, path).
    if role == MountRole.ARTIFACTS and role_conv:
        artifacts_root = session_artifacts(role_conv) + "/"
        rel = (
            abs_path[len(artifacts_root) :]
            if abs_path.startswith(artifacts_root)
            else abs_path.rsplit("/", 1)[-1]
        )
        content_type = detect_content_type(rel)
        inline_body = (
            content
            if len(encoded) <= INLINE_ARTIFACT_MAX_BYTES
            and is_inlineable_content_type(content_type)
            else None
        )
        with contextlib.suppress(Exception):
            await publish_artifact_event(
                user_id,
                upsert_event(
                    role_conv,
                    ArtifactInfo(
                        path=rel,
                        size_bytes=len(encoded),
                        mtime=real_mtime,
                        content_type=content_type,
                    ),
                    body=inline_body,
                ),
            )

    return f"Wrote {len(encoded)} bytes to {abs_path}"


async def _atomic_write(sbx: object, abs_path: str, content: bytes) -> float:
    """Base64-pipe content into a temp file, atomically rename, return mtime.

    Returns the real post-rename mtime (`stat -c%Y`) so the artifact-event
    dedup signature `(event, path, size_bytes, mtime)` stays valid across
    repeat writes. Falls back to wall-clock if stat is unparseable.
    """
    parent = abs_path.rsplit("/", 1)[0] or "/"
    tmp_path = f"{abs_path}.gaia-tmp"
    payload = base64.b64encode(content).decode("ascii")
    cmd = (
        f"mkdir -p {sh_quote(parent)} && "
        f"printf %s {sh_quote(payload)} | base64 -d > {sh_quote(tmp_path)} && "
        f"mv {sh_quote(tmp_path)} {sh_quote(abs_path)} && "
        f"stat -c%Y {sh_quote(abs_path)}"
    )
    result = await sbx.commands.run(cmd, timeout=30)  # type: ignore[attr-defined]
    if getattr(result, "exit_code", 1) != 0:
        raise RuntimeError(
            f"write failed (exit {getattr(result, 'exit_code', None)}): "
            f"{getattr(result, 'stderr', '')}"
        )
    try:
        return float((getattr(result, "stdout", "") or "").strip())
    except ValueError:
        return time.time()
