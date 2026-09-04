"""Composes the conversation GAIA opens with once onboarding completes.

Deterministic and LLM-free, like :mod:`first_message` — the same answers always
produce the same conversation. Where ``first_message`` writes the USER's opener
(sent as their turn on the bot surfaces), this writes GAIA's, seeded server-side
as an unread conversation the web lands the user in.

Every user-visible string is a module constant so the copy can be edited in one
place without reading the assembly logic.
"""

from pydantic import BaseModel

from app.models.chat_models import ConversationSource, ToolDataEntry
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_message import (
    _ARTICLES,
    _SENTENCE_OPENERS,
    _join,
)
from app.services.outbound_delivery import PLATFORM_DISPLAY_NAMES

#: Q1 slugs as GAIA would name the user back — one word, no article, so they
#: drop straight into the line-1 list beside the week statements. Mirrors the
#: keys of ``PROFESSION_PHRASES`` in :mod:`first_message`.
PROFESSION_WORDS: dict[str, str] = {
    "founder": "founder",
    "executive": "executive",
    "sales": "in sales",
    "product": "in product",
    "creative": "creative",
    "engineering": "engineer",
    "marketing": "in marketing",
    "finance": "in finance",
    "student": "student",
}

#: ``NEED_PHRASES`` (the user's first person) turned around into GAIA's voice, so
#: line 1 reads as one list of things GAIA already knows about their week.
NEED_CLAUSES: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: "drowning in email",
    OnboardingNeed.CALENDAR: "back-to-back meetings",
    OnboardingNeed.BRIEFINGS: "mornings that start behind",
    OnboardingNeed.TODOS: "follow-ups slipping through",
    OnboardingNeed.MEMORY: "re-explaining yourself",
    OnboardingNeed.RESEARCH: "research eating your evenings",
    OnboardingNeed.AUTOMATION: "the same chores every single day",
    OnboardingNeed.REACH: "wanting me wherever you are",
}

#: One chip per need, in the order the user picked them.
NEED_FOLLOW_UPS: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: "Sort my inbox",
    OnboardingNeed.CALENDAR: "What's on my calendar this week?",
    OnboardingNeed.BRIEFINGS: "Set up my morning brief",
    OnboardingNeed.TODOS: "Track my follow-ups",
    OnboardingNeed.MEMORY: "Remember this about me",
    OnboardingNeed.RESEARCH: "Research something for me",
    OnboardingNeed.AUTOMATION: "Automate a chore for me",
}

# --- copy: one constant per line ------------------------------------------

LINE_1_PREFIX = "So: "
LINE_1_TAIL_WITH_NEEDS = ". That's most of a day. I can take a lot of it."
LINE_1_TAIL_WITHOUT_NEEDS = ". I can take a lot off your plate."
LINE_1_NO_ANSWERS = "So: you're here. I can take a lot off your plate."

LINE_2 = (
    "Start with Gmail. Connect it and I'll get into your inbox tonight, "
    "sort what needs you from what doesn't, and have drafts waiting by morning."
)

LINE_3_TEMPLATE = (
    "And I'm in your {platform} now. Text me from there whenever. "
    "If something needs you, I'll text first."
)

LINE_4_TEMPLATE = "And the {other_need} part, say the word and I'll start on it."

OTHER_NEED_FOLLOW_UP_TEMPLATE = "Help me with {other_need}"
FALLBACK_FOLLOW_UP = "What can you do for me?"

#: Chips are the whole affordance of the seeded turn — more than three reads as
#: a menu rather than a nudge.
MAX_FOLLOW_UPS = 3

#: The integration the Gmail connect card on line 2 points at.
GMAIL_INTEGRATION_ID = "gmail"
GMAIL_CARD_MESSAGE = "To use Gmail features, please connect your account first."

#: Line 2 is always the first move, so the connect card always rides message index 1.
GMAIL_CARD_LINE = 1


class FirstConversation(BaseModel):
    """The statically composed opening conversation.

    ``lines`` are separate bot messages so the web renders them as grouped
    bubbles; ``gmail_card_line`` indexes the one that carries the Gmail connect
    card, and ``follow_ups`` ride the last message.
    """

    lines: list[str]
    follow_ups: list[str]
    gmail_card_line: int


def gmail_connect_tool_data() -> ToolDataEntry:
    """The Gmail connect card, in the shape the agent's own emitter produces.

    Mirrors the ``integration_connection_required`` payload
    ``request_integration_connection`` writes to the stream, normalised the way
    ``normalize_custom_event`` stores it — ``timestamp`` is omitted because the
    seeded turn is not a live stream frame.
    """
    return {
        "tool_name": "integration_connection_required",
        "data": {
            "integration_id": GMAIL_INTEGRATION_ID,
            "expired": False,
            "message": GMAIL_CARD_MESSAGE,
        },
    }


def _profession_fragment(profession: str | None) -> str | None:
    """The user's job as one list item in GAIA's voice, or None to say nothing.

    A typed job that already opens like a sentence ("I run a bakery") stays
    whole; a picked slug becomes the single word from ``PROFESSION_WORDS``.
    Anything else is a bare job title dropped mid-sentence, so its leading
    capital ("Engineer") is lowered — the settings page and the pre-relocation
    onboarding both store free text with arbitrary casing.
    """
    if not profession:
        return None
    cleaned = profession.strip()
    key = cleaned.lower()
    if key in PROFESSION_WORDS:
        return PROFESSION_WORDS[key]
    if key == "other":
        return None
    if key.startswith(_SENTENCE_OPENERS):
        return cleaned.rstrip(".!")
    title = cleaned.split(" ", 1)[1] if key.startswith(_ARTICLES) else cleaned
    return f"{title[0].lower()}{title[1:]}"


def _acknowledgement(preferences: OnboardingPreferences) -> str:
    fragment = _profession_fragment(preferences.profession)
    clauses = [NEED_CLAUSES[need] for need in preferences.needs or []]
    parts = ([fragment] if fragment else []) + clauses

    if not parts:
        return LINE_1_NO_ANSWERS
    tail = LINE_1_TAIL_WITH_NEEDS if clauses else LINE_1_TAIL_WITHOUT_NEEDS
    return f"{LINE_1_PREFIX}{_join(parts)}{tail}"


def _platform_label(connected_platform: str) -> str:
    source = ConversationSource.coerce(connected_platform)
    if source is None:
        return connected_platform.capitalize()
    return PLATFORM_DISPLAY_NAMES.get(source, source.value.capitalize())


def _follow_ups(preferences: OnboardingPreferences) -> list[str]:
    chips: list[str] = []
    if preferences.other_need:
        chips.append(OTHER_NEED_FOLLOW_UP_TEMPLATE.format(other_need=preferences.other_need))
    for need in preferences.needs or []:
        chip = NEED_FOLLOW_UPS.get(need)
        if chip:
            chips.append(chip)
    return chips[:MAX_FOLLOW_UPS] or [FALLBACK_FOLLOW_UP]


def compose_first_conversation(
    preferences: OnboardingPreferences, connected_platform: str | None
) -> FirstConversation:
    """GAIA's opening turn, built from the onboarding answers and any linked bot."""
    lines = [_acknowledgement(preferences), LINE_2]

    if connected_platform:
        lines.append(LINE_3_TEMPLATE.format(platform=_platform_label(connected_platform)))
    if preferences.other_need:
        lines.append(LINE_4_TEMPLATE.format(other_need=preferences.other_need))

    return FirstConversation(
        lines=lines,
        follow_ups=_follow_ups(preferences),
        gmail_card_line=GMAIL_CARD_LINE,
    )


def with_closing_question(
    composed: FirstConversation,
    preferences: OnboardingPreferences,
    question: str,
    chips: list[str],
) -> FirstConversation:
    """The same conversation with a written question as its last turn.

    ``LINE_4_TEMPLATE`` is the static version of exactly this move, so where it
    was composed the question takes its place rather than following it; with no
    "Something else" answer there is no such line and the question is appended.
    Either way the chips answer the question, so they replace the static ones.
    """
    lines = composed.lines[:]
    if preferences.other_need and lines:
        lines[-1] = question
    else:
        lines.append(question)
    return FirstConversation(
        lines=lines,
        follow_ups=chips,
        gmail_card_line=composed.gmail_card_line,
    )
