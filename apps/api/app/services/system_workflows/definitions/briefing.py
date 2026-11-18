"""Briefing system workflow definitions, and how the workflow engine treats them.

Provisioned at onboarding completion and via the existing-user backfill, not on
integration connect. Both are SCHEDULE workflows in the user's timezone that run the
briefing pipeline instead of the agent (briefing_runs), so the prompt/steps here are
display metadata only.
"""

from collections.abc import Callable
from functools import partial
from uuid import uuid4

from app.constants.brief_slots import BRIEF_QUEUE, SCOUT_QUEUE
from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY
from app.constants.scouts import REFRESH_SCOUTS_TASK, SCOUT_REFRESH_LEAD
from app.constants.workflows import WorkflowDelivery
from app.models.brief_settings_models import BriefingSchedule
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from app.services.briefing.run_times import brief_slots, briefing_cron
from app.services.system_workflows.behaviour import RunAhead, SystemWorkflowBehaviour

_DEFAULT_SLOTS = brief_slots(BriefingSchedule(), DEFAULT_QUIET_HOURS)


def _daily_briefing() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Daily Briefing",
        description="Your morning brief: curates your list, looks back at yesterday, and plans today.",
        prompt=(
            "Generate the user's daily briefing: curate the todo list, compare yesterday's "
            "plan to what actually happened, and plan today's work within budget. Emit one "
            "structured briefing payload."
        ),
        is_system_workflow=True,
        # The brief delivers itself (in-app, email, the chat photo); the run's
        # own completion never notifies.
        delivery=WorkflowDelivery.SILENT,
        system_workflow_key=DAILY_BRIEFING_WORKFLOW_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            # The default schedule's slot; provisioning stamps the user's own.
            cron_expression=_DEFAULT_SLOTS[DAILY_BRIEFING_WORKFLOW_KEY].cron,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Curate, look back, and plan",
                category="gaia",
                description=(
                    "Compare yesterday's briefing to completed todos and workflow runs, "
                    "then plan today's items within budget."
                ),
            ),
        ],
    )


def _weekly_digest() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Weekly Digest",
        description="Sunday zoom-out: your week's completed work.",
        prompt=(
            "Generate the user's weekly digest: summarize the week's completed work (by GAIA "
            "and by the user). Emit one structured payload."
        ),
        is_system_workflow=True,
        # The brief delivers itself (in-app, email, the chat photo); the run's
        # own completion never notifies.
        delivery=WorkflowDelivery.SILENT,
        system_workflow_key=WEEKLY_DIGEST_WORKFLOW_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression=_DEFAULT_SLOTS[WEEKLY_DIGEST_WORKFLOW_KEY].cron,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Summarize the week",
                category="gaia",
                description=(
                    "Aggregate the week's completed todos (GAIA's and the user's) and "
                    "compile the weekly digest payload."
                ),
            ),
        ],
    )


BRIEFING_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    (DAILY_BRIEFING_WORKFLOW_KEY, _daily_briefing),
    (WEEKLY_DIGEST_WORKFLOW_KEY, _weekly_digest),
]


# A brief is no workflow to the user: never listed, a failure is the logged error and the
# next one runs, and it winds itself down (briefing.wind_down) instead of being paused. It
# runs on its own queue, its scouts refreshed on theirs ahead of its slot.
BRIEFING_BEHAVIOURS: dict[str, SystemWorkflowBehaviour] = {
    key: SystemWorkflowBehaviour(
        listed=False,
        notify_on_failure=False,
        pausable=False,
        cron_for=partial(briefing_cron, key),
        queue=BRIEF_QUEUE,
        run_ahead=RunAhead(task=REFRESH_SCOUTS_TASK, queue=SCOUT_QUEUE, lead=SCOUT_REFRESH_LEAD),
    )
    for key in (DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY)
}
