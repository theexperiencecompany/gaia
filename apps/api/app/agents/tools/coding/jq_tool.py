"""`jq` tool — filter an offloaded JSON/JSONL workspace file.

Runs the `jq` binary over a single workspace file. Execution hardening
(argv/no-shell, secret-free env, output cap, timeout) lives in `_filter.py`.
"""

from __future__ import annotations

import re
from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._filter import run_file_filter
from app.decorators import with_doc, with_rate_limiting
from app.services.storage import FsOps, fs_timer
from app.templates.docstrings.coding_tools_docs import JQ_TOOL
from shared.py.wide_events import log

# jq's module system (`import "x" as $d {search:"/path"};`, `include "x";`) reads
# files OFF DISK from a program-supplied path — argv `--` cannot stop it because
# it's in-language, not a flag. That is an arbitrary cross-workspace file-read
# primitive, so reject any module directive. Data mining never needs jq modules.
#
# A naive `\b(import|include)\s*"` regex is bypassable: jq treats a `#` line
# comment as inter-token whitespace, so `include #x<newline> "mod"` is a valid
# directive that the regex misses. Neutralize string literals first (so the word
# inside data like `contains(" import ")` isn't flagged), THEN strip `#` comments
# (so they can't smuggle the keyword away from its string), THEN match the bare
# keyword token. Strings are stripped before comments because a `#` inside a
# string is not a comment.
_JQ_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_JQ_COMMENT = re.compile(r"#[^\n]*")
_MODULE_KEYWORD = re.compile(r"(?<![\w.])(?:import|include)\b")


def _has_module_directive(query: str) -> bool:
    stripped = _JQ_COMMENT.sub(" ", _JQ_STRING.sub('""', query))
    return bool(_MODULE_KEYWORD.search(stripped))


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
    if _has_module_directive(query):
        return "Error: jq module loading (import/include) is not allowed."
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
