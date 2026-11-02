"""Composes the conversation GAIA opens with once onboarding completes.

Deterministic and model-free here: the same answers always produce the same two
bubbles. The only model-written part, the four starting jobs offered as chips,
comes from :mod:first_question at Q2 and is merged by :func:with_starting_jobs;
when that call failed there are no chips, and the composer is the way in.

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
from app.services.onboarding.welcome_copy import (
    DEFAULT_LANGUAGE,
    WELCOME_COPY,
    WelcomeCopy,
    welcome_copy,
)

INTEGRATIONS_PATH = "/integrations"
GMAIL_INTEGRATION_ID = "gmail"
CALENDAR_INTEGRATION_ID = "googlecalendar"


def connect_link(integration_id: str) -> str:
    """Return the integrations page with that app's connect flow opened on arrival."""
    return f"{INTEGRATIONS_PATH}?connect={integration_id}"


#: The buttons under the routines bubble: rendered by the web as a plain row of
#: buttons outside the bubble (``connect_options`` in ToolRenderers), same tab,
#: opening the app's connect flow on arrival exactly as the old links did.
CONNECT_OPTIONS_TOOL_NAME = "connect_options"
HANDOVER_TEMPLATE = "You're {job}. What's first?"
HANDOVER_SENTENCE_TEMPLATE = "{sentence}. What's first?"
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
    """The composed opening conversation.

    ``opening`` is one idea per bubble, welcome to the two routines, in one bot
    message; the connect buttons ride a message of their own after it; the
    ``question`` is the last bot message, with the chips riding it. Separate
    messages because a message's cards render after all of its bubbles.
    """

    opening: list[str]
    question: str
    follow_ups: list[str]
    connect_options: list[dict[str, str]]

    @property
    def lines(self) -> list[str]:
        """Every bubble in order, for anything that reads the thread as text."""
        return [*self.opening, self.question]

    def connect_tool_data(self) -> dict[str, object]:
        return {"tool_name": CONNECT_OPTIONS_TOOL_NAME, "data": {"options": self.connect_options}}


def _connect_options(copy: WelcomeCopy) -> list[dict[str, str]]:
    return [
        {
            "integration_id": GMAIL_INTEGRATION_ID,
            "label": copy.connect_gmail,
            "href": connect_link(GMAIL_INTEGRATION_ID),
        },
        {
            "integration_id": CALENDAR_INTEGRATION_ID,
            "label": copy.connect_calendar,
            "href": connect_link(CALENDAR_INTEGRATION_ID),
        },
        {"label": copy.all_integrations, "href": INTEGRATIONS_PATH},
    ]


def platform_label(connected_platform: str) -> str:
    """Return the platform's friendly name for user-facing copy and prompt text."""
    source = ConversationSource.coerce(connected_platform)
    if source is None:
        return connected_platform.capitalize()
    return source.display_name


def _handover_line(copy: WelcomeCopy, connected_platform: str | None) -> str:
    if not connected_platform:
        return copy.handover_line
    platform = copy.platform_template.format(platform=platform_label(connected_platform))
    return copy.handover_line + platform


def _handover(profession: str | None) -> str | None:
    """Build the English handover line ("You're a founder. What's first?"), or None if skipped/Other."""
    cleaned = (profession or "").strip().rstrip(".!")
    key = cleaned.lower()
    if not cleaned or key == "other":
        return None
    if key in PROFESSION_PHRASES:
        return HANDOVER_TEMPLATE.format(job=PROFESSION_PHRASES[key])
    for opener, replacement in _FIRST_PERSON_TO_SECOND:
        if key.startswith(opener):
            sentence = f"{replacement}{cleaned[len(opener) :]}"
            return HANDOVER_SENTENCE_TEMPLATE.format(
                sentence=f"{sentence[0].upper()}{sentence[1:]}"
            )
    title = cleaned.split(maxsplit=1)[1] if key.startswith(_ARTICLES) else cleaned
    title = f"{title[0].lower()}{title[1:]}"
    article = "an" if title.startswith(_VOWELS) else "a"
    return HANDOVER_TEMPLATE.format(job=f"{article} {title}")


def compose_first_conversation(
    preferences: OnboardingPreferences, connected_platform: str | None
) -> FirstConversation:
    """Build the bubbles GAIA opens with, in the user's browser language.

    Outside English the question skips the job: a profession rendered into a
    gendered language guesses the reader's gender. The chips are only ever the
    model-written jobs, added by with_starting_jobs.
    """
    copy = welcome_copy(preferences.language)
    english = copy is WELCOME_COPY[DEFAULT_LANGUAGE]
    question = (_handover(preferences.profession) if english else None) or copy.whats_first
    return FirstConversation(
        opening=[
            copy.welcome,
            _handover_line(copy, connected_platform),
            f"{copy.routines_intro}\n- {copy.gmail_line}\n- {copy.calendar_line}",
        ],
        question=question,
        follow_ups=[],
        connect_options=_connect_options(copy),
    )


def with_starting_jobs(composed: FirstConversation, chips: list[str]) -> FirstConversation:
    """Return composed with the model-written starting jobs as its chips."""
    return composed.model_copy(update={"follow_ups": list(chips)})
