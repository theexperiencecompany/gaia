"""Persistent `write` tool — overwrite files in the user's E2B workspace."""

from __future__ import annotations

import posixpath
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
from app.agents.workspace.paths import WORKSPACE_ROOT, MountRole
from app.constants.account import account_mutation_refusal
from app.constants.log_tags import LogTag
from app.decorators import with_doc, with_rate_limiting
from app.services import gaia_task_files
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import FsOps, add_fs_bytes, fs_timer
from app.services.storage.gaia_tasks_vfs import GAIA_TASKS_DIRNAME
from app.templates.docstrings.coding_tools_docs import WRITE_TOOL
from shared.py.wide_events import log

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB


def _refuse_write(role: MountRole, rel: str) -> str | None:
    if role == MountRole.USER_UPLOADED:
        return (
            "Error: user-uploaded/ is read-only. Copy the file to scratch "
            "first: cp user-uploaded/<name> scratch/"
        )
    # account/** holds projections of real settings — refuse with the tool
    # that performs the mutation instead of touching the filesystem.
    return account_mutation_refusal(rel)


async def _write_task_file(
    task_ref: gaia_task_files.GaiaTaskPath,
    user_id: str,
    content: str,
    abs_path: str,
    size: int,
    session_id: str | None,
) -> str:
    refusal = await gaia_task_files.write_file(task_ref, user_id, content)
    if refusal is not None:
        return refusal
    log.set(write_via="todo_document")
    safe_emit(
        {"file_data": {"operation": "write", "path": abs_path, "size_bytes": size}},
        session_id=session_id,
    )
    return f"Wrote {size} bytes to {abs_path}"


async def _maybe_write_task_file(
    rel: str, user_id: str, content: str, abs_path: str, size: int, session_id: str | None
) -> str | None:
    try:
        task_ref = await gaia_task_files.resolve(rel, user_id)
        if task_ref is None:
            if rel == GAIA_TASKS_DIRNAME or rel.startswith(GAIA_TASKS_DIRNAME + "/"):
                return (
                    f"Error: {rel} is not an editable notes file. Only canvas.md and "
                    "activity.md under /workspace/gaia-tasks/<todo>/ can be edited."
                )
            return None
        return await _write_task_file(task_ref, user_id, content, abs_path, size, session_id)
    except gaia_task_files.GaiaTaskPathError as e:
        return f"Error: {e}"
    except gaia_task_files.NoteConflictError:
        return "Error: notes changed concurrently; read the file again and retry the write."
    except Exception as e:
        log.error("write task file failed", error_type=type(e).__name__, exc_info=True)
        return f"Error writing todo notes: {e}"


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

    rel = posixpath.relpath(abs_path, WORKSPACE_ROOT)
    if (preamble_refusal := _refuse_write(role, rel)) is not None:
        return preamble_refusal

    encoded = content.encode("utf-8")
    if len(encoded) > MAX_CONTENT_BYTES:
        return f"Error: content exceeds {MAX_CONTENT_BYTES} bytes"

    # Tracked-todo files (canvas.md / activity.md) are stored on the todo
    # document; the on-disk copy is a read-only projection repainted by the
    # sync, so the write goes to Mongo and never touches the sandbox.
    if (
        handled := await _maybe_write_task_file(
            rel, user_id, content, abs_path, len(encoded), session_id
        )
    ) is not None:
        return handled

    try:
        async with fs_timer(FsOps.TOOL_WRITE), acquire_sandbox(user_id) as sbx:
            real_mtime = await atomic_write(sbx, abs_path, encoded)
        add_fs_bytes(FsOps.TOOL_WRITE, len(encoded))
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable: {e}"
    except Exception as e:
        log.error(f"{LogTag.SANDBOX} write tool failed", error_type=type(e).__name__, exc_info=True)
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
