"""Finish task tool for subagent completion.

The tool name MUST match FINISH_TASK_NAME in app.constants.general —
the bigtool router and subagent runner key off that constant.
"""

from langchain_core.tools import tool

from app.constants.general import FINISH_TASK_NAME


@tool(
    description=(
        "Finish the task and return the final result to the parent. `result` must "
        "contain the ACTUAL deliverable in full, not a description of what you did. "
        "If the task asked for a list, records, or data, include every item with its "
        "details (do not return a count, a few highlights, or a 'successfully "
        "retrieved X' summary in place of the data). The data itself is the result; "
        "the parent only sees what you put here."
    )
)
async def finish_task(result: str) -> str:
    return result


# Import-time guarantee that a rename doesn't silently break the
# finish_task → END short-circuit.
# nosec B101 — intentional invariant, not security-sensitive.
assert finish_task.name == FINISH_TASK_NAME, (  # nosec B101
    f"finish_task tool name mismatch: tool exposes {finish_task.name!r} but "
    f"FINISH_TASK_NAME is {FINISH_TASK_NAME!r}"
)
