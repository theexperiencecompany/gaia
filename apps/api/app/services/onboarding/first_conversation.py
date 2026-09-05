"""Composes the conversation GAIA opens with once onboarding completes.

Deterministic and model-free here: the same answers always produce the same two
bubbles. The only model-written part, the four starting jobs offered as chips,
comes from :mod:`first_question` at Q2 and is merged by :func:`with_starting_jobs`;
when that call failed there are no job chips, only the escape hatch.

This is post-onboarding, not a pitch. The user has just sat through the wizard,
paid, and picked where GAIA texts them, so nothing here explains GAIA or reads
their answers back. Bubble one opens the door and is the one place the built-in
routines get sold, with the links to switch them on. Bubble two hands the
conversation to them, addressed by the job they gave.
"""

from pydantic import BaseModel

from app.models.chat_models import ConversationSource
from app.models.user_models import OnboardingPreferences
from app.services.onboarding.first_message import (
    _ARTICLES,
    PROFESSION_PHRASES,
)
from app.services.outbound_delivery import PLATFORM_DISPLAY_NAMES

INTEGRATIONS_PATH = "/integrations"
GMAIL_INTEGRATION_ID = "gmail"
CALENDAR_INTEGRATION_ID = "googlecalendar"


def connect_link(integration_id: str) -> str:
    """The integrations page with that app's connect flow opened on arrival."""
    return f"{INTEGRATIONS_PATH}?connect={integration_id}"


WELCOME = "Okay, you're in."
WELCOME_WITH_PLATFORM_TEMPLATE = (
    "Okay, you're in. I'm on your {platform}, so text me there anytime."
)
ROUTINES_LINE = (
    "Two things worth switching on now: connect Gmail and every morning your mail "
    "comes back sorted, replies drafted. Add Calendar and I brief you before every meeting."
)
LINKS_LINE = (
    f"[Connect Gmail]({connect_link(GMAIL_INTEGRATION_ID)}) · "
    f"[Connect Calendar]({connect_link(CALENDAR_INTEGRATION_ID)}) · "
    f"[All integrations]({INTEGRATIONS_PATH})"
)
HANDOVER_TEMPLATE = "Since you're {job}, what are we starting with?"
HANDOVER_SENTENCE_TEMPLATE = "Since {sentence}, what are we starting with?"
HANDOVER_WITHOUT_JOB = "So, what are we starting with?"
SOMETHING_ELSE_CHIP = "Something else"
_VOWELS = ("a", "e", "i", "o", "u")

#: A typed sentence turned to the second person: "I run a bakery" reads
#: "you run a bakery", "I'm a plumber" reads "you're a plumber".
_FIRST_PERSON_TO_SECOND: tuple[tuple[str, str], ...] = (
    ("i'm ", "you're "),
    ("i’m ", "you're "),
    ("i am ", "you are "),
    ("i ", "you "),
    ("we're ", "you're "),
    ("we’re ", "you're "),
    ("we ", "you "),
)


class FirstConversation(BaseModel):
    """The composed opening conversation: separate bot messages so the web renders
    them as grouped bubbles, with the chips riding the last one."""

    lines: list[str]
    follow_ups: list[str]


def _platform_label(connected_platform: str) -> str:
    source = ConversationSource.coerce(connected_platform)
    if source is None:
        return connected_platform.capitalize()
    return PLATFORM_DISPLAY_NAMES.get(source) or source.value.capitalize()


def _welcome(connected_platform: str | None) -> str:
    if not connected_platform:
        return WELCOME
    return WELCOME_WITH_PLATFORM_TEMPLATE.format(platform=_platform_label(connected_platform))


def _handover(profession: str | None) -> str:
    """ "Since you're a founder" for a pick, "Since you run a bakery" for a typed
    sentence, "Since you're a plumber" for a typed title, and the plain question
    when they skipped it or picked Other."""
    cleaned = (profession or "").strip().rstrip(".!")
    key = cleaned.lower()
    if not cleaned or key == "other":
        return HANDOVER_WITHOUT_JOB
    if key in PROFESSION_PHRASES:
        return HANDOVER_TEMPLATE.format(job=PROFESSION_PHRASES[key])
    for opener, replacement in _FIRST_PERSON_TO_SECOND:
        if key.startswith(opener):
            return HANDOVER_SENTENCE_TEMPLATE.format(
                sentence=f"{replacement}{cleaned[len(opener) :]}"
            )
    title = cleaned.split(maxsplit=1)[1] if key.startswith(_ARTICLES) else cleaned
    title = f"{title[0].lower()}{title[1:]}"
    article = "an" if title.startswith(_VOWELS) else "a"
    return HANDOVER_TEMPLATE.format(job=f"{article} {title}")


def compose_first_conversation(
    preferences: OnboardingPreferences, connected_platform: str | None
) -> FirstConversation:
    """The two bubbles GAIA opens with. The escape-hatch chip is always offered;
    the model-written jobs join it in :func:`with_starting_jobs`."""
    opening = f"{_welcome(connected_platform)} {ROUTINES_LINE}\n\n{LINKS_LINE}"
    return FirstConversation(
        lines=[opening, _handover(preferences.profession)],
        follow_ups=[SOMETHING_ELSE_CHIP],
    )


def with_starting_jobs(composed: FirstConversation, chips: list[str]) -> FirstConversation:
    """The same conversation with the model-written starting jobs ahead of the
    escape hatch."""
    return FirstConversation(lines=composed.lines[:], follow_ups=[*chips, SOMETHING_ELSE_CHIP])
