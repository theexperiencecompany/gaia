"""`jq` tool — filter an offloaded JSON/JSONL workspace file.

Runs the `jq` binary over a single workspace file. Execution hardening
(argv/no-shell, secret-free env, output cap, timeout) lives in `_filter.py`.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._filter import run_file_filter
from app.decorators import with_doc, with_rate_limiting
from app.services.storage import FsOps, fs_timer
from app.templates.docstrings.coding_tools_docs import JQ_TOOL
from shared.py.wide_events import log


@tool
@with_rate_limiting("workspace_jq")
@with_doc(JQ_TOOL)
async def jq(
    config: RunnableConfig,
    query: Annotated[str, "jq program, e.g. 'select(.from|contains(\"x\"))|.subject'"],
    path: Annotated[str, "JSON/JSONL file inside the workspace (relative = session scratch)"],
    raw: Annotated[bool, "Raw output (-r): strip JSON quotes from string results"] = False,
) -> str:
    """Filter a workspace JSON/JSONL file with jq, host-side (no sandbox)."""
    log.set(tool={"name": "jq", "action": "filter"})
    # `--` ends option parsing so a query starting with `-` is treated as the
    # filter, never a jq flag.
    args = ["-r", "--", query] if raw else ["--", query]
    async with fs_timer(FsOps.TOOL_JQ):
        return await run_file_filter(
            config=config,
            binary="jq",
            args=args,
            path=path,
            ok_returncodes=(0,),
            empty_message="(no matches)",
            error_label="jq",
        )
