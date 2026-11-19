"""How the briefing system workflows run: the briefing pipeline, in place of the agent turn.

Apart from definitions/briefing.py because the pipeline sits on the agent stack, and the
provisioner that reads the definitions is itself imported below it (oauth_service).
"""

from collections.abc import Awaitable, Callable
from functools import partial

from app.constants.briefing import (
    BRIEFING_KIND_BY_WORKFLOW_KEY,
    BRIEFING_RUN_SUMMARIES,
    BriefingKind,
)
from app.models.workflow_models import Workflow
from app.services.briefing.held import release_after_daily_run
from app.services.briefing.pipeline import run_brief
from shared.py.wide_events import log


async def _run_brief(kind: BriefingKind, workflow: Workflow) -> str:
    outcome = await run_brief(workflow.user_id, kind)
    # The weekly digest never carries held results, so only the daily run lets them go.
    if kind is BriefingKind.DAILY:
        await release_after_daily_run(workflow.user_id, outcome)
    log.set_ns("workflow", briefing_outcome=outcome.value)
    return BRIEFING_RUN_SUMMARIES[outcome]


BRIEFING_RUNS: dict[str, Callable[[Workflow], Awaitable[str]]] = {
    key: partial(_run_brief, kind) for key, kind in BRIEFING_KIND_BY_WORKFLOW_KEY.items()
}
