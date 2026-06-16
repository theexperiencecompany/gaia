"""Persistent `edit` tool — exact-string replacement on workspace files."""

from __future__ import annotations

from typing import Annotated, Any

from e2b import NotFoundException
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
from app.services.storage import FsOps, fs_timer
from app.templates.docstrings.coding_tools_docs import EDIT_TOOL
from shared.py.wide_events import log

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PATCH_BYTES = 2 * 1024 * 1024


@tool
@with_rate_limiting("workspace_edit")
@with_doc(EDIT_TOOL)
async def edit(
    config: RunnableConfig,
    path: Annotated[str, "Path to an existing file inside the workspace"],
    old_string: Annotated[str, "Exact text to replace; must appear verbatim"],
    new_string: Annotated[str, "Replacement text; may be empty"],
    replace_all: Annotated[bool, "Replace every occurrence"] = False,
) -> str:
    """Replace a string inside an existing workspace file."""

    log.set(tool={"name": "edit", "action": "edit"})

    if not old_string:
        return "Error: old_string is required"
    if (len(old_string.encode("utf-8")) > MAX_PATCH_BYTES) or (
        len(new_string.encode("utf-8")) > MAX_PATCH_BYTES
    ):
        return f"Error: old_string and new_string must each be <= {MAX_PATCH_BYTES} bytes"

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

    try:
        async with fs_timer(FsOps.TOOL_EDIT), acquire_sandbox(user_id) as sbx:
            return await _do_edit(
                sbx,
                user_id,
                abs_path,
                role,
                role_conv,
                old_string,
                new_string,
                replace_all,
                session_id,
            )
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"edit tool failed: {e}", exc_info=True)
        return f"Error editing file: {e}"


async def _read_editable_content(sbx: Any, abs_path: str) -> tuple[str | None, str]:
    """Read a workspace file's UTF-8 content. Returns ``(content, error)``.

    On success ``error`` is empty; on failure ``content`` is ``None`` and
    ``error`` holds the user-facing message.
    """
    # Native filesystem read, binary-safe — no base64/quoting. A missing file
    # raises NotFoundException rather than returning a sentinel.
    try:
        content_bytes = bytes(await sbx.files.read(abs_path, format="bytes"))
    except NotFoundException:
        return None, f"Error: file not found at {abs_path}"

    if len(content_bytes) > MAX_FILE_BYTES:
        return None, f"Error: file exceeds {MAX_FILE_BYTES} bytes; cannot edit"

    try:
        return content_bytes.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "Error: file is not UTF-8; cannot edit"


async def _do_edit(
    sbx: Any,
    user_id: str,
    abs_path: str,
    role: MountRole,
    role_conv: str | None,
    old_string: str,
    new_string: str,
    replace_all: bool,
    session_id: str | None,
) -> str:
    content, error = await _read_editable_content(sbx, abs_path)
    if content is None:
        return error

    occurrences = content.count(old_string)
    if occurrences == 0:
        return "Error: old_string not found in file"
    if occurrences > 1 and not replace_all:
        return (
            f"Error: old_string appears {occurrences} times. "
            "Pass replace_all=True or add surrounding context to disambiguate."
        )

    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)

    new_bytes = new_content.encode("utf-8")
    real_mtime = await atomic_write(sbx, abs_path, new_bytes)

    safe_emit(
        {
            "file_data": {
                "operation": "edit",
                "path": abs_path,
                "size_bytes": len(new_bytes),
                "occurrences_replaced": occurrences if replace_all else 1,
            }
        },
        session_id=session_id,
    )

    # Surface the edit live in chat when it lands under artifacts/ — same path
    # the write tool takes, so an edited artifact card updates during the turn.
    await publish_artifact_write(
        user_id, role, role_conv, abs_path, new_content, len(new_bytes), real_mtime
    )

    return (
        f"Edited {abs_path} ({occurrences if replace_all else 1} "
        f"occurrence{'s' if (replace_all and occurrences > 1) else ''} replaced)"
    )
