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
import hashlib
import json
import re
import time

from pydantic import BaseModel, Field

from app.agents.llm.client import (
    LLMInvokeOptions,
    ainvoke_llm,
    background_structured_runnable,
    metered_config,
)
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.constants.cache import (
    FIRST_QUESTION_CACHE_PREFIX,
    FIRST_QUESTION_CACHE_TTL,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.user_models import OnboardingPreferences
from app.services.onboarding.first_message import NEED_PHRASES
from shared.py.wide_events import log

#: The ceiling for the call made AHEAD of time, while the user is still clicking
#: through the wizard. Nobody is waiting on it, so it gets room to succeed.
QUESTION_TIMEOUT_SECONDS = 8.0

#: The ceiling for the call made at completion, when the prewarm missed. The
#: user is watching a spinner here, so this is a last chance rather than a real
#: attempt: past two seconds the static line is the better product.
LIVE_QUESTION_TIMEOUT_SECONDS = 2.0

#: Low but not zero. At 0 the question collapses onto the same two shapes for
#: every persona; above this it starts inventing facts about their week.
QUESTION_TEMPERATURE = 0.4

MIN_CHIPS = 3
MAX_CHIPS = 4
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
them, in their words. All of it is about their WORK week (a "chore" is a \
repeated work task, never housework):

{answers}

Write the LAST thing you say to them in your opening message: ONE question \
asking what to take on first. Rules:
- Name what they actually told you. A founder with the inbox and the calendar \
gets a question about being a founder with the inbox and the calendar.
- Be extremely specific. The question must be unanswerable by anyone else who \
signed up today.
- 25 words maximum. Ends with a question mark. No exclamation marks.
- Never ask how you can help, never ask what you can do, never list features.
- Do not default to "what do we take on first". Ask the question this \
person's week actually raises: what the fight is this month, what they'd hand \
off tonight, which of two named things is worse, what "done" would look like.
- The chips are the answers a real person would tap for THIS question, in \
the same words the question uses. If the question names three options, the \
chips are those three (plus at most one "neither" style escape). Never invent \
a chip the question did not set up. Avoid "Both" and "All of it" unless the \
question is a genuine either-or.
- Then 3 or 4 chips: the answers, each 4 words maximum, no ending punctuation.

Shapes to aim for. They are about OTHER people: vary between them, never \
reuse their details (no supplier thread, no product or hiring, unless THIS \
person said so). 20 words reads better than 25.
question: "Founder with the inbox and the calendar on fire. What's actually \
the fight this month, product, growth, hiring, or just getting your mornings \
back?"
chips: ["Product", "Growth", "Hiring", "My mornings"]
question: "Sales, and follow-ups slip. Which loss would you kill first: the \
deal that went quiet, or the intro you never sent?"
chips: ["The quiet deal", "The intro", "Both, honestly"]
question: "Bakery owner buried in supplier email. If I handled one thread \
tonight, which one?"
chips: ["Orders", "Invoices", "Late deliveries", "Price quotes"]
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


def _stem(word: str) -> str:
    """Crude inflection strip so "emails"/"email" and "chasing"/"chase" match.

    Only for the "did their own words survive" check, where a plural in the
    answer and a singular in the question must not read as a dropped need.
    """
    for suffix in ("ing", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _validate_question(question: str) -> _Rejection | None:
    """Structure only: something to show, and it asks. Style is the prompt's job."""
    if not question.strip():
        return _Rejection("empty_question")
    if not question.rstrip().endswith("?"):
        return _Rejection("not_a_question")
    return None


def _validate_chips(chips: list[str]) -> _Rejection | None:
    """Structure only: enough distinct, non-empty answers to tap."""
    if not (MIN_CHIPS <= len(chips) <= MAX_CHIPS):
        return _Rejection("chip_count")
    if len({chip.strip().lower() for chip in chips}) != len(chips):
        return _Rejection("duplicate_chips")
    if any(not chip.strip() for chip in chips):
        return _Rejection("empty_chip")
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
    content = {_stem(w) for w in _words(phrase) if w not in _STOPWORDS}
    if content and content <= {_stem(w) for w in _words(surface)}:
        return None
    return _Rejection("other_need_dropped")


def validate_draft(
    question: str, chips: list[str], preferences: OnboardingPreferences
) -> _Rejection | None:
    """The whole rule set, in the order a reader would check it. ``None`` passes."""
    return (
        _validate_question(question)
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
            # Live at completion (2s) gets one attempt: a retry plus backoff
            # cannot fit, and a second timeout costs the user the same wait.
            # The prewarm (8s, nobody waiting) may retry once for an empty or
            # malformed draft.
            options=LLMInvokeOptions(
                max_attempts=2 if timeout_seconds >= QUESTION_TIMEOUT_SECONDS else 1,
                timeout=timeout_seconds,
            ),
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


def answers_fingerprint(preferences: OnboardingPreferences) -> str:
    """A stable hash of the three answers the question is written from.

    Part of the cache key rather than a stored field, so changing an answer
    cannot read a question written for the old one: the new answers hash to a
    key nobody has written yet, and the prewarm for them writes that key. No
    explicit invalidation exists because none can be forgotten.
    """
    payload = json.dumps(
        {
            "profession": (preferences.profession or "").strip().lower(),
            "needs": [need.value for need in preferences.needs or []],
            "other_need": (preferences.other_need or "").strip().lower(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def first_question_cache_key(user_id: str, preferences: OnboardingPreferences) -> str:
    return f"{FIRST_QUESTION_CACHE_PREFIX}{user_id}:{answers_fingerprint(preferences)}"


async def prewarm_first_question(
    user_id: str,
    preferences: OnboardingPreferences,
    connected_platform: str | None,
) -> None:
    """Write the question while the user is still in the wizard.

    Fire-and-forget: this runs detached from the request that saved the answers,
    so it owns its own failures and raises nothing. A question that is not ready
    by the time completion is pressed simply is not used.
    """
    try:
        question = await compose_first_question(preferences, connected_platform, user_id=user_id)
        if question is None:
            return
        await redis_cache.set(
            first_question_cache_key(user_id, preferences),
            question,
            ttl=FIRST_QUESTION_CACHE_TTL,
            model=FirstQuestion,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} first question prewarm failed",
            user_id=user_id,
            error=str(e)[:200],
            error_type=type(e).__name__,
        )


async def resolve_first_question(
    user_id: str,
    preferences: OnboardingPreferences,
    connected_platform: str | None,
) -> FirstQuestion | None:
    """The question to close the seeded conversation with, at completion time.

    Prefers whatever :func:`prewarm_first_question` already wrote, because that
    call cost the user nothing. A miss (they answered and completed in the same
    breath, Redis was down, the prewarm lost its race) gets ONE short live
    attempt, and then the static line.
    """
    cached = await redis_cache.get(first_question_cache_key(user_id, preferences), FirstQuestion)
    if cached is not None:
        log.info(
            f"{LogTag.ONBOARDING} first question resolved",
            user_id=user_id,
            outcome="cached",
        )
        return cached

    live = await compose_first_question(
        preferences,
        connected_platform,
        user_id=user_id,
        timeout_seconds=LIVE_QUESTION_TIMEOUT_SECONDS,
    )
    log.info(
        f"{LogTag.ONBOARDING} first question resolved",
        user_id=user_id,
        outcome="live" if live is not None else "fallback",
    )
    return live


async def seeded_chips(user_id: str, preferences: OnboardingPreferences) -> list[str]:
    """The chips the seeded conversation offered this user, for the agent's prompt.

    Read back from the same cache key the seeded turn was built from, so the
    agent meeting "Growth" as a first message knows it is looking at an answer
    to its own question. An expired key returns nothing rather than guessing: a
    wrong list of chips would tell the model a choice was offered that was not.
    """
    try:
        cached = await redis_cache.get(
            first_question_cache_key(user_id, preferences), FirstQuestion
        )
    except Exception as e:
        # A cache outage must not take the prompt down with it; the agent just
        # loses the "these were your chips" hint for this turn.
        log.warning(
            f"{LogTag.ONBOARDING} seeded chips unreadable — prompt goes without them",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return []
    return list(cached.chips) if cached else []
