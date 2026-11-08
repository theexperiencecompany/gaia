"""The one judgment GAIA makes about an email, from one JEV call: its desk bucket, and inside quiet hours its urgency.

The Inbox desk's gate reads it when the email arrives and the desk's own fetch reads it at
the sweep. JEV judges the email by its value to this user, so memory's About-the-user note
rides along. Each answer is kept by Gmail message id, so the second reader never asks JEV
again. Only a quiet-hours arrival needs urgency, so only it asks the urgent question too.
A JEV failure raises and nothing is kept: each caller degrades its own way.
"""

import asyncio
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.constants.desk_buckets import (
    DESK_AUTOMATION,
    DESK_BUCKET_CRITERIA,
    DESK_BUCKET_INSTRUCTIONS,
    DESK_BUCKET_JUNK_PROBABILITY,
    DESK_BUCKET_QUESTION_KEY,
    EMAIL_VERDICT_JEV_LIMIT,
    EMAIL_VERDICT_JEV_LIMIT_KEY,
    EMAIL_VERDICT_JEV_TIMEOUT_SECONDS,
    EMAIL_VERDICT_KEY_PREFIX,
    EMAIL_VERDICT_PROFILE_MAX_CHARS,
    EMAIL_VERDICT_TTL_SECONDS,
    DeskBucket,
)
from app.constants.trigger_gates import (
    QUIET_HOURS_BYPASS_REASONS,
    TRIGGER_GATE_URGENT_CRITERIA,
    TRIGGER_GATE_URGENT_INSTRUCTIONS,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    UrgentChoice,
)
from app.db.redis import redis_cache
from app.memory.context import about_the_user
from app.memory.engine import memory_engine
from app.models.jev_models import JevChoiceAnswer, JevDecisionsResponse
from app.services.hil.jev_client import post_decisions
from app.utils.concurrency import loop_bound_semaphore
from app.utils.general_utils import clip_text
from shared.py.wide_events import log

_BUCKET_LABELS = frozenset(DeskBucket)
_URGENT_LABELS = frozenset(TRIGGER_GATE_URGENT_CRITERIA)
# Buckets that ask nothing of the user; the desk gate skips on their summed probability.
QUIET_BUCKETS = frozenset({DeskBucket.FYI, DeskBucket.JUNK})


class Urgency(BaseModel):
    """How likely an email is worth waking the user for, and the urgent choice JEV leans to."""

    model_config = ConfigDict(frozen=True)

    probability: float
    choice: UrgentChoice


class EmailVerdict(BaseModel):
    """One email's bucket, None for a junk under the line the desk judges itself, and its urgency.

    urgency is None on a verdict asked outside quiet hours.
    """

    model_config = ConfigDict(frozen=True)

    bucket: DeskBucket | None
    # P(fyi) + P(junk): how sure JEV is that nothing is asked of the user.
    quiet_probability: float
    urgency: Urgency | None


def urgency(answer: JevChoiceAnswer) -> Urgency:
    """Return P(urgent) as 1 - P(can_wait); raise ValueError without a P(can_wait) to trust.

    A missing can_wait would read as certain urgency, so it is malformed, never a wake.
    """
    probabilities = answer.probabilities
    if (
        not probabilities
        or not probabilities.keys() <= _URGENT_LABELS
        or UrgentChoice.CAN_WAIT not in probabilities
    ):
        raise ValueError(f"urgent answer has no usable probabilities: {probabilities!r}")
    leaning = max(QUIET_HOURS_BYPASS_REASONS, key=lambda choice: probabilities.get(choice, 0.0))
    return Urgency(probability=1 - probabilities[UrgentChoice.CAN_WAIT], choice=leaning)


def verdict_request(
    event: Mapping[str, object], *, quiet: bool, profile: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and questions for one email; pure, so the eval sends the same bytes.

    An empty profile is left out. Inside quiet hours the urgent question rides next to the
    unchanged bucket question.
    """
    state: dict[str, object] = {"user": profile} if profile else {}
    state |= {"event": dict(event), "automation": DESK_AUTOMATION}
    questions: dict[str, dict[str, object]] = {
        DESK_BUCKET_QUESTION_KEY: {
            "type": "choice",
            "instructions": DESK_BUCKET_INSTRUCTIONS,
            "criteria": {bucket.value: text for bucket, text in DESK_BUCKET_CRITERIA.items()},
        }
    }
    if quiet:
        questions[TRIGGER_GATE_URGENT_QUESTION_KEY] = {
            "type": "choice",
            "instructions": TRIGGER_GATE_URGENT_INSTRUCTIONS,
            "criteria": {
                choice.value: text for choice, text in TRIGGER_GATE_URGENT_CRITERIA.items()
            },
        }
    return state, questions


def read_verdict(body: JevDecisionsResponse, *, quiet: bool) -> EmailVerdict:
    """Return the verdict JEV gave; raise ValueError for a choice never offered or no probabilities."""
    answer = body.choice(DESK_BUCKET_QUESTION_KEY, _BUCKET_LABELS, label="bucket ")
    probabilities = answer.probabilities
    if not probabilities or not probabilities.keys() <= _BUCKET_LABELS:
        raise ValueError(f"bucket answer has no usable probabilities: {probabilities!r}")
    bucket = DeskBucket(answer.choice)
    if bucket is DeskBucket.JUNK and probabilities.get(bucket, 0.0) < DESK_BUCKET_JUNK_PROBABILITY:
        bucket = None
    urgent = (
        urgency(body.choice(TRIGGER_GATE_URGENT_QUESTION_KEY, _URGENT_LABELS, label="urgent "))
        if quiet
        else None
    )
    return EmailVerdict(
        bucket=bucket,
        quiet_probability=sum(probabilities.get(b, 0.0) for b in QUIET_BUCKETS),
        urgency=urgent,
    )


async def user_profile(user_id: str) -> str:
    """Return memory's note on who the user is, clipped; "" when there is none or it cannot be read."""
    try:
        core = await memory_engine.get_core_context(user_id)
    except Exception as e:
        # The verdict is still worth asking without it: JEV then judges the email alone.
        log.warning(
            "email_verdict.profile_unreadable", error=str(e)[:300], error_type=type(e).__name__
        )
        return ""
    profile = about_the_user(core)
    return clip_text(profile, EMAIL_VERDICT_PROFILE_MAX_CHARS) if profile else ""


async def email_verdict(
    user_id: str,
    message_id: str | None,
    event: Mapping[str, object],
    *,
    quiet: bool,
    conversation: bool,
) -> EmailVerdict:
    """Return the email's kept verdict, or ask JEV once and keep it; raise when JEV gives none.

    A conversation (a thread the user wrote in, now someone else's turn) is reply whatever
    JEV says, and by day JEV is not asked. A kept verdict without urgency does not answer a
    quiet-hours ask. An email with no message id is asked every time.
    """
    key = f"{EMAIL_VERDICT_KEY_PREFIX}:{user_id}:{message_id}" if message_id else None
    kept = await redis_cache.get(key, EmailVerdict) if key is not None else None
    if kept is not None and (not quiet or kept.urgency is not None):
        return kept
    if conversation and not quiet:
        verdict = EmailVerdict(bucket=DeskBucket.REPLY, quiet_probability=0.0, urgency=None)
    else:
        verdict = await _ask(user_id, message_id, event, quiet=quiet)
        if conversation:
            verdict = verdict.model_copy(update={"bucket": DeskBucket.REPLY})
    if key is not None:
        await redis_cache.set(key, verdict, ttl=EMAIL_VERDICT_TTL_SECONDS, model=EmailVerdict)
    return verdict


async def _ask(
    user_id: str, message_id: str | None, event: Mapping[str, object], *, quiet: bool
) -> EmailVerdict:
    profile = await user_profile(user_id)
    state, questions = verdict_request(event, quiet=quiet, profile=profile)
    # pragma: no mutate start — any key names one process-wide semaphore.
    limit = loop_bound_semaphore(EMAIL_VERDICT_JEV_LIMIT_KEY, EMAIL_VERDICT_JEV_LIMIT)
    # pragma: no mutate end
    async with limit, asyncio.timeout(EMAIL_VERDICT_JEV_TIMEOUT_SECONDS):
        body = await post_decisions(state, questions)
    verdict = read_verdict(body, quiet=quiet)
    log.info(
        "email_verdict.judged",
        message_id=message_id,
        bucket=verdict.bucket.value if verdict.bucket else None,
        quiet=quiet,
    )
    return verdict
