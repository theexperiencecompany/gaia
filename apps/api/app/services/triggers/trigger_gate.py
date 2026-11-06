"""Trigger gates: one JEV question about a fired event, asked three times before it costs a run.

Both fan-outs of TriggerHandler.process_event call decide_gate before anything is
claimed, buffered or queued, so a skipped event leaves nothing behind that marks
it handled. By day only P(skip label) >= 0.95 on every sample skips, and every
other answer or failure runs. Inside the user's quiet hours the same call also
asks whether the event is worth waking them for: a median P(urgent) >= 0.80 runs
now, then a confident skip skips, and everything else, every JEV failure
included, waits for 08:00. A gate that crashes outside its JEV call runs the job
now, day or night.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
import time
from typing import Final

import httpx

from app.constants.integrations import EVENT_ACCOUNT_ID_KEY
from app.constants.trigger_gates import (
    AUTHORED_GATE_QUESTION,
    AUTHORED_GATE_RUN_LABEL,
    AUTHORED_GATE_SKIP_MEANING,
    ENFORCED_GATE_KINDS,
    GMAIL_MESSAGE_TRIGGERS,
    QUIET_HOURS_BYPASS_REASONS,
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_AUTOMATION_MAX_CHARS,
    TRIGGER_GATE_EVENT_LABEL_MAX_CHARS,
    TRIGGER_GATE_FIELD_MAX_CHARS,
    TRIGGER_GATE_INSTRUCTIONS,
    TRIGGER_GATE_JEV_SAMPLES,
    TRIGGER_GATE_JEV_TIMEOUT_SECONDS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_LABEL,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_SKIPPED_SUMMARY,
    TRIGGER_GATE_UNTITLED_EVENT,
    TRIGGER_GATE_URGENT_CRITERIA,
    TRIGGER_GATE_URGENT_INSTRUCTIONS,
    TRIGGER_GATE_URGENT_PROBABILITY,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    GateOutcome,
    GateOwner,
    GateQuestion,
    GateReason,
    UrgentChoice,
)
from app.models.jev_models import JevChoiceAnswer, JevDecisionsResponse
from app.models.trigger_gate_models import (
    AuthoredGate,
    QuietHoursBypass,
    QuietHoursHold,
    SystemGate,
    TriggerGate,
)
from app.services.analytics_service import capture
from app.services.feature_flags import is_trigger_gates_enforced
from app.services.hil.jev_client import JevUnconfiguredError, post_decisions
from app.services.latency_metrics import observe_trigger_gate_decision
from app.services.mail.thread_participation import user_wrote_in_thread
from app.services.triggers.condition_matching import resolve_payload_value
from app.services.triggers.gmail_signals import GmailGateView, gmail_gate_view
from app.services.triggers.matchable_fields import get_matchable_trigger
from app.services.user_service import get_profile_timezone
from app.utils.general_utils import clip_text
from app.utils.quiet_hours import after_quiet_hours, in_quiet_hours
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


@dataclass(frozen=True, slots=True)
class GateRun:
    """Run the job now, as if the gate were not there."""


@dataclass(frozen=True, slots=True)
class GateSkip:
    """Do not run the job; summary is the line its run history shows.

    event names what was skipped; certainty is JEV's P(skip label).
    """

    event: str
    condition: str
    certainty: float

    @property
    def summary(self) -> str:
        return TRIGGER_GATE_SKIPPED_SUMMARY.format(
            event=self.event, condition=self.condition, certainty=self.certainty
        )


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
class Urgency:
    """How likely an event is worth waking the user for, and the urgent choice JEV leans to."""

    probability: float
    choice: UrgentChoice


@dataclass(frozen=True, slots=True)
class _GateEvent:
    """The event as JEV reads it, the line a skip names it by, and the thread it continues.

    A conversation runs by day without asking; in quiet hours it is held, never skipped.
    """

    fields: dict[str, object]
    label: str
    continued_thread: str | None = None
    conversation: bool = False


@dataclass(frozen=True, slots=True)
class _Decision:
    """Why the gate decided, and what an enforced gate does with the event."""

    reason: GateReason
    verdict: GateVerdict
    answer: JevChoiceAnswer | None = None
    skip_probability: float | None = None
    urgency: Urgency | None = None
    latency_ms: int | None = None


def automation_text(title: str, description: str | None) -> str:
    """Name the job a gate guards, as JEV reads it: its title and what it is for."""
    text = f"{title}: {description}" if description else title
    return clip_text(text, TRIGGER_GATE_AUTOMATION_MAX_CHARS)


def _question(gate: TriggerGate) -> GateQuestion:
    if isinstance(gate, SystemGate):
        return SYSTEM_GATE_PRESETS[gate.preset].question
    return GateQuestion(
        question=AUTHORED_GATE_QUESTION,
        run_label=AUTHORED_GATE_RUN_LABEL,
        run_meaning=gate.condition,
        skip_label=TRIGGER_GATE_SKIP_LABEL,
        skip_meaning=AUTHORED_GATE_SKIP_MEANING,
    )


def gate_request(
    gate: TriggerGate, event: Mapping[str, object], automation: str, *, quiet: bool
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and questions for one event; pure, so the eval sends the same bytes.

    A preset sends its own job text; an authored gate sends the owner's automation.
    Inside quiet hours the urgent question rides next to the unchanged gate question.
    """
    question = _question(gate)
    job = (
        SYSTEM_GATE_PRESETS[gate.preset].automation if isinstance(gate, SystemGate) else automation
    )
    state: dict[str, object] = {"event": dict(event), "automation": job}
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


def skip_probability(gate: TriggerGate, answer: JevChoiceAnswer) -> float:
    """Return P(skip label) from JEV's probabilities; raise ValueError when there are none to trust."""
    question = _question(gate)
    probabilities = answer.probabilities
    if not probabilities or not probabilities.keys() <= question.labels:
        raise ValueError(f"gate answer has no usable probabilities: {probabilities!r}")
    return probabilities.get(question.skip_label, 0.0)


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
    return Urgency(1 - probabilities[UrgentChoice.CAN_WAIT], leaning)


def consensus_skip(
    gate: TriggerGate, answers: Sequence[JevChoiceAnswer]
) -> tuple[JevChoiceAnswer, float]:
    """Return the least sure answer and its P(skip label): a skip needs every sample past the line."""
    return min(((a, skip_probability(gate, a)) for a in answers), key=lambda pair: pair[1])


def consensus_urgency(answers: Sequence[JevChoiceAnswer]) -> Urgency:
    """Return the median sample's urgency, so the user is woken only when most samples would."""
    ranked = sorted((urgency(a) for a in answers), key=lambda u: u.probability)
    return ranked[len(ranked) // 2]


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
    """Name an email by its sender and subject, as many of them as it has."""
    parts = [_label(view.sender)] if view.sender else []
    if view.subject:
        parts.append(f'"{_label(view.subject)}"')
    return ", ".join(parts) or TRIGGER_GATE_UNTITLED_EVENT.format(trigger_name=trigger_name)


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
        return _GateEvent(
            view.as_event(),
            _gmail_label(view, trigger_name),
            continued_thread=thread if isinstance(thread, str) else None,
            conversation=view.continues_thread is None,
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
    gate: TriggerGate,
    bodies: Sequence[JevDecisionsResponse],
    event: _GateEvent,
    *,
    hold: GateHold | None,
) -> _Decision:
    """Read JEV's sampled answers in the settle order; hold is what quiet hours do, None by day."""
    urgent: Urgency | None = None  # pragma: no mutate — only read as truthy; "" equals None
    if hold is not None:
        urgent = consensus_urgency(
            [
                b.choice(TRIGGER_GATE_URGENT_QUESTION_KEY, _URGENT_LABELS, label="urgent ")
                for b in bodies
            ]
        )
        if urgent.probability >= TRIGGER_GATE_URGENT_PROBABILITY:
            bypass = GateBypass(QUIET_HOURS_BYPASS_REASONS[urgent.choice])
            return _Decision(GateReason.JEV_URGENT, bypass, urgency=urgent)
        if event.conversation:
            return _Decision(GateReason.JEV_CAN_WAIT, hold, urgency=urgent)
    labels = _question(gate).labels
    answer, p_skip = consensus_skip(
        gate, [b.choice(TRIGGER_GATE_QUESTION_KEY, labels, label="gate ") for b in bodies]
    )
    if p_skip >= TRIGGER_GATE_SKIP_PROBABILITY:
        skip = GateSkip(event.label, gate.display_condition, p_skip)
        return _Decision(GateReason.JEV_SKIP, skip, answer, p_skip, urgent)
    if hold is not None:
        return _Decision(GateReason.JEV_CAN_WAIT, hold, answer, p_skip, urgent)
    return _Decision(GateReason.JEV_RUN, GateRun(), answer, p_skip)


async def _ask_jev(
    gate: TriggerGate, event: _GateEvent, automation: str, *, hold: GateHold | None
) -> _Decision:
    state, questions = gate_request(gate, event.fields, automation, quiet=hold is not None)
    started = time.perf_counter()
    try:
        async with asyncio.timeout(TRIGGER_GATE_JEV_TIMEOUT_SECONDS):
            bodies = await asyncio.gather(
                *(post_decisions(state, questions) for _ in range(TRIGGER_GATE_JEV_SAMPLES))
            )
        decision = _settle(gate, bodies, event, hold=hold)
    except Exception as e:
        # The one degradation a gate has: run as if it were not there, or wait for the morning.
        reason = next(
            (reason for kinds, reason in _FAILURE_REASONS if isinstance(e, kinds)),
            GateReason.JEV_ERROR,
        )
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
    answer, urgent = decision.answer, decision.urgency
    log.set(
        trigger_gate={
            job.id: {
                "owner": job.owner.value,
                "kind": gate.kind.value,
                "outcome": outcome.value,
                "reason": decision.reason.value,
                "enforced": enforced,
                "skip_probability": decision.skip_probability,
                "choice": answer.choice if answer else None,
                "confidence": answer.confidence if answer else None,
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
    return GateHold(after_quiet_hours(local_now)) if in_quiet_hours(local_now) else None


async def quiet_hours_hold(gate: TriggerGate | None, user_id: str) -> GateHold | None:
    """Return the hold a run of the job behind gate waits on if it would start now, or None.

    An enforced gate starts no run inside the user's quiet hours; an urgent run is
    decided per event, so the caller says when one is carried.
    """
    if gate is None or not gate.enabled or gate.kind not in ENFORCED_GATE_KINDS:
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
        decision = await _ask_jev(gate, event, job.automation, hold=hold)
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        enforced = gate.kind in ENFORCED_GATE_KINDS and await is_trigger_gates_enforced(job.user_id)
        verdict = decision.verdict if enforced else GateRun()
        _record(gate, job, trigger_name, decision, _OUTCOMES[type(verdict)], enforced=enforced)
    return verdict
