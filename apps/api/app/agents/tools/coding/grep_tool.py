"""`grep` tool — search a single offloaded workspace file.

Runs the `grep` binary over one workspace file. Execution hardening
(argv/no-shell, secret-free env, output cap, timeout) lives in `_filter.py`.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._filter import run_file_filter
from app.decorators import with_doc, with_rate_limiting
from app.services.storage import FsOps, fs_timer
from app.templates.docstrings.coding_tools_docs import GREP_TOOL
from shared.py.wide_events import log


@tool
@with_rate_limiting("workspace_grep")
@with_doc(GREP_TOOL)
async def grep(
    config: RunnableConfig,
    pattern: Annotated[str, "Regular expression (or literal text) to match"],
    path: Annotated[str, "File inside the workspace (relative = session scratch)"],
    ignore_case: Annotated[bool, "Case-insensitive match (-i)"] = False,
) -> str:
    """Search a workspace file with grep, host-side (no sandbox)."""
    log.set(tool={"name": "grep", "action": "search"})
    # -n: prefix matches with line numbers. -e: the pattern is data, never a flag.
    # trailing `--`: ends options so the (absolute) file path can't be a flag either.
    args = ["-n", "-i", "-e", pattern, "--"] if ignore_case else ["-n", "-e", pattern, "--"]
    async with fs_timer(FsOps.TOOL_GREP):
        return await run_file_filter(
            config=config,
            binary="grep",
            args=args,
            path=path,
            # grep exits 1 when there are no matches — a normal outcome, not an error.
            ok_returncodes=(0, 1),
            empty_message="(no matches)",
            error_label="grep",
        )
