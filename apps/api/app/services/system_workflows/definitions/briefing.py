"""Briefing system workflow definitions.

Provisioned at onboarding completion and via the existing-user backfill, not on
integration connect. Both are SCHEDULE workflows in the user's timezone; the workflow
ARQ path routes their system_workflow_key into the briefing service, so the
prompt/steps here are display metadata only.
"""

from collections.abc import Callable
from uuid import uuid4

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_CRON,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)
from app.constants.workflows import WorkflowDelivery
from app.models.briefing_models import BriefingSchedule
from app.models.notification.notification_models import default_quiet_hours
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from app.services.briefing.schedule import daily_briefing_cron


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
            cron_expression=daily_briefing_cron(BriefingSchedule(), default_quiet_hours()),
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
            cron_expression=WEEKLY_DIGEST_CRON,
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
