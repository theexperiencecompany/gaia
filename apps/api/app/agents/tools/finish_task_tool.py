"""Finish task tool for subagent completion.

The tool name MUST match `FINISH_TASK_NAME` in `app.constants.general` —
the bigtool router and subagent runner key off that constant.
"""

from langchain_core.tools import tool

from app.constants.general import FINISH_TASK_NAME


@tool(description="Finish the task and return the final result to the parent.")
async def finish_task(result: str) -> str:
    return result


# Hard guarantee at import time that the decorated tool's name still
# matches the routing constant. If someone renames the function without
# updating FINISH_TASK_NAME, this fires immediately instead of silently
# breaking the finish_task → END short-circuit.
# nosec B101 — intentional import-time invariant; the message is for developers,
# not security-sensitive runtime data.
assert finish_task.name == FINISH_TASK_NAME, (  # nosec B101
    f"finish_task tool name mismatch: tool exposes {finish_task.name!r} but "
    f"FINISH_TASK_NAME is {FINISH_TASK_NAME!r}"
)
