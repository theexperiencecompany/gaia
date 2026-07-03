"""Briefing system workflow definitions.

Provisioned for every user at onboarding completion and via the existing-user
backfill — not on integration connect. Both are SCHEDULE workflows in the user's
timezone; the workflow ARQ path special-cases their ``system_workflow_key`` to
route into the briefing service instead of the generic chat execution, so the
``prompt``/``steps`` here are display metadata for the workflows UI, not the
generation logic (that lives in ``app/agents/prompts/briefing_prompts.py``).
"""

from collections.abc import Callable
from uuid import uuid4

from app.constants.briefing import (
    DAILY_BRIEFING_CRON,
    DAILY_BRIEFING_WORKFLOW_KEY,
    OVERNIGHT_WORK_CRON,
    OVERNIGHT_WORK_WORKFLOW_KEY,
    WEEKLY_DIGEST_CRON,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)


def _overnight_work() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Overnight Work",
        description="GAIA's night shift: works your goals so the morning brief reports finished work.",
        prompt=(
            "Decompose the user's stated goals into concrete internal work and execute it "
            "now: research, lists, drafts, documents. Stage anything outward-facing as a "
            "proposal awaiting approval."
        ),
        is_system_workflow=True,
        system_workflow_key=OVERNIGHT_WORK_WORKFLOW_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression=OVERNIGHT_WORK_CRON,
            enabled=True,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Work the goals",
                category="gaia",
                description=(
                    "For each stated goal, complete or stage concrete work tonight: build the "
                    "lists, write the drafts, produce the documents; queue outward sends as "
                    "proposals for the morning tap."
                ),
            ),
        ],
    )


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
        system_workflow_key=DAILY_BRIEFING_WORKFLOW_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression=DAILY_BRIEFING_CRON,
            enabled=True,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Curate, look back, and plan",
                category="gaia",
                description=(
                    "Sweep the todo list (expire stale proposals), compare yesterday's briefing "
                    "to completed todos and workflow runs, then plan today's items within budget."
                ),
            ),
        ],
    )


def _weekly_digest() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Weekly Digest",
        description="Sunday zoom-out: your week's completed work, hours saved, and streak.",
        prompt=(
            "Generate the user's weekly digest: summarize the week's completed work split by "
            "assignee, estimate hours saved, and report the streak. Emit one structured payload."
        ),
        is_system_workflow=True,
        system_workflow_key=WEEKLY_DIGEST_WORKFLOW_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression=WEEKLY_DIGEST_CRON,
            enabled=True,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Summarize the week",
                category="gaia",
                description=(
                    "Aggregate the week's completed todos by assignee, estimate hours saved, "
                    "compute the streak, and compile the weekly digest payload."
                ),
            ),
        ],
    )


BRIEFING_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    (OVERNIGHT_WORK_WORKFLOW_KEY, _overnight_work),
    (DAILY_BRIEFING_WORKFLOW_KEY, _daily_briefing),
    (WEEKLY_DIGEST_WORKFLOW_KEY, _weekly_digest),
]
