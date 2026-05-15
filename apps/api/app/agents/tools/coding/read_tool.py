"""Persistent `read` tool — read files from the user's E2B workspace."""

from __future__ import annotations

from typing import Annotated

from shared.py.wide_events import log
from app.agents.tools.coding._context import (
    canonical_path,
    get_session_id,
    get_user_id,
    safe_emit,
    sh_quote,
)
from app.decorators import with_doc, with_rate_limiting
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.templates.docstrings.coding_tools_docs import READ_TOOL
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

DEFAULT_LIMIT = 2000
MAX_LIMIT = 10_000


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

    if offset < 0:
        offset = 0
    limit = max(1, min(limit, MAX_LIMIT))

    try:
        async with acquire_sandbox(user_id) as sbx:
            return await _read_file(sbx, abs_path, offset, limit, session_id)
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"read tool failed: {e}", exc_info=True)
        return f"Error reading file: {e}"


async def _read_file(
    sbx: object,
    abs_path: str,
    offset: int,
    limit: int,
    session_id: str | None,
) -> str:
    # Use `awk` to slice the requested range without loading the entire file.
    start = max(1, offset) if offset > 0 else 1
    end = start + limit - 1
    cmd = (
        f"if [ ! -f {sh_quote(abs_path)} ]; then echo __NOT_FOUND__; "
        f"else awk 'NR>={start} && NR<={end}' {sh_quote(abs_path)}; fi"
    )
    result = await sbx.commands.run(cmd, timeout=15)  # type: ignore[attr-defined]
    stdout = getattr(result, "stdout", "") or ""
    if stdout.strip() == "__NOT_FOUND__":
        return f"Error: file not found at {abs_path}"

    lines = stdout.splitlines()
    numbered = "\n".join(f"{start + i:>6}\t{line}" for i, line in enumerate(lines))

    # Footer for paging info
    total_cmd = f"wc -l < {sh_quote(abs_path)}"
    total_result = await sbx.commands.run(total_cmd, timeout=5)  # type: ignore[attr-defined]
    total_lines_str = (getattr(total_result, "stdout", "") or "").strip()
    try:
        total_lines = int(total_lines_str)
    except ValueError:
        total_lines = start + len(lines) - 1

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
