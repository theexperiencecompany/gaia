"""Composes the conversation GAIA opens with once onboarding completes.

Deterministic and model-free here: the same answers always produce the same two
bubbles. The only personalised part, the four starting jobs offered as chips, is
written by the model at Q2 (:mod:`first_question`) and merged in by
:func:`with_starting_jobs`; when that call failed there are simply no chips.

This is post-onboarding, not a pitch. The user has just sat through the wizard,
paid, and picked where GAIA texts them, so nothing here explains GAIA or reads
their answers back. Bubble one is the one place the built-in routines get sold,
with the links to switch them on. Bubble two hands the conversation to them.
"""

from pydantic import BaseModel

INTEGRATIONS_PATH = "/integrations"
GMAIL_INTEGRATION_ID = "gmail"
CALENDAR_INTEGRATION_ID = "googlecalendar"


def connect_link(integration_id: str) -> str:
    """The integrations page with that app's connect flow opened on arrival."""
    return f"{INTEGRATIONS_PATH}?connect={integration_id}"


ROUTINES_LINE = (
    "Connect Gmail and every morning your mail comes back sorted, replies drafted. "
    "Add Calendar and I brief you before every meeting."
)
LINKS_LINE = (
    f"[Connect Gmail]({connect_link(GMAIL_INTEGRATION_ID)}) · "
    f"[Connect Calendar]({connect_link(CALENDAR_INTEGRATION_ID)}) · "
    f"[All integrations]({INTEGRATIONS_PATH})"
)
OPENING_LINE = f"{ROUTINES_LINE}\n\n{LINKS_LINE}"
HANDOVER_LINE = "What are we starting with?"


class FirstConversation(BaseModel):
    """The composed opening conversation: separate bot messages so the web renders
    them as grouped bubbles, with the starting-job chips riding the last one."""

    lines: list[str]
    follow_ups: list[str]


def compose_first_conversation() -> FirstConversation:
    """The two bubbles GAIA opens with. No chips yet: see :func:`with_starting_jobs`."""
    return FirstConversation(lines=[OPENING_LINE, HANDOVER_LINE], follow_ups=[])


def with_starting_jobs(composed: FirstConversation, chips: list[str]) -> FirstConversation:
    """The same conversation with the model-written starting jobs as its chips."""
    return FirstConversation(lines=composed.lines[:], follow_ups=list(chips))
