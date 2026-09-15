"""
Briefing system workflow definitions.

Provisioned for every user at onboarding completion, not per integration: the
prompts read whatever is connected and omit the rest. Each tuple is
(system_workflow_key, factory function) — factories are called at provisioning
time so each user gets unique step IDs rather than sharing module-load IDs.
"""

from collections.abc import Callable
from uuid import uuid4

from app.agents.prompts.briefing_prompts import DAILY_BRIEFING_PROMPT, WEEKLY_DIGEST_PROMPT
from app.constants.briefing import (
    BRIEFING_DAILY_CRON,
    BRIEFING_DAILY_KEY,
    BRIEFING_WEEKLY_CRON,
    BRIEFING_WEEKLY_KEY,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)


def _daily_briefing() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Daily Briefing",
        description=(
            "Every morning: today's meetings, what is waiting on you, and what moved, "
            "read from the integrations you have connected."
        ),
        prompt=DAILY_BRIEFING_PROMPT,
        is_system_workflow=True,
        system_workflow_key=BRIEFING_DAILY_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression=BRIEFING_DAILY_CRON,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Read today from each connected integration",
                category="gaia",
                description=(
                    "One fixed read-only call per connected integration, in order: "
                    "calendar events today, inbox threads from the last 24 hours, "
                    "pull requests, issues, pages, mentions from the last 24 hours, "
                    "and todos due today. Nothing for integrations that are not connected."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Write the briefing",
                category="gaia",
                description=(
                    "Plain text, at most 12 lines: the shape of the day, what is waiting "
                    "on the user, what moved. One or two lines on an empty day. "
                    "A final 'Next:' line naming one thing GAIA could do that it is not yet."
                ),
            ),
        ],
    )


def _weekly_digest() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Weekly Digest",
        description=(
            "Sunday evening: the receipt for the week, numbers first, "
            "what GAIA did and what you did across your connected integrations."
        ),
        prompt=WEEKLY_DIGEST_PROMPT,
        is_system_workflow=True,
        system_workflow_key=BRIEFING_WEEKLY_KEY,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression=BRIEFING_WEEKLY_CRON,
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Read the week from GAIA and each connected integration",
                category="gaia",
                description=(
                    "Workflow and todo statistics, then one fixed read-only call per "
                    "connected integration over the last 7 days, in order. "
                    "Nothing for integrations that are not connected."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Write the digest",
                category="gaia",
                description=(
                    "The fixed WEEK OF / GAIA / YOU / NOTABLE / NEXT shape, counts before "
                    "words, one YOU line per connected integration."
                ),
            ),
        ],
    )


BRIEFING_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    (BRIEFING_DAILY_KEY, _daily_briefing),
    (BRIEFING_WEEKLY_KEY, _weekly_digest),
]
