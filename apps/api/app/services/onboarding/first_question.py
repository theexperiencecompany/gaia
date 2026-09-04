"""The one LLM-composed line of GAIA's opening conversation.

:mod:`first_conversation` is deterministic on purpose, and stays that way: it is
the thing that always ships. This module writes only the LAST turn of it — one
extremely specific question about what to tackle first, inferred from the three
onboarding answers — and every failure mode returns ``None`` so the static line
composed next door is what the user gets instead.

The rules are enforced in code rather than trusted to the prompt. A model that
answers "How can I help you today?" has produced something worse than the static
copy, so a miss is a fallback, not a warning to ship anyway.
"""

from dataclasses import dataclass
import re
import string
import time

from pydantic import BaseModel, Field

from app.agents.llm.client import (
    LLMInvokeOptions,
    ainvoke_llm,
    background_structured_runnable,
    metered_config,
)
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.constants.log_tags import LogTag
from app.models.user_models import OnboardingPreferences
from app.services.onboarding.first_conversation import PROFESSION_WORDS
from app.services.onboarding.first_message import NEED_PHRASES
from shared.py.wide_events import log

#: One call, on a hard latency budget: this sits inside onboarding completion,
#: so the user waits for it. Anything slower than this is worth less than the
#: static line it would replace.
QUESTION_TIMEOUT_SECONDS = 4.0

#: Low but not zero. At 0 the question collapses onto the same two shapes for
#: every persona; above this it starts inventing facts about their week.
QUESTION_TEMPERATURE = 0.4

MAX_QUESTION_WORDS = 25
MIN_CHIPS = 3
MAX_CHIPS = 4
MAX_CHIP_WORDS = 4

#: Substrings that mean the model wrote assistant boilerplate instead of a
#: question about this user. Matched case-insensitively on the whole question.
BANNED_QUESTION_SUBSTRINGS: tuple[str, ...] = (
    "how can i help",
    "what can i do",
    "assist",
)

#: A question naming three or more of GAIA's surfaces is a feature list wearing
#: a question mark. Two is a comparison ("the inbox or the calendar"), which is
#: exactly the shape we want.
FEATURE_NOUNS: tuple[str, ...] = (
    "inbox",
    "email",
    "calendar",
    "meeting",
    "todo",
    "reminder",
    "workflow",
    "automation",
    "memory",
    "brief",
    "research",
)
MAX_FEATURE_NOUNS = 2

#: Words carrying no identity, so they never count as "something they said".
_STOPWORDS = frozenset(
    {
        "a",
        "am",
        "an",
        "and",
        "are",
        "at",
        "every",
        "for",
        "i",
        "in",
        "is",
        "it",
        "keep",
        "me",
        "my",
        "of",
        "on",
        "single",
        "the",
        "they",
        "to",
        "want",
        "wake",
        "with",
        "you",
        "your",
    }
)

_WORD_RE = re.compile(r"[a-z0-9']+")

#: The voice section of the comms prompt, read out of the prompt itself so the
#: seeded question and the agent the user talks to next cannot drift apart.
_VOICE_SECTION_START = "## Voice"
_VOICE_SECTION_END = "## Length Modes"


class FirstQuestion(BaseModel):
    """A validated question plus the chips that answer it."""

    question: str
    chips: list[str]


class _QuestionDraft(BaseModel):
    """The raw model output, before any of the rules are applied."""

    question: str = Field(description="One question, 25 words max, ending in a question mark.")
    chips: list[str] = Field(description="3 or 4 answers to it, 4 words max each.")


@dataclass(frozen=True)
class _Rejection:
    """Why a draft is not shippable. ``reason`` is the wide-event value."""

    reason: str


def comms_voice_rules() -> str:
    """The comms agent's own Voice section, verbatim.

    Sliced out of :data:`COMMS_AGENT_PROMPT` rather than restated here: a
    second copy of the voice rules is a second thing to keep in sync, and the
    one that is never read is the one that rots.
    """
    start = COMMS_AGENT_PROMPT.find(_VOICE_SECTION_START)
    end = COMMS_AGENT_PROMPT.find(_VOICE_SECTION_END, start + 1)
    if start == -1 or end == -1:
        return ""
    return COMMS_AGENT_PROMPT[start:end].strip()


QUESTION_PROMPT_TEMPLATE = """\
You are GAIA. You write in this voice:

{voice}

A person finished signing up seconds ago. This is everything you know about \
them, in their words:

{answers}

Write the LAST thing you say to them in your opening message: ONE question \
asking what to take on first. Rules:
- Name what they actually told you. A founder with the inbox and the calendar \
gets a question about being a founder with the inbox and the calendar.
- Be extremely specific. The question must be unanswerable by anyone else who \
signed up today.
- 25 words maximum. Ends with a question mark. No exclamation marks.
- Never ask how you can help, never ask what you can do, never list features.
- Then 3 or 4 chips: the answers, each 4 words maximum, no ending punctuation.

Shape to aim for:
question: "Founder with the inbox and the calendar on fire. What's actually \
the fight this month, product, growth, hiring, or just getting your mornings \
back?"
chips: ["Product", "Growth", "Hiring", "My mornings"]
"""


def _answers_block(preferences: OnboardingPreferences, connected_platform: str | None) -> str:
    """The onboarding answers as the model reads them, one per line."""
    lines: list[str] = []
    profession = (preferences.profession or "").strip()
    if profession and profession.lower() != "other":
        lines.append(f"- Their job, as they answered it: {profession}")
    for need in preferences.needs or []:
        lines.append(f"- {NEED_PHRASES[need]}")
    if preferences.other_need:
        lines.append(f'- In their own words: "{preferences.other_need}"')
    if connected_platform:
        lines.append(f"- They already text you on {connected_platform}")
    return "\n".join(lines) or "- Nothing. They answered nothing."


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _their_words(preferences: OnboardingPreferences) -> set[str]:
    """Every content word the user gave us, in any of the three answers.

    A question "mentions something they said" when it reuses one of these. The
    need's own slug is in here beside its phrase: "inbox" is the word on the
    chip they clicked, even though the phrase behind it says "email".
    """
    source: list[str] = []
    profession = (preferences.profession or "").strip()
    if profession and profession.lower() != "other":
        source.append(profession)
        source.append(PROFESSION_WORDS.get(profession.lower(), ""))
    for need in preferences.needs or []:
        source.append(need.value)
        source.append(NEED_PHRASES[need])
    if preferences.other_need:
        source.append(preferences.other_need)
    return {word for text in source for word in _words(text)} - _STOPWORDS


def _validate_question(question: str, preferences: OnboardingPreferences) -> _Rejection | None:
    if not question.strip():
        return _Rejection("empty_question")
    if not question.rstrip().endswith("?"):
        return _Rejection("not_a_question")
    if "!" in question:
        return _Rejection("exclamation")
    if len(question.split()) > MAX_QUESTION_WORDS:
        return _Rejection("too_long")
    lowered = question.lower()
    if any(banned in lowered for banned in BANNED_QUESTION_SUBSTRINGS):
        return _Rejection("banned_phrase")
    if sum(noun in lowered for noun in FEATURE_NOUNS) > MAX_FEATURE_NOUNS:
        return _Rejection("feature_list")
    if not (set(_words(question)) & _their_words(preferences)):
        return _Rejection("nothing_they_said")
    return None


def _validate_chips(chips: list[str]) -> _Rejection | None:
    if not (MIN_CHIPS <= len(chips) <= MAX_CHIPS):
        return _Rejection("chip_count")
    if len({chip.strip().lower() for chip in chips}) != len(chips):
        return _Rejection("duplicate_chips")
    for chip in chips:
        stripped = chip.strip()
        if not stripped:
            return _Rejection("empty_chip")
        if len(stripped.split()) > MAX_CHIP_WORDS:
            return _Rejection("chip_too_long")
        if stripped[-1] in string.punctuation:
            return _Rejection("chip_punctuation")
    return None


def _validate_other_need(
    question: str, chips: list[str], other_need: str | None
) -> _Rejection | None:
    """The thing they typed by hand has to survive into what they are shown.

    They wrote it because no chip covered it; dropping it is the one failure
    that reads as not having been listened to.
    """
    if not other_need:
        return None
    surface = " ".join([question, *chips]).lower()
    phrase = other_need.strip().lower()
    if phrase in surface:
        return None
    content = set(_words(phrase)) - _STOPWORDS
    if content and content <= set(_words(surface)):
        return None
    return _Rejection("other_need_dropped")


def validate_draft(
    question: str, chips: list[str], preferences: OnboardingPreferences
) -> _Rejection | None:
    """The whole rule set, in the order a reader would check it. ``None`` passes."""
    return (
        _validate_question(question, preferences)
        or _validate_chips(chips)
        or _validate_other_need(question, chips, preferences.other_need)
    )


async def compose_first_question(
    preferences: OnboardingPreferences,
    connected_platform: str | None,
    *,
    user_id: str | None = None,
    timeout_seconds: float = QUESTION_TIMEOUT_SECONDS,
) -> FirstQuestion | None:
    """GAIA's closing question for a brand-new user, or ``None`` to use the static line.

    One structured call on the deployment's own cheap lane, capped at
    :data:`QUESTION_TIMEOUT_SECONDS` with no retry, because the caller is a user
    waiting on a page. Every exception, timeout and rule miss returns ``None``.

    ``timeout_seconds`` exists for the persona eval script, which reads the copy
    on whatever lane a developer has configured and must not report a slow local
    endpoint as a copy problem. Nothing in the product passes it.
    """
    started = time.monotonic()
    config = metered_config(user_id) if user_id else None
    prompt = QUESTION_PROMPT_TEMPLATE.format(
        voice=comms_voice_rules(),
        answers=_answers_block(preferences, connected_platform),
    )

    try:
        draft: _QuestionDraft = await ainvoke_llm(
            background_structured_runnable(
                _QuestionDraft, temperature=QUESTION_TEMPERATURE, config=config
            ),
            prompt,
            label="onboarding_first_question",
            config=config,
            # One attempt: retries plus their backoff cannot fit under a 4
            # second ceiling, and a second attempt that times out costs the
            # user the same wait a first one succeeding would have.
            options=LLMInvokeOptions(max_attempts=1, timeout=timeout_seconds),
        )
    except Exception as e:
        # Deliberately everything (LLMNotConfiguredError, TimeoutError, provider
        # errors, schema parse failures): not one of them is a reason to leave
        # the user without an opening conversation.
        log.warning(
            f"{LogTag.ONBOARDING} first question fell back",
            outcome="fallback",
            reason=type(e).__name__,
            duration_s=round(time.monotonic() - started, 3),
        )
        return None

    chips = [chip.strip() for chip in draft.chips]
    rejection = validate_draft(draft.question.strip(), chips, preferences)
    if rejection is not None:
        log.warning(
            f"{LogTag.ONBOARDING} first question fell back",
            outcome="fallback",
            reason=rejection.reason,
            duration_s=round(time.monotonic() - started, 3),
        )
        return None

    log.info(
        f"{LogTag.ONBOARDING} first question composed",
        outcome="llm",
        reason="ok",
        chip_count=len(chips),
        duration_s=round(time.monotonic() - started, 3),
    )
    return FirstQuestion(question=draft.question.strip(), chips=chips)
