"""Persistent `edit` tool — exact-string replacement on workspace files."""

from __future__ import annotations

from dataclasses import dataclass
import posixpath
from typing import Annotated

from e2b import AsyncSandbox, NotFoundException
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
from app.decorators import with_doc, with_rate_limiting
from app.services import gaia_task_files
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import FsOps, fs_timer
from app.services.storage.gaia_tasks_vfs import GAIA_TASKS_DIRNAME
from app.templates.docstrings.coding_tools_docs import EDIT_TOOL
from shared.py.wide_events import log

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PATCH_BYTES = 2 * 1024 * 1024
# Re-applying a patch to fresh content is cheap and safe; beyond this the
# notes are churning under the agent and it should re-read and decide.
_EDIT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class EditPatch:
    """The replacement to apply — grouped so helpers stay within the arg limit."""

    old_string: str
    new_string: str
    replace_all: bool


@dataclass(frozen=True)
class EditTarget:
    """Where to apply the patch — the resolved workspace location and actor."""

    user_id: str
    abs_path: str
    role: MountRole
    role_conv: str | None
    session_id: str | None


def _validate_patch(patch: EditPatch) -> str | None:
    if not patch.old_string:
        return "Error: old_string is required"
    if (len(patch.old_string.encode("utf-8")) > MAX_PATCH_BYTES) or (
        len(patch.new_string.encode("utf-8")) > MAX_PATCH_BYTES
    ):
        return f"Error: old_string and new_string must each be <= {MAX_PATCH_BYTES} bytes"
    return None


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

    patch = EditPatch(old_string=old_string, new_string=new_string, replace_all=replace_all)
    if (patch_error := _validate_patch(patch)) is not None:
        return patch_error

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

    # account/** holds projections of real settings — refuse with the tool
    # that performs the mutation instead of touching the filesystem.
    rel = posixpath.relpath(abs_path, WORKSPACE_ROOT)
    refusal = account_mutation_refusal(rel)
    if refusal is not None:
        return refusal

    target = EditTarget(
        user_id=user_id, abs_path=abs_path, role=role, role_conv=role_conv, session_id=session_id
    )
    # Tracked-todo files are edited on the todo document, not in the sandbox.
    if (handled := await _maybe_edit_task_file(rel, target, patch)) is not None:
        return handled

    try:
        async with fs_timer(FsOps.TOOL_EDIT), acquire_sandbox(user_id) as sbx:
            return await _do_edit(sbx, target, patch)
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable ({e})"
    except Exception as e:
        log.error("edit tool failed", error_type=type(e).__name__, exc_info=True)
        return f"Error editing file: {e}"


async def _read_editable_content(sbx: AsyncSandbox, abs_path: str) -> tuple[str | None, str]:
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


def _apply_replacement(
    content: str, old_string: str, new_string: str, replace_all: bool
) -> tuple[str, int] | str:
    """``(new_content, replaced_count)`` or the user-facing error string."""
    occurrences = content.count(old_string)
    if occurrences == 0:
        return "Error: old_string not found in file"
    if occurrences > 1 and not replace_all:
        return (
            f"Error: old_string appears {occurrences} times. "
            "Pass replace_all=True or add surrounding context to disambiguate."
        )
    if replace_all:
        return content.replace(old_string, new_string), occurrences
    return content.replace(old_string, new_string, 1), 1  # pragma: no mutate — occurrences==1


def _emit_edit(abs_path: str, size_bytes: int, replaced: int, session_id: str | None) -> str:
    safe_emit(
        {
            "file_data": {
                "operation": "edit",
                "path": abs_path,
                "size_bytes": size_bytes,
                "occurrences_replaced": replaced,
            }
        },
        session_id=session_id,
    )
    return f"Edited {abs_path} ({replaced} occurrence{'s' if replaced > 1 else ''} replaced)"


async def _maybe_edit_task_file(rel: str, target: EditTarget, patch: EditPatch) -> str | None:
    """Edit the todo document when ``rel`` names a tracked-todo file.

    Returns the tool result when handled (including the resolve error), else
    None so the caller falls through to the sandbox path. A patch is
    re-appliable, so a lost revision race re-resolves and retries instead of
    failing the edit.
    """
    try:
        task_ref = await gaia_task_files.resolve(rel, target.user_id)
        if task_ref is None:
            if rel == GAIA_TASKS_DIRNAME or rel.startswith(GAIA_TASKS_DIRNAME + "/"):
                return (
                    f"Error: {rel} is not an editable notes file. Only canvas.md and "
                    "activity.md under /workspace/gaia-tasks/<todo>/ can be edited."
                )
            return None
        for _ in range(_EDIT_MAX_ATTEMPTS):
            try:
                return await _edit_task_file(task_ref, target, patch)
            except gaia_task_files.NoteConflictError:
                task_ref = await gaia_task_files.resolve(rel, target.user_id)
                if task_ref is None:
                    return "Error: tracked todo no longer exists."
        return "Error: notes changed concurrently; read the file again and retry the edit."
    except gaia_task_files.GaiaTaskPathError as e:
        return f"Error: {e}"
    except Exception as e:
        log.error("edit task file failed", error_type=type(e).__name__, exc_info=True)
        return f"Error editing todo notes: {e}"


async def _edit_task_file(
    task_ref: gaia_task_files.GaiaTaskPath,
    target: EditTarget,
    patch: EditPatch,
) -> str:
    refusal = gaia_task_files.write_refusal(task_ref)
    if refusal is not None:
        return refusal
    content = await gaia_task_files.read_file(task_ref, target.user_id)
    outcome = _apply_replacement(content, patch.old_string, patch.new_string, patch.replace_all)
    if isinstance(outcome, str):
        return outcome
    new_content, replaced = outcome
    refusal = await gaia_task_files.write_file(task_ref, target.user_id, new_content)
    if refusal is not None:
        return refusal
    log.set(write_via="todo_document")
    return _emit_edit(
        target.abs_path, len(new_content.encode("utf-8")), replaced, target.session_id
    )


async def _do_edit(sbx: AsyncSandbox, target: EditTarget, patch: EditPatch) -> str:
    content, error = await _read_editable_content(sbx, target.abs_path)
    if content is None:
        return error

    outcome = _apply_replacement(content, patch.old_string, patch.new_string, patch.replace_all)
    if isinstance(outcome, str):
        return outcome
    new_content, replaced = outcome

    new_bytes = new_content.encode("utf-8")  # pragma: no mutate — "UTF-8" is the same codec
    real_mtime = await atomic_write(sbx, target.abs_path, new_bytes)

    # Surface the edit live in chat when it lands under artifacts/ — same path
    # the write tool takes, so an edited artifact card updates during the turn.
    await publish_artifact_write(
        target.user_id,
        target.role,
        target.role_conv,
        target.abs_path,
        new_content,
        len(new_bytes),
        real_mtime,
    )

    return _emit_edit(target.abs_path, len(new_bytes), replaced, target.session_id)
