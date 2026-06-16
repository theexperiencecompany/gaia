"""Persistent `read` tool — read files from the user's workspace.

Reads go straight to the host-side JuiceFS mount (``/mnt/jfs/users/<id>``, the
same volume the sandbox bind-mounts at ``/workspace``) so they do NOT pay an
E2B sandbox spin-up/resume — the sandbox is reserved for execution, not reading.
When the host mount is absent (native dev without ``mise dev:vm``) the tool
falls back to reading through the sandbox so file reads still work.
"""

from __future__ import annotations

from typing import Annotated, Any

from e2b import NotFoundException
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._context import (
    canonical_path,
    get_session_id,
    get_user_id,
    safe_emit,
)
from app.agents.workspace.paths import WORKSPACE_ROOT
from app.agents.workspace.system_files import system_file_body
from app.decorators import with_doc, with_rate_limiting
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import FsOps, JuiceFSUnavailable, fs_timer, read_user_file
from app.services.storage.juicefs import page_bounds, user_owns_regular_file
from app.templates.docstrings.coding_tools_docs import READ_TOOL
from shared.py.wide_events import log

DEFAULT_LIMIT = 2000
MAX_LIMIT = 10_000
# Native-dev sandbox-read fallback slurps the whole file into memory (no
# server-side range read), so cap it to avoid OOMing the worker on a huge file.
MAX_SANDBOX_READ_BYTES = 10 * 1024 * 1024  # 10 MB


@tool
@with_rate_limiting("workspace_read")
@with_doc(READ_TOOL)
async def read(
    config: RunnableConfig,
    path: Annotated[str, "Path inside the workspace (relative = session scratch)"],
    offset: Annotated[int, "Starting line (1-indexed); 0 = start of file"] = 0,
    limit: Annotated[int, "Max lines to return"] = DEFAULT_LIMIT,
) -> str:
    """Read a file from the persistent workspace."""

    log.set(tool={"name": "read", "action": "read"})

    try:
        user_id = get_user_id(config)
        session_id = get_session_id(config)
        abs_path, _, _ = canonical_path(path, session_id=session_id)
    except ValueError as e:
        return f"Error: {e}"

    offset = max(offset, 0)
    limit = max(1, min(limit, MAX_LIMIT))
    # `abs_path` is always under /workspace (canonical_path enforces it); the
    # relative remainder maps to the user's host root, where read_user_file
    # re-checks containment so a model-supplied path can't escape it.
    rel = abs_path[len(WORKSPACE_ROOT) + 1 :] if abs_path != WORKSPACE_ROOT else ""

    # System-owned files (INDEX.md, the GUIDE.md docs, builtin skills) are
    # authored by GAIA and held in process memory — serve them without touching
    # the sandbox OR JuiceFS. The per-user on-disk copy (a symlink, once the
    # _system mount lands) exists only so in-sandbox `bash` can see them.
    body = system_file_body(rel)
    if body is not None and not await user_owns_regular_file(user_id, rel):
        log.set(read_via="memory")
        return _format_text_read(abs_path, body, offset, limit, session_id)

    try:
        async with fs_timer(FsOps.TOOL_READ):
            try:
                lines, total = await read_user_file(user_id, rel, offset=offset, limit=limit)
            except JuiceFSUnavailable:
                # Native dev (no host mount): read through the sandbox instead.
                log.set(read_via="sandbox_fallback")
                async with acquire_sandbox(user_id) as sbx:
                    return await _read_file_sandbox(sbx, abs_path, offset, limit, session_id)
        return _format_read(abs_path, lines, total, offset, limit, session_id)
    except FileNotFoundError:
        return f"Error: file not found at {abs_path}"
    except ValueError as e:
        # Containment failure (path escaped the user root) or bad input.
        return f"Error: {e}"
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"read tool failed: {e}", exc_info=True)
        return f"Error reading file: {e}"


def _format_text_read(
    abs_path: str,
    text: str,
    offset: int,
    limit: int,
    session_id: str | None,
) -> str:
    """Split full text into lines, slice the requested page, and format.

    Shared by the in-memory system-file path and the sandbox-fallback read so
    their line numbering stays consistent with each other and with the host
    ``read_user_file``.

    ``read_user_file`` opens the file in TEXT mode, so Python's universal-newline
    translation collapses ``\\r\\n`` and a lone ``\\r`` to ``\\n`` before lines are
    counted. Mirror that here (the sandbox path decodes raw bytes, the memory
    path holds an untranslated string), THEN split on ``\\n`` only — matching
    universal newlines, which do NOT treat ``\\f``, ``\\v``, ``\\x85``, U+2028 etc.
    as breaks (``str.splitlines`` would, and diverge). A trailing newline does
    not start a new line, so drop a trailing "" element.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    all_lines = text.split("\n")
    if all_lines and all_lines[-1] == "":
        all_lines.pop()
    start, end = page_bounds(offset, limit)
    sliced = all_lines[start - 1 : end]
    return _format_read(abs_path, sliced, len(all_lines), offset, limit, session_id)


def _format_read(
    abs_path: str,
    lines: list[str],
    total_lines: int,
    offset: int,
    limit: int,
    session_id: str | None,
) -> str:
    """Number the sliced lines and append a paging footer (shared by both paths)."""
    start, end = page_bounds(offset, limit)
    numbered = "\n".join(f"{start + i:>6}\t{line}" for i, line in enumerate(lines))

    footer = ""
    if total_lines > end:
        footer = (
            f"\n\n... [showing lines {start}-{min(end, total_lines)} of "
            f"{total_lines}; call again with offset={end + 1} for more]"
        )

    safe_emit(
        {
            "file_data": {
                "operation": "read",
                "path": abs_path,
                "lines_returned": len(lines),
            }
        },
        session_id=session_id,
    )

    return numbered + footer


async def _read_file_sandbox(
    sbx: Any,
    abs_path: str,
    offset: int,
    limit: int,
    session_id: str | None,
) -> str:
    # Native-dev fallback (host JuiceFS absent): read through the sandbox with
    # the native filesystem API. There's no server-side range read, so we slurp
    # the whole file and slice in Python — fine for this dev-only path, but cap
    # the size first via get_info so a huge file can't OOM the worker (the host
    # path streams line-by-line and needs no such guard). Read as bytes and
    # decode with errors="replace" to stay binary-safe, matching read_user_file.
    try:
        info = await sbx.files.get_info(abs_path)
    except NotFoundException:
        return f"Error: file not found at {abs_path}"
    size = getattr(info, "size", 0) or 0
    if size > MAX_SANDBOX_READ_BYTES:
        return (
            f"Error: file is {size} bytes; exceeds the {MAX_SANDBOX_READ_BYTES}-byte "
            "sandbox-read limit — read a narrower range or run with the host mount"
        )

    try:
        raw = bytes(await sbx.files.read(abs_path, format="bytes"))
    except NotFoundException:
        # Deleted between the get_info check and the read — same answer.
        return f"Error: file not found at {abs_path}"
    text = raw.decode("utf-8", errors="replace")
    return _format_text_read(abs_path, text, offset, limit, session_id)
