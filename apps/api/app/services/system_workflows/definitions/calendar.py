"""
Calendar system workflow definitions.

These are auto-provisioned when a user connects Google Calendar.
Each tuple is (system_workflow_key, factory function) — factories are called at
provisioning time so each user gets unique step IDs rather than sharing module-load IDs.
"""

from collections.abc import Callable
from uuid import uuid4

from app.models.trigger_configs import CalendarEventStartingSoonConfig
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)


def _meeting_prep() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Meeting Briefing",
        description=(
            "60 minutes before every calendar event, GAIA researches attendees, "
            "reviews relevant emails and context, prepares talking points and agenda, "
            "and sends you a briefing so you walk in prepared."
        ),
        is_system_workflow=True,
        source_integration="googlecalendar",
        system_workflow_key="calendar:meeting_prep",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="calendar_event_starting_soon",
            enabled=True,
            trigger_data=CalendarEventStartingSoonConfig(
                calendar_ids=["all"],
                minutes_before_start=60,
                include_all_day=False,
            ),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Assess the meeting",
                category="googlecalendar",
                description=(
                    "Get full event details: title, description, attendees, location/link. "
                    "Skip if solo personal event (gym, lunch, focus time). "
                    "For 1:1s, focus on relationship history. "
                    "For group meetings, focus on agenda and open items."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Research attendees and gather context",
                category="gmail",
                description=(
                    "For external attendees: search web for LinkedIn, recent news, company info. "
                    "Search memory for past interactions. Search Gmail for recent threads with them. "
                    "For internal attendees: search memory and open todos for shared context. "
                    "Also search Gmail for threads from the past 2 weeks on this event's topic."
                ),
            ),
            WorkflowStep(
                id=str(uuid4()),
                title="Prepare meeting brief",
                category="gaia",
                description=(
                    "Synthesize all context into a structured brief: "
                    "(1) Who you're meeting and key context about them, "
                    "(2) Suggested agenda / talking points, "
                    "(3) Open action items to address, "
                    "(4) Relevant background from past interactions, "
                    "(5) Join link if available. "
                    "Save the brief as a note or document."
                ),
            ),
        ],
    )


def _meeting_reminder() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Meeting Reminder",
        description=(
            "A simple heads-up 10 minutes before any calendar event so you don't miss it. "
            "Includes the join link if available."
        ),
        is_system_workflow=True,
        source_integration="googlecalendar",
        system_workflow_key="calendar:meeting_reminder",
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="calendar_event_starting_soon",
            enabled=True,
            trigger_data=CalendarEventStartingSoonConfig(
                calendar_ids=["all"],
                minutes_before_start=10,
                include_all_day=False,
            ),
        ),
        steps=[
            WorkflowStep(
                id=str(uuid4()),
                title="Prepare meeting summary",
                category="gaia",
                description=(
                    "Pull the event details: title, time, location or video join link, "
                    "and any description. Format a concise 2-3 line heads-up summary "
                    "ready to surface to the user."
                ),
            ),
        ],
    )


CALENDAR_SYSTEM_WORKFLOWS: list[tuple[str, Callable[[], CreateWorkflowRequest]]] = [
    ("calendar:meeting_prep", _meeting_prep),
    ("calendar:meeting_reminder", _meeting_reminder),
]
