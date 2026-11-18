"""How the briefing system workflows run: the briefing pipeline, in place of the agent turn.

Apart from definitions/briefing.py because the pipeline sits on the agent stack, and the
provisioner that reads the definitions is itself imported below it (oauth_service).
"""

from collections.abc import Awaitable, Callable

from app.constants.briefing import (
    BRIEFING_RUN_SUMMARIES,
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    BriefingRunOutcome,
)
from app.models.workflow_models import Workflow
from app.services.briefing.daily import run_daily_briefing
from app.services.briefing.held import release_after_daily_run
from app.services.briefing.weekly import run_weekly_digest
from shared.py.wide_events import log


def _run_summary(outcome: BriefingRunOutcome) -> str:
    log.set_ns("workflow", briefing_outcome=outcome.value)
    return BRIEFING_RUN_SUMMARIES[outcome]


async def _run_daily_briefing(workflow: Workflow) -> str:
    outcome = await run_daily_briefing(workflow.user_id)
    await release_after_daily_run(workflow.user_id, outcome)
    return _run_summary(outcome)


async def _run_weekly_digest(workflow: Workflow) -> str:
    return _run_summary(await run_weekly_digest(workflow.user_id))


BRIEFING_RUNS: dict[str, Callable[[Workflow], Awaitable[str]]] = {
    DAILY_BRIEFING_WORKFLOW_KEY: _run_daily_briefing,
    WEEKLY_DIGEST_WORKFLOW_KEY: _run_weekly_digest,
}
