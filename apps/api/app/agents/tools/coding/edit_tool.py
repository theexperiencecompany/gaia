"""Persistent `edit` tool — exact-string replacement on workspace files."""

from __future__ import annotations

import base64
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
        abs_path, role, _ = canonical_path(path, session_id=session_id)
    except ValueError as e:
        return f"Error: {e}"

    if role == MountRole.USER_UPLOADED:
        return (
            "Error: user-uploaded/ is read-only. Copy the file to scratch "
            "first: cp user-uploaded/<name> scratch/"
        )

    try:
        async with fs_timer(FsOps.TOOL_EDIT), acquire_sandbox(user_id) as sbx:
            return await _do_edit(sbx, abs_path, old_string, new_string, replace_all, session_id)
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"edit tool failed: {e}", exc_info=True)
        return f"Error editing file: {e}"


async def _read_editable_content(sbx: object, abs_path: str) -> tuple[str | None, str]:
    """Read a workspace file's UTF-8 content. Returns ``(content, error)``.

    On success ``error`` is empty; on failure ``content`` is ``None`` and
    ``error`` holds the user-facing message.
    """
    # Read full file via base64 to keep binary-safe and to avoid quoting issues.
    # Signal "file missing" via exit code, not an in-band marker.
    read_cmd = (
        f"if [ ! -f {sh_quote(abs_path)} ]; then exit 44; else base64 -w0 {sh_quote(abs_path)}; fi"
    )
    read_result = await sbx.commands.run(read_cmd, timeout=15)  # type: ignore[attr-defined]
    if (getattr(read_result, "exit_code", 0) or 0) == 44:
        return None, f"Error: file not found at {abs_path}"
    raw = (getattr(read_result, "stdout", "") or "").strip()

    try:
        content_bytes = base64.b64decode(raw)
    except Exception as e:
        return None, f"Error: failed to decode file: {e}"

    if len(content_bytes) > MAX_FILE_BYTES:
        return None, f"Error: file exceeds {MAX_FILE_BYTES} bytes; cannot edit"

    try:
        return content_bytes.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "Error: file is not UTF-8; cannot edit"


async def _do_edit(
    sbx: object,
    abs_path: str,
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
    payload = base64.b64encode(new_bytes).decode("ascii")
    tmp_path = f"{abs_path}.gaia-tmp"
    write_cmd = (
        f"printf %s {sh_quote(payload)} | base64 -d > {sh_quote(tmp_path)} && "
        f"mv {sh_quote(tmp_path)} {sh_quote(abs_path)}"
    )
    write_result = await sbx.commands.run(write_cmd, timeout=30)  # type: ignore[attr-defined]
    if getattr(write_result, "exit_code", 1) != 0:
        return (
            f"Error: write failed (exit {getattr(write_result, 'exit_code', None)}): "
            f"{getattr(write_result, 'stderr', '')}"
        )

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

    return (
        f"Edited {abs_path} ({occurrences if replace_all else 1} "
        f"occurrence{'s' if (replace_all and occurrences > 1) else ''} replaced)"
    )
