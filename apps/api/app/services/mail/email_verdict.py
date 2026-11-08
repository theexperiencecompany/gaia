"""The one judgment GAIA makes about an email: JEV's yes/no answers from one call, and the bucket code derives.

The Inbox desk's gate reads it when the email arrives and the desk's own fetch reads it at
the sweep. JEV answers each judgment in desk_buckets.JUDGMENT_QUESTIONS as P(true); the
decision table here turns their bands into a bucket and a skip. Inside quiet hours the shared
urgent question rides along. Each verdict is kept by Gmail message id, so the second reader
never asks again. A JEV failure raises and nothing is kept.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.constants.desk_buckets import (
    EMAIL_VERDICT_JEV_LIMIT,
    EMAIL_VERDICT_JEV_LIMIT_KEY,
    EMAIL_VERDICT_JEV_TIMEOUT_SECONDS,
    EMAIL_VERDICT_PROFILE_MAX_CHARS,
    JUDGMENT_NO_UNDER,
    JUDGMENT_QUESTIONS,
    JUDGMENT_YES_OVER,
    Band,
    DeskBucket,
    Judgment,
)
from app.constants.trigger_gates import TRIGGER_GATE_URGENT_QUESTION_KEY
from app.db.repositories.email_verdicts import email_verdict_repository
from app.memory.context import about_the_user
from app.memory.engine import memory_engine
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.jev_models import JevDecisionsResponse
from app.services.hil.jev_client import post_decisions
from app.services.quiet_hours_urgency import Urgency, read_urgency, urgent_question
from app.utils.concurrency import loop_bound_semaphore
from app.utils.general_utils import clip_text
from shared.py.wide_events import log

# All of these settled no is one answer the desk gate skips on.
_SKIP_JUDGMENTS = (
    Judgment.IS_PERSON,
    Judgment.ASKS_USER,
    Judgment.REPORTS_ISSUE,
    Judgment.OFFICIAL,
)


@dataclass(frozen=True, slots=True)
class ThreadFacts:
    """What code knows about the email's thread, read off Gmail before JEV is asked."""

    user_wrote_in_thread: bool
    latest_from_other: bool

    @property
    def conversation(self) -> bool:
        """The user wrote in the thread and it is now someone else's turn: reply, unasked."""
        return self.user_wrote_in_thread and self.latest_from_other


def band(probability: float) -> Band:
    """Read a P(true) on Typesafe's starting bands."""
    if probability > JUDGMENT_YES_OVER:
        return Band.YES
    if probability < JUDGMENT_NO_UNDER:
        return Band.NO
    return Band.UNSURE


def desk_bucket(answers: Mapping[Judgment, float], *, conversation: bool) -> DeskBucket | None:
    """Return the bucket the decision table gives; None when an unsure answer leaves the desk to judge.

    conversation is reply; a reported issue or an official notice is act; a person asking a
    relevant ask is reply; bulk mail reporting nothing is junk, or fyi when it is relevant;
    once every skip judgment is settled, the rest is fyi, or junk when nobody wrote it and it
    is irrelevant.
    """
    if conversation:
        return DeskBucket.REPLY
    bands = {judgment: band(p) for judgment, p in answers.items()}
    if Band.YES in (bands[Judgment.REPORTS_ISSUE], bands[Judgment.OFFICIAL]):
        return DeskBucket.ACT
    if (
        bands[Judgment.IS_PERSON] is Band.YES
        and bands[Judgment.ASKS_USER] is Band.YES
        and bands[Judgment.RELEVANT] is not Band.NO
    ):
        return DeskBucket.REPLY
    if _bulk_noise(bands):
        return DeskBucket.FYI if bands[Judgment.RELEVANT] is Band.YES else DeskBucket.JUNK
    if any(bands[judgment] is Band.UNSURE for judgment in _SKIP_JUDGMENTS):
        return None
    nobody = bands[Judgment.IS_PERSON] is Band.NO
    return DeskBucket.JUNK if nobody and bands[Judgment.RELEVANT] is Band.NO else DeskBucket.FYI


def _bulk_noise(bands: Mapping[Judgment, Band]) -> bool:
    """Bulk mail that reports no problem, unless a person wrote it about the user's own work."""
    aligned = bands[Judgment.IS_PERSON] is Band.YES and bands[Judgment.RELEVANT] is Band.YES
    return (
        bands[Judgment.BULK] is Band.YES
        and bands[Judgment.REPORTS_ISSUE] is Band.NO
        and not aligned
    )


class EmailVerdict(BaseModel):
    """One email's answers, P(true) per judgment asked, its bucket, and its urgency in quiet hours."""

    model_config = ConfigDict(frozen=True)

    answers: Mapping[Judgment, float]
    bucket: DeskBucket | None
    urgency: Urgency | None = None

    @property
    def skips(self) -> bool:
        """Whether the desk gate skips the email: fyi or junk that is bulk noise or asks nothing."""
        if self.bucket not in (DeskBucket.FYI, DeskBucket.JUNK):
            return False
        bands = {judgment: band(p) for judgment, p in self.answers.items()}
        return _bulk_noise(bands) or all(bands[j] is Band.NO for j in _SKIP_JUDGMENTS)

    @property
    def skip_certainty(self) -> float | None:
        """How sure JEV is that nothing is asked of the user: 1 - the highest skip judgment."""
        if not all(judgment in self.answers for judgment in _SKIP_JUDGMENTS):
            return None
        return 1 - max(self.answers[judgment] for judgment in _SKIP_JUDGMENTS)


def verdict_request(
    email: Mapping[str, object], *, thread: ThreadFacts | None, quiet: bool, profile: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and questions for one email; pure, so the eval sends the same bytes.

    An empty profile and unknown thread facts are left out; inside quiet hours the urgent question
    is asked too.
    """
    state: dict[str, object] = {"user": {"profile": profile}} if profile else {}
    state["email"] = dict(email)
    if thread is not None:
        state["thread"] = {
            "user_wrote_in_thread": thread.user_wrote_in_thread,
            "latest_from_other": thread.latest_from_other,
        }
    questions: dict[str, dict[str, object]] = {
        judgment.value: {
            "type": "noul",
            "instructions": JUDGMENT_QUESTIONS[judgment].instructions,
            "criteria": {
                "true": JUDGMENT_QUESTIONS[judgment].true,
                "false": JUDGMENT_QUESTIONS[judgment].false,
            },
        }
        for judgment in Judgment
    }
    if quiet:
        questions[TRIGGER_GATE_URGENT_QUESTION_KEY] = urgent_question()
    return state, questions


def read_verdict(
    body: JevDecisionsResponse, *, quiet: bool, conversation: bool = False
) -> EmailVerdict:
    """Return the verdict JEV's answers give; raise ValueError for an answer missing or malformed."""
    answers = {judgment: body.noul(judgment.value) for judgment in Judgment}
    return EmailVerdict(
        answers=answers,
        bucket=desk_bucket(answers, conversation=conversation),
        urgency=read_urgency(body) if quiet else None,
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
    email: Mapping[str, object],
    *,
    thread: ThreadFacts | None,
    quiet: bool,
) -> EmailVerdict:
    """Return the email's kept verdict, or ask JEV once and keep it; raise when JEV gives none.

    A conversation is reply, and by day JEV is not asked. A kept verdict without urgency does
    not answer a quiet-hours ask. An email with no message id is asked every time.
    """
    kept = await email_verdict_repository.get(message_id, user_id=user_id) if message_id else None
    if kept is not None and (not quiet or kept.urgency is not None):
        return EmailVerdict(answers=kept.answers, bucket=kept.bucket, urgency=kept.urgency)
    conversation = thread is not None and thread.conversation
    if conversation and not quiet:
        verdict = EmailVerdict(answers={}, bucket=DeskBucket.REPLY)
    else:
        verdict = await _ask(user_id, message_id, email, thread, quiet=quiet)
    if message_id:
        await email_verdict_repository.keep(
            EmailVerdictDocument(
                user_id=user_id,
                message_id=message_id,
                answers=dict(verdict.answers),
                bucket=verdict.bucket,
                urgency=verdict.urgency,
            )
        )
    return verdict


async def _ask(
    user_id: str,
    message_id: str | None,
    email: Mapping[str, object],
    thread: ThreadFacts | None,
    *,
    quiet: bool,
) -> EmailVerdict:
    profile = await user_profile(user_id)
    state, questions = verdict_request(email, thread=thread, quiet=quiet, profile=profile)
    # pragma: no mutate start — any key names one process-wide semaphore.
    limit = loop_bound_semaphore(EMAIL_VERDICT_JEV_LIMIT_KEY, EMAIL_VERDICT_JEV_LIMIT)
    # pragma: no mutate end
    # The budget starts before the semaphore, so a queue of sweep calls cannot stretch it.
    async with asyncio.timeout(EMAIL_VERDICT_JEV_TIMEOUT_SECONDS), limit:
        body = await post_decisions(state, questions)
    conversation = thread is not None and thread.conversation
    verdict = read_verdict(body, quiet=quiet, conversation=conversation)
    log.info(
        "email_verdict.judged",
        message_id=message_id,
        bucket=verdict.bucket.value if verdict.bucket else None,
        bands={judgment.value: band(p).value for judgment, p in verdict.answers.items()},
        quiet=quiet,
    )
    return verdict
