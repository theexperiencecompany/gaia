"""Trigger gates: one JEV call about a fired event, made before it costs a run.

Both fan-outs of TriggerHandler.process_event call decide_gate before anything is
claimed, buffered or queued, so a skipped event leaves nothing behind that marks
it handled. An authored gate skips by day only at P(skip label) >= 0.95; the desk
preset reads the email verdict instead and skips fyi and junk. Inside quiet hours
P(urgent) >= 0.80 runs now, then a skip skips, and everything else, every JEV
failure included, waits for the window to end. A crash outside JEV runs the job.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import parseaddr
import time
from typing import Final

import httpx

from app.constants.desk_buckets import DESK_BUCKET_SKIP_REASONS
from app.constants.integrations import EVENT_ACCOUNT_ID_KEY
from app.constants.trigger_gates import (
    AUTHORED_GATE_QUESTION,
    AUTHORED_GATE_RUN_LABEL,
    AUTHORED_GATE_SKIP_MEANING,
    GMAIL_MESSAGE_TRIGGERS,
    QUIET_HOURS_BYPASS_REASONS,
    TRIGGER_GATE_AUTOMATION_MAX_CHARS,
    TRIGGER_GATE_EVENT_LABEL_MAX_CHARS,
    TRIGGER_GATE_EVENT_LABEL_SEPARATOR,
    TRIGGER_GATE_FIELD_MAX_CHARS,
    TRIGGER_GATE_INSTRUCTIONS,
    TRIGGER_GATE_JEV_TIMEOUT_SECONDS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_LABEL,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_UNTITLED_EVENT,
    TRIGGER_GATE_URGENT_CRITERIA,
    TRIGGER_GATE_URGENT_INSTRUCTIONS,
    TRIGGER_GATE_URGENT_PROBABILITY,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    GateOutcome,
    GateOwner,
    GateQuestion,
    GateReason,
)
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.jev_models import JevChoiceAnswer, JevDecisionsResponse
from app.models.trigger_gate_models import (
    AuthoredGate,
    GateSkipRecord,
    QuietHoursBypass,
    QuietHoursHold,
    SystemGate,
    TriggerGate,
)
from app.services.analytics_service import capture
from app.services.feature_flags import is_trigger_gates_enforced
from app.services.hil.jev_client import JevUnconfiguredError, post_decisions
from app.services.latency_metrics import observe_trigger_gate_decision
from app.services.mail.email_verdict import (
    QUIET_BUCKETS,
    EmailVerdict,
    Urgency,
    email_verdict,
    urgency,
)
from app.services.mail.thread_participation import user_wrote_in_thread
from app.services.triggers.condition_matching import resolve_payload_value
from app.services.triggers.gmail_signals import GmailGateView, gmail_gate_view
from app.services.triggers.matchable_fields import get_matchable_trigger
from app.services.user_service import get_profile_timezone, get_quiet_hours
from app.utils.general_utils import clip_text
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.catalog.triggers import TriggerGateDecided
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log

# Why JEV gave no usable answer, first match wins; anything else is an error, so it is alerted on.
_FAILURE_REASONS: tuple[tuple[type[Exception] | tuple[type[Exception], ...], GateReason], ...] = (
    (JevUnconfiguredError, GateReason.JEV_UNCONFIGURED),
    ((TimeoutError, httpx.TimeoutException), GateReason.JEV_TIMEOUT),
    # A body that is not JSON, fails validation, or names a label or probability the gate never offered.
    (ValueError, GateReason.JEV_MALFORMED),
)


def jev_failure_reason(error: Exception) -> GateReason:
    """Name why a JEV call gave no usable answer; anything unforeseen is JEV_ERROR."""
    return next(
        (reason for kinds, reason in _FAILURE_REASONS if isinstance(error, kinds)),
        GateReason.JEV_ERROR,
    )


@dataclass(frozen=True, slots=True)
class GateRun:
    """Run the job now, as if the gate were not there."""


@dataclass(frozen=True, slots=True)
class GateSkip:
    """Do not run the job; event names what was skipped, certainty is JEV's P(skip label)."""

    event: str
    certainty: float


@dataclass(frozen=True, slots=True)
class GateHold:
    """Run the job when the user's quiet hours end; until is that moment on their clock."""

    until: datetime

    @property
    def stamp(self) -> QuietHoursHold:
        return QuietHoursHold()


@dataclass(frozen=True, slots=True)
class GateBypass:
    """Run the job now, inside quiet hours; its run says it interrupts them and why."""

    reason: str

    @property
    def stamp(self) -> QuietHoursBypass:
        return QuietHoursBypass(reason=self.reason)


# What a gate tells its fan-out to do with one fired event.
GateVerdict = GateRun | GateSkip | GateHold | GateBypass

_OUTCOMES: Final[Mapping[type[GateVerdict], GateOutcome]] = {
    GateRun: GateOutcome.RUN,
    GateSkip: GateOutcome.SKIP,
    GateHold: GateOutcome.HOLD,
    GateBypass: GateOutcome.BYPASS,
}
_URGENT_LABELS: Final = frozenset(TRIGGER_GATE_URGENT_CRITERIA)


@dataclass(frozen=True, slots=True)
class GatedJob:
    """The job a gate stands in front of: a workflow or one todo subscription, and what it does."""

    owner: GateOwner
    id: str
    user_id: str
    automation: str
    # Gmail threads the job already follows; a message on one of them is a conversation.
    tracked_threads: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class _GateEvent:
    """The event as JEV reads it, the line a skip names it by, and the thread it continues.

    A conversation runs by day without asking; in quiet hours it is held, never skipped.
    """

    fields: dict[str, object]
    label: str
    continued_thread: str | None = None
    conversation: bool = False
    # The Gmail message id an email's verdict is kept under; None for any other event.
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Decision:
    """Why the gate decided, and what an enforced gate does with the event."""

    reason: GateReason
    verdict: GateVerdict
    choice: str | None = None
    confidence: float | None = None
    skip_probability: float | None = None
    urgency: Urgency | None = None
    latency_ms: int | None = None


def automation_text(title: str, description: str | None) -> str:
    """Name the job a gate guards, as JEV reads it: its title and what it is for."""
    text = f"{title}: {description}" if description else title
    return clip_text(text, TRIGGER_GATE_AUTOMATION_MAX_CHARS)


def _question(gate: AuthoredGate) -> GateQuestion:
    return GateQuestion(
        question=AUTHORED_GATE_QUESTION,
        run_label=AUTHORED_GATE_RUN_LABEL,
        run_meaning=gate.condition,
        skip_label=TRIGGER_GATE_SKIP_LABEL,
        skip_meaning=AUTHORED_GATE_SKIP_MEANING,
    )


def gate_request(
    gate: AuthoredGate, event: Mapping[str, object], automation: str, *, quiet: bool
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and questions for one event; pure, so the eval sends the same bytes.

    Inside quiet hours the urgent question rides next to the unchanged gate question.
    """
    question = _question(gate)
    state: dict[str, object] = {"event": dict(event), "automation": automation}
    questions: dict[str, dict[str, object]] = {
        TRIGGER_GATE_QUESTION_KEY: {
            "type": "choice",
            "instructions": TRIGGER_GATE_INSTRUCTIONS.format(question=question.question),
            "criteria": question.criteria(),
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


def skip_probability(gate: AuthoredGate, answer: JevChoiceAnswer) -> float:
    """Return P(skip label) from JEV's probabilities; raise ValueError when there are none to trust."""
    question = _question(gate)
    probabilities = answer.probabilities
    if not probabilities or not probabilities.keys() <= question.labels:
        raise ValueError(f"gate answer has no usable probabilities: {probabilities!r}")
    return probabilities.get(question.skip_label, 0.0)


def _clip(value: object) -> object | None:
    if isinstance(value, str):
        return clip_text(" ".join(value.split()), TRIGGER_GATE_FIELD_MAX_CHARS)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [clip_text(v, TRIGGER_GATE_FIELD_MAX_CHARS) for v in value]
    return None


def _label(text: str) -> str:
    return clip_text(" ".join(text.split()), TRIGGER_GATE_EVENT_LABEL_MAX_CHARS)


def _gmail_label(view: GmailGateView, trigger_name: str) -> str:
    """Name an email by its sender's name and its subject, as many of them as it has."""
    name, address = parseaddr(view.sender) if view.sender else ("", "")
    parts = [_label(part) for part in (name or address or view.sender, view.subject) if part]
    return TRIGGER_GATE_EVENT_LABEL_SEPARATOR.join(parts) or TRIGGER_GATE_UNTITLED_EVENT.format(
        trigger_name=trigger_name
    )


def _event(trigger_name: str, payload: Mapping[str, object]) -> _GateEvent | None:
    """Return the event JEV reads; None when there is nothing it can read.

    A Gmail message that continues a thread carries that thread; one the signals
    cannot place as new or continued counts as a conversation. Any other trigger
    sends its matchable catalog fields.
    """
    if trigger_name in GMAIL_MESSAGE_TRIGGERS:
        view = gmail_gate_view(payload)
        if view is None:
            return None
        thread = resolve_payload_value(payload, "thread_id") if view.continues_thread else None
        message_id = resolve_payload_value(payload, "message_id")
        return _GateEvent(
            view.as_event(),
            _gmail_label(view, trigger_name),
            continued_thread=thread if isinstance(thread, str) else None,
            conversation=view.continues_thread is None,
            message_id=message_id if isinstance(message_id, str) and message_id else None,
        )
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        return None
    event = {
        name: value
        for name in entry.field_names
        if (value := _clip(resolve_payload_value(payload, name))) is not None
    }
    if not event:
        return None
    title = event.get(entry.title_field) if entry.title_field else None
    label = (
        f'"{_label(title)}"'
        if isinstance(title, str) and title
        else TRIGGER_GATE_UNTITLED_EVENT.format(trigger_name=trigger_name)
    )
    return _GateEvent(event, label)


async def _in_conversation(job: GatedJob, thread_id: str, payload: Mapping[str, object]) -> bool:
    """Whether a continued thread is one the job follows or the user wrote in; unreadable counts.

    A thread Gmail cannot be asked about is treated as a conversation, so a lookup
    failure never reaches a skip.
    """
    if thread_id in job.tracked_threads:
        return True
    message_id = resolve_payload_value(payload, "message_id")
    account_id = payload.get(EVENT_ACCOUNT_ID_KEY)
    try:
        return await user_wrote_in_thread(
            job.user_id,
            thread_id,
            message_id=message_id if isinstance(message_id, str) else None,
            account_id=account_id if isinstance(account_id, str) else None,
        )
    except Exception as e:
        log.warning(
            "trigger_gate.thread_unreadable",
            owner=job.owner.value,
            job_id=job.id,
            error=str(e)[:300],
            error_type=type(e).__name__,
        )
        return True


def _settle(
    gate: AuthoredGate, body: JevDecisionsResponse, event: _GateEvent, *, hold: GateHold | None
) -> _Decision:
    """Read JEV's answers in the settle order; hold is what quiet hours do, None by day."""
    urgent: Urgency | None = None  # pragma: no mutate — only read as truthy; "" equals None
    if hold is not None:
        labels = _URGENT_LABELS
        urgent = urgency(body.choice(TRIGGER_GATE_URGENT_QUESTION_KEY, labels, label="urgent "))
        if urgent.probability >= TRIGGER_GATE_URGENT_PROBABILITY:
            bypass = GateBypass(QUIET_HOURS_BYPASS_REASONS[urgent.choice])
            return _Decision(GateReason.JEV_URGENT, bypass, urgency=urgent)
        if event.conversation:
            return _Decision(GateReason.JEV_CAN_WAIT, hold, urgency=urgent)
    answer = body.choice(TRIGGER_GATE_QUESTION_KEY, _question(gate).labels, label="gate ")
    p_skip = skip_probability(gate, answer)
    if p_skip >= TRIGGER_GATE_SKIP_PROBABILITY:
        skip = GateSkip(event.label, p_skip)
        return _Decision(GateReason.JEV_SKIP, skip, *_answered(answer), p_skip, urgent)
    if hold is not None:
        return _Decision(GateReason.JEV_CAN_WAIT, hold, *_answered(answer), p_skip, urgent)
    return _Decision(GateReason.JEV_RUN, GateRun(), *_answered(answer), p_skip)


def _answered(answer: JevChoiceAnswer) -> tuple[str, float | None]:
    return answer.choice, answer.confidence


def _settle_verdict(
    verdict: EmailVerdict, event: _GateEvent, *, hold: GateHold | None
) -> _Decision:
    """Read the email verdict in the settle order: fyi and junk skip, any other bucket wakes the desk."""
    bucket = verdict.bucket
    choice = bucket.value if bucket else None
    p_skip = verdict.quiet_probability
    urgent = verdict.urgency if hold is not None else None
    if hold is not None:
        if urgent is None:
            raise ValueError("a quiet-hours email verdict carries no urgency")
        if urgent.probability >= TRIGGER_GATE_URGENT_PROBABILITY:
            bypass = GateBypass(QUIET_HOURS_BYPASS_REASONS[urgent.choice])
            return _Decision(GateReason.JEV_URGENT, bypass, choice, None, p_skip, urgent)
        if event.conversation:
            return _Decision(GateReason.JEV_CAN_WAIT, hold, choice, None, p_skip, urgent)
    if bucket is not None and bucket in QUIET_BUCKETS:
        reason = DESK_BUCKET_SKIP_REASONS[bucket]
        skip = GateSkip(TRIGGER_GATE_EVENT_LABEL_SEPARATOR.join((reason, event.label)), p_skip)
        return _Decision(GateReason.JEV_SKIP, skip, choice, None, p_skip, urgent)
    if hold is not None:
        return _Decision(GateReason.JEV_CAN_WAIT, hold, choice, None, p_skip, urgent)
    return _Decision(GateReason.JEV_RUN, GateRun(), choice, None, p_skip)


async def _ask_authored(
    gate: AuthoredGate, event: _GateEvent, automation: str, *, hold: GateHold | None
) -> _Decision:
    state, questions = gate_request(gate, event.fields, automation, quiet=hold is not None)
    async with asyncio.timeout(TRIGGER_GATE_JEV_TIMEOUT_SECONDS):
        body = await post_decisions(state, questions)
    return _settle(gate, body, event, hold=hold)


async def _ask_jev(
    gate: TriggerGate, event: _GateEvent, job: GatedJob, *, hold: GateHold | None
) -> _Decision:
    started = time.perf_counter()
    try:
        if isinstance(gate, SystemGate):
            verdict = await email_verdict(
                job.user_id, event.message_id, event.fields, quiet=hold is not None
            )
            decision = _settle_verdict(verdict, event, hold=hold)
        else:
            decision = await _ask_authored(gate, event, job.automation, hold=hold)
    except Exception as e:
        # The one degradation a gate has: run as if it were not there, or wait for the morning.
        reason = jev_failure_reason(e)
        if reason is not GateReason.JEV_UNCONFIGURED:
            log.warning(
                "trigger_gate.jev_failed",
                reason=reason.value,
                error=str(e)[:300],
                error_type=type(e).__name__,
            )
        decision = _Decision(reason, hold or GateRun())
    return replace(decision, latency_ms=int((time.perf_counter() - started) * 1000))


def _record(
    gate: TriggerGate,
    job: GatedJob,
    trigger_name: str,
    decision: _Decision,
    outcome: GateOutcome,
    *,
    enforced: bool,
) -> None:
    """Count the decision, write it to the wide event under the job's id, and send it to PostHog."""
    observe_trigger_gate_decision(
        owner=job.owner.value, outcome=outcome.value, reason=decision.reason.value
    )
    urgent = decision.urgency
    log.set(
        trigger_gate={
            job.id: {
                "owner": job.owner.value,
                "kind": gate.kind.value,
                "outcome": outcome.value,
                "reason": decision.reason.value,
                "enforced": enforced,
                "skip_probability": decision.skip_probability,
                "choice": decision.choice,
                "confidence": decision.confidence,
                "urgent_probability": urgent.probability if urgent else None,
                "urgent_choice": urgent.choice.value if urgent else None,
                "latency_ms": decision.latency_ms,
            }
        }
    )
    capture(
        UserId(job.user_id),
        TriggerGateDecided(
            owner_type=job.owner.value,
            trigger_name=trigger_name,
            gate_kind=gate.kind.value,
            author=gate.author.value if isinstance(gate, AuthoredGate) else None,
            outcome=outcome.value,
            reason=decision.reason.value,
            urgent_choice=(
                urgent.choice.value if urgent and decision.reason is GateReason.JEV_URGENT else None
            ),
            enforced=enforced,
            latency_ms=decision.latency_ms,
        ),
    )


async def _hold_on_users_clock(user_id: str) -> GateHold | None:
    """Return a hold until the user's quiet hours end when their own clock is inside them now."""
    local_now = datetime.now((await get_profile_timezone(user_id)).tzinfo)
    hours = await get_quiet_hours(user_id)
    return GateHold(hours.end_after(local_now)) if hours.contains(local_now) else None


async def quiet_hours_hold(gate: TriggerGate | None, user_id: str) -> GateHold | None:
    """Return the hold a run of the job behind gate waits on if it would start now, or None.

    An enforced gate starts no run inside the user's quiet hours; an urgent run is
    decided per event, so the caller says when one is carried.
    """
    if gate is None or not gate.enabled or not gate.enforced:
        return None
    if (hold := await _hold_on_users_clock(user_id)) is None:
        return None
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        return hold if await is_trigger_gates_enforced(user_id) else None


async def decide_gate(
    gate: TriggerGate | None, job: GatedJob, *, trigger_name: str, payload: Mapping[str, object]
) -> GateVerdict:
    """Decide what one fired event does to its job's run, on the user's own clock; a crash runs it.

    Counts the decision, writes it to the wide event under the job's id and sends
    trigger:gate_decided. A gate that is absent or turned off is not asked.
    """
    if gate is None or not gate.enabled:
        return GateRun()
    try:
        return await _decide(gate, job, trigger_name, payload)
    except Exception:
        # A gate that cannot decide runs its job, and never costs a fan-out its other jobs.
        log.error("trigger_gate.failed", owner=job.owner.value, job_id=job.id, exc_info=True)
        return GateRun()


async def _decide(
    gate: TriggerGate, job: GatedJob, trigger_name: str, payload: Mapping[str, object]
) -> GateVerdict:
    hold = await _hold_on_users_clock(job.user_id)
    event = _event(trigger_name, payload)
    if (
        event is not None
        and event.continued_thread is not None
        and await _in_conversation(job, event.continued_thread, payload)
    ):
        event = replace(event, conversation=True)
    if event is None or (event.conversation and hold is None):
        decision = _Decision(GateReason.FREE_RUN, hold or GateRun())
    else:
        decision = await _ask_jev(gate, event, job, hold=hold)
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        enforced = gate.enforced and await is_trigger_gates_enforced(job.user_id)
        verdict = decision.verdict if enforced else GateRun()
        _record(gate, job, trigger_name, decision, _OUTCOMES[type(verdict)], enforced=enforced)
    if isinstance(verdict, GateSkip):
        await _remember_skip(job, verdict)
    return verdict


async def _remember_skip(job: GatedJob, skip: GateSkip) -> None:
    """Keep the skip on the job's gate for its panel; a failed write costs the entry, not the skip."""
    record = GateSkipRecord(event=skip.event, at=datetime.now(UTC), certainty=skip.certainty)
    try:
        if job.owner is GateOwner.WORKFLOW:
            await workflow_repository.remember_gate_skip(job.id, job.user_id, record)
        else:
            await todo_repository.remember_subscription_gate_skip(
                user_id=job.user_id, subscription_id=job.id, skip=record
            )
    except Exception as e:
        # Re-raising would reach decide_gate's crash path and run the job the gate just skipped.
        log.error(
            "trigger_gate.skip_unrecorded",
            owner=job.owner.value,
            job_id=job.id,
            user_id=job.user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
