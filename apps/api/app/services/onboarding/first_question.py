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

import hashlib
import json
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
QUESTION_TIMEOUT_SECONDS = 20.0

#: The ceiling for the call made at completion, when the prewarm missed. The
#: user is watching a spinner here, so this is a last chance rather than a real
#: attempt: past two seconds the static line is the better product.
LIVE_QUESTION_TIMEOUT_SECONDS = 2.0

#: Low but not zero. At 0 the question collapses onto the same two shapes for
#: every persona; above this it starts inventing facts about their week.
QUESTION_TEMPERATURE = 0.4

#: The voice section of the comms prompt, read out of the prompt itself so the
#: seeded question and the agent the user talks to next cannot drift apart.
_VOICE_SECTION_START = "## Voice"
_VOICE_SECTION_END = "## Length Modes"


class FirstQuestion(BaseModel):
    """The four starting jobs offered as chips under "What are we starting with?"."""

    chips: list[str]


class _QuestionDraft(BaseModel):
    """The model's output. The schema IS the check: structured output cannot hand
    back the wrong number of chips, so nothing downstream second-guesses the words."""

    chips: list[str] = Field(
        min_length=4, max_length=4, description="Exactly 4 jobs, 2 to 4 words each."
    )


def comms_voice_rules() -> str:
    """The comms agent's own Voice section, verbatim.

    Sliced out of :data:`COMMS_AGENT_PROMPT` rather than restated here: a
    second copy of the voice rules is a second thing to keep in sync, and the
    one that is never read is the one that rots.
    """
    start = COMMS_AGENT_PROMPT.find(_VOICE_SECTION_START)
    end = COMMS_AGENT_PROMPT.find(_VOICE_SECTION_END, start + 1)
    # One membership test rather than two comparisons: `start == -1` on its own
    # is unobservable (when the start marker is missing the slice below is empty
    # anyway), so no test can pin it and a silent edit to it is free.
    if -1 in (start, end):
        return ""
    return COMMS_AGENT_PROMPT[start:end].strip()


QUESTION_PROMPT_TEMPLATE = """\
You are GAIA. You write in this voice:

{voice}

A person finished signing up seconds ago. This is everything you know about \
them, in their words. All of it is about their WORK (a "chore" is a repeated \
work task, never housework):

{answers}

Your opening message ends with "What are we starting with?" and four chips \
under it. Write the four chips: the four jobs THIS person most wants handed \
off, ambitious ones, the things they lie awake over, not chores. You can start \
every one of them today with research, writing, a list you hold, a plan, or a \
job you run on a schedule. Rules:
- 2 to 4 words each. Verb first. No "the". No ending punctuation. No emoji.
- Never the inbox or the calendar routines (sorting mail, drafting replies, \
meeting prep): those are already on offer above the chips.
- Never generic ("Help me", "Get organised", "Plan my day"). Each chip names a \
real outcome in their world.
- If they typed a need in their own words and it is a real job, it is chip one, \
in their words, trimmed to a verb phrase. If it is not a real job, ignore it.
- Four different jobs, no two about the same thing.
- A job is something they would hand to a capable person to DO: it starts with \
a verb that produces a thing (find, write, plan, build, chase, research, \
model, prep). Never a complaint or a wish ("Never miss follow-ups", "Stop \
re-explaining myself"), never a feeling, never "Do my research" or "Write my \
drafts" style filler that names no outcome.
- Write THIS person's four. The examples below show the standard, not the \
words: copying an example's chips for a similar job is a failure.

Examples of the standard. They are about OTHER people: never reuse their \
details or their chips unless THIS person said so.
founder, drowning in email: ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]
sales, follow-ups slip: ["Find leads", "Write outreach", "Prep a demo", "Build my pipeline"]
engineer, same chores daily: ["Design my system", "Plan my sprint", "Write docs", "Ship my side project"]
student, mornings start behind: ["Ace my exam", "Write my essay", "Land an internship", "Plan my semester"]
marketing, typed "content calendar": ["Plan content calendar", "Grow my list", "Write a campaign", "Find influencers"]
bakery owner, typed "chasing suppliers for invoices": ["Chase suppliers", "Find new suppliers", "Plan next month", "Write my newsletter"]
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


async def compose_first_question(
    preferences: OnboardingPreferences,
    connected_platform: str | None,
    *,
    user_id: str | None = None,
    timeout_seconds: float = QUESTION_TIMEOUT_SECONDS,
) -> FirstQuestion | None:
    """The four starting jobs for a brand-new user, or ``None`` for no chips.

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

    log.info(
        f"{LogTag.ONBOARDING} first question composed",
        outcome="llm",
        reason="ok",
        chip_count=len(chips),
        duration_s=round(time.monotonic() - started, 3),
    )
    return FirstQuestion(chips=chips)


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
