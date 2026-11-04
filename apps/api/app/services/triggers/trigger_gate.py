"""Trigger gates: one JEV call about a fired event, made before it costs a run.

Both fan-outs of TriggerHandler.process_event call decide_gate before anything is
claimed, buffered or queued, so a skipped event leaves nothing behind that marks
it handled. By day only P(skip label) >= 0.95 skips, and every other answer or
failure runs. Inside the user's quiet hours the same call also asks whether the
event is worth waking them for: P(urgent) >= 0.95 runs now, then a confident
skip skips, and everything else, every failure included, waits for 08:00.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import time
from typing import Final

import httpx

from app.constants.trigger_gates import (
    AUTHORED_GATE_QUESTION,
    AUTHORED_GATE_RUN_LABEL,
    AUTHORED_GATE_SKIP_MEANING,
    ENFORCED_GATE_KINDS,
    GMAIL_MESSAGE_TRIGGERS,
    QUIET_HOURS_BYPASS_REASONS,
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_AUTOMATION_MAX_CHARS,
    TRIGGER_GATE_FIELD_MAX_CHARS,
    TRIGGER_GATE_INSTRUCTIONS,
    TRIGGER_GATE_JEV_TIMEOUT_SECONDS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_LABEL,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_SKIPPED_SUMMARY,
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
from app.services.triggers.condition_matching import resolve_payload_value
from app.services.triggers.gmail_signals import gmail_gate_view
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
    """Do not run the job; summary is the line its run history shows."""

    condition: str

    @property
    def summary(self) -> str:
        return TRIGGER_GATE_SKIPPED_SUMMARY.format(condition=self.condition)


@dataclass(frozen=True, slots=True)
class GateHold:
    """Run the job when the user's quiet hours end; until is that moment on their clock."""

    until: datetime

    @property
    def stamp(self) -> QuietHoursHold:
        return QuietHoursHold()

    def batch_seconds(self, window_seconds: int) -> int:
        """Seconds a held event's batch waits: its whole window, then out of any quiet hours it ends in."""
        now = datetime.now(self.until.tzinfo)
        runs_at = after_quiet_hours(max(self.until, now + timedelta(seconds=window_seconds)))
        return int((runs_at - now).total_seconds())


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


@dataclass(frozen=True, slots=True)
class Urgency:
    """How likely an event is worth waking the user for, and the urgent choice JEV leans to."""

    probability: float
    choice: UrgentChoice


@dataclass(frozen=True, slots=True)
class _GateEvent:
    """The event as JEV reads it; a thread continuation runs by day without asking."""

    fields: dict[str, object]
    continues_thread: bool = False


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
        raise ValueError(f"gate answer has no usable probabilities: {probabilities!r}"[:300])
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
        raise ValueError(f"urgent answer has no usable probabilities: {probabilities!r}"[:300])
    leaning = max(QUIET_HOURS_BYPASS_REASONS, key=lambda choice: probabilities.get(choice, 0.0))
    return Urgency(1 - probabilities[UrgentChoice.CAN_WAIT], leaning)


def _clip(value: object) -> object | None:
    if isinstance(value, str):
        return clip_text(" ".join(value.split()), TRIGGER_GATE_FIELD_MAX_CHARS)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [clip_text(v, TRIGGER_GATE_FIELD_MAX_CHARS) for v in value]
    return None


def _event(trigger_name: str, payload: Mapping[str, object]) -> _GateEvent | None:
    """Return the event JEV reads; None when there is nothing it can read.

    A Gmail message that continues a thread, or that the signals cannot place
    as new, is marked a continuation. Any other trigger sends its matchable
    catalog fields.
    """
    if trigger_name in GMAIL_MESSAGE_TRIGGERS:
        view = gmail_gate_view(payload)
        if view is None:
            return None
        return _GateEvent(view.as_event(), continues_thread=view.continues_thread is not False)
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        return None
    event = {
        name: value
        for name in entry.field_names
        if (value := _clip(resolve_payload_value(payload, name))) is not None
    }
    return _GateEvent(event) if event else None


def _settle(
    gate: TriggerGate, body: JevDecisionsResponse, *, hold: GateHold | None, continues_thread: bool
) -> _Decision:
    """Read JEV's answers in the settle order; hold is what quiet hours do, None by day."""
    urgent: Urgency | None = None
    if hold is not None:
        labels = _URGENT_LABELS
        urgent = urgency(body.choice(TRIGGER_GATE_URGENT_QUESTION_KEY, labels, label="urgent "))
        if urgent.probability >= TRIGGER_GATE_URGENT_PROBABILITY:
            bypass = GateBypass(QUIET_HOURS_BYPASS_REASONS[urgent.choice])
            return _Decision(GateReason.JEV_URGENT, bypass, urgency=urgent)
        if continues_thread:
            return _Decision(GateReason.JEV_CAN_WAIT, hold, urgency=urgent)
    answer = body.choice(TRIGGER_GATE_QUESTION_KEY, _question(gate).labels, label="gate ")
    p_skip = skip_probability(gate, answer)
    if p_skip >= TRIGGER_GATE_SKIP_PROBABILITY:
        return _Decision(
            GateReason.JEV_SKIP, GateSkip(gate.display_condition), answer, p_skip, urgent
        )
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
            body = await post_decisions(state, questions)
        decision = _settle(gate, body, hold=hold, continues_thread=event.continues_thread)
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


async def decide_gate(
    gate: TriggerGate | None, job: GatedJob, *, trigger_name: str, payload: Mapping[str, object]
) -> GateVerdict:
    """Decide what one fired event does to its job's run, on the user's own clock.

    Counts the decision, writes it to the wide event under the job's id and sends
    trigger:gate_decided. A gate that is absent or turned off is not asked.
    """
    if gate is None or not gate.enabled:
        return GateRun()
    local_now = datetime.now((await get_profile_timezone(job.user_id)).tzinfo)
    hold = GateHold(after_quiet_hours(local_now)) if in_quiet_hours(local_now) else None
    event = _event(trigger_name, payload)
    if event is None or (event.continues_thread and hold is None):
        decision = _Decision(GateReason.FREE_RUN, hold or GateRun())
    else:
        decision = await _ask_jev(gate, event, job.automation, hold=hold)
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        enforced = gate.kind in ENFORCED_GATE_KINDS and await is_trigger_gates_enforced(job.user_id)
        verdict = decision.verdict if enforced else GateRun()
        _record(gate, job, trigger_name, decision, _OUTCOMES[type(verdict)], enforced=enforced)
    return verdict
