"""
Calendar system workflow definitions, and the recipe each one ships with.

These are auto-provisioned when a user connects Google Calendar.
Each tuple is (system_workflow_key, factory function) — factories are called at
provisioning time so each user gets unique step IDs rather than sharing module-load IDs.
A recipe is the playbook stored beside the workflow when it is provisioned, so
its first fire replays instead of reasoning the work out.
"""

from collections.abc import Callable
from uuid import uuid4

from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.workflows import WorkflowDelivery
from app.models.playbook_models import AskSlot, ForEachStep, PlaybookBody, ToolStep
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
        description="Researches attendees and prepares a briefing before each meeting.",
        prompt=(
            "Prepare a meeting briefing for the upcoming calendar event from the trigger. "
            "Get the event details (title, attendees, description, location/link). "
            "Skip solo personal events (gym, lunch, focus time). "
            "For external attendees, search the web for LinkedIn, company info, and recent news. "
            "Search user memory for past interactions with attendees. "
            "Search Gmail for recent threads related to the meeting topic. "
            "Compile a structured brief: who the user is meeting, suggested talking points, "
            "open action items, relevant background, and the join link if available."
        ),
        is_system_workflow=True,
        source_integration="googlecalendar",
        system_workflow_key="calendar:meeting_prep",
        # A pre-meeting brief is only useful before the meeting starts.
        delivery=WorkflowDelivery.NOW,
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
                    "(5) Join link if available."
                ),
            ),
        ],
    )


def _meeting_reminder() -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Meeting Reminder",
        description="A heads-up 10 minutes before any event with the join link.",
        prompt=(
            "Send the user a short reminder for the upcoming calendar event from the trigger. "
            "Include the event title, time, and join link or location if available. "
            "Keep it to 2-3 lines. This is just a heads-up, not a full briefing."
        ),
        is_system_workflow=True,
        source_integration="googlecalendar",
        system_workflow_key="calendar:meeting_reminder",
        delivery=WorkflowDelivery.NOW,
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


#: The event a calendar_event_starting_soon fire is about, as the trigger payload names it.
_TRIGGERING_EVENT = {
    "event_id": "$trigger.trigger_data.event_id",
    "calendar_id": "$trigger.trigger_data.calendar_id",
}


def _get_triggering_event() -> ToolStep:
    return ToolStep(
        id="event",
        tool=EXECUTE_TOOL_NAME,
        args={
            "task_description": "Looking up the event",
            "tool_name": "GOOGLECALENDAR_CUSTOM_GET_EVENT",
            "data": {"events": [dict(_TRIGGERING_EVENT)]},
        },
    )


def _meeting_reminder_recipe() -> PlaybookBody:
    return PlaybookBody(
        description="Look up the event that is about to start, then write a short heads-up.",
        steps=[_get_triggering_event()],
        result_brief=(
            "Write a 2-3 line heads-up for the event the event step returned: its title, "
            "when it starts in the user's local time, and its video join link or location "
            "if it has one (say plainly if it has neither). It is a heads-up, not a briefing. "
            "Never mention workflows, shortcuts or steps."
        ),
    )


def _meeting_prep_recipe() -> PlaybookBody:
    return PlaybookBody(
        description=(
            "Look up the event, recall what memory holds about its people and topic, "
            "research its external attendees, then write the briefing."
        ),
        steps=[
            _get_triggering_event(),
            ToolStep(
                id="memory",
                tool="search_memory",
                args={
                    "query": {"$ask": "a memory search for the people in this event and its topic"}
                },
            ),
            ForEachStep(
                id="research",
                tool="web_search_tool",
                for_each=AskSlot.model_validate(
                    {
                        "$ask": (
                            "the external attendees of this event worth researching: not the "
                            "user and not people at the user's own company; none for a solo "
                            "or internal event"
                        )
                    }
                ),
                max_items=3,
                args={
                    "query_text": {
                        "$ask": "a web search for this attendee: their name, company and role"
                    }
                },
            ),
        ],
        result_brief=(
            "If the event is a solo personal one (gym, lunch, focus time, no other attendees), "
            "say in one line that no briefing is needed. Otherwise write a structured brief "
            "from the event, memory and research steps: (1) who the user is meeting and the "
            "key context about them, (2) suggested agenda or talking points, (3) open action "
            "items to raise, (4) relevant background from past interactions, (5) the join link "
            "or location. Never mention workflows, shortcuts or steps."
        ),
    )


CALENDAR_SYSTEM_RECIPES: dict[str, Callable[[], PlaybookBody]] = {
    "calendar:meeting_prep": _meeting_prep_recipe,
    "calendar:meeting_reminder": _meeting_reminder_recipe,
}


#: Prompts earlier releases provisioned, still on stored workflows a user never edited:
#: the reminder's wording before #1296 is on 138 of 145 Meeting Reminders (prod, 2026-11-03).
PREVIOUSLY_SHIPPED_PROMPTS: dict[str, tuple[str, ...]] = {
    "calendar:meeting_reminder": (
        "Send the user a short reminder for the upcoming calendar event from the trigger. "
        "Include the event title, time, and join link or location if available. "
        "Keep it to 2-3 lines \u2014 this is just a heads-up, not a full briefing.",
    ),
}
