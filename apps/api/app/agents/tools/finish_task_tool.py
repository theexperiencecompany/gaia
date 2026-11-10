"""Finish task tool: how a subagent, and the executor, end a run.

The tool name MUST match `FINISH_TASK_NAME` in `app.constants.general` —
the bigtool router and subagent runner key off that constant.
"""

from langchain_core.tools import tool

from app.agents.core.task_report import render_task_report
from app.constants.general import FINISH_TASK_NAME
from app.models.task_report_models import FinishTaskArgs


@tool(
    args_schema=FinishTaskArgs,
    description=(
        "Finish the task and return the final result to the parent. `result` must "
        "contain the ACTUAL deliverable in full, not a description of what you did; "
        "the parent only sees what you put here. The executor also files its report "
        "here: outcome, facts, answer, scope, needs_you and failure."
    ),
)
async def finish_task(**fields: object) -> str:
    return render_task_report(FinishTaskArgs.model_validate(fields))


# Import-time guarantee that a rename doesn't silently break the
# finish_task → END short-circuit.
# nosec B101 — intentional invariant, not security-sensitive.
assert finish_task.name == FINISH_TASK_NAME, (  # nosec B101
    f"finish_task tool name mismatch: tool exposes {finish_task.name!r} but "
    f"FINISH_TASK_NAME is {FINISH_TASK_NAME!r}"
)
