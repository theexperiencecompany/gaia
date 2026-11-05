"""Trigger gates: one JEV question about a fired event, asked before it costs a run.

Both fan-outs of TriggerHandler.process_event call gate_skip before anything is
claimed, buffered or queued, so a skipped event leaves nothing behind that marks
it handled. Only P(skip label) >= 0.95 skips; every other answer, and every
failure, runs the job as if the gate were not there.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import time

import httpx

from app.constants.integrations import EVENT_ACCOUNT_ID_KEY
from app.constants.trigger_gates import (
    AUTHORED_GATE_QUESTION,
    AUTHORED_GATE_RUN_LABEL,
    AUTHORED_GATE_SKIP_MEANING,
    ENFORCED_GATE_KINDS,
    GMAIL_MESSAGE_TRIGGERS,
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_AUTOMATION_MAX_CHARS,
    TRIGGER_GATE_EVENT_LABEL_MAX_CHARS,
    TRIGGER_GATE_FIELD_MAX_CHARS,
    TRIGGER_GATE_INSTRUCTIONS,
    TRIGGER_GATE_JEV_TIMEOUT_SECONDS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_LABEL,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_SKIPPED_SUMMARY,
    TRIGGER_GATE_UNTITLED_EVENT,
    GateOutcome,
    GateOwner,
    GateQuestion,
    GateReason,
)
from app.models.jev_models import JevChoiceAnswer
from app.models.trigger_gate_models import AuthoredGate, SystemGate, TriggerGate
from app.services.analytics_service import capture
from app.services.feature_flags import is_trigger_gates_enforced
from app.services.hil.jev_client import JevUnconfiguredError, post_decisions
from app.services.latency_metrics import observe_trigger_gate_decision
from app.services.mail.thread_participation import user_wrote_in_thread
from app.services.triggers.condition_matching import resolve_payload_value
from app.services.triggers.gmail_signals import GmailGateView, gmail_gate_view
from app.services.triggers.matchable_fields import get_matchable_trigger
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


@dataclass(frozen=True, slots=True)
class GateSkip:
    """A gated event that must not run; summary is the line its run history shows.

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
class GatedJob:
    """The job a gate stands in front of: a workflow or one todo subscription, and what it does."""

    owner: GateOwner
    id: str
    user_id: str
    automation: str
    # Gmail threads the job already follows; a message on one of them runs unasked.
    tracked_threads: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class _GateEvent:
    """The event as JEV reads it, the line a skip names it by, and the thread it continues."""

    fields: dict[str, object]
    label: str
    continued_thread: str | None = None


@dataclass(frozen=True, slots=True)
class _Decision:
    reason: GateReason
    answer: JevChoiceAnswer | None = None
    skip_probability: float | None = None
    latency_ms: int | None = None
    skip: GateSkip | None = None


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
    gate: TriggerGate, event: Mapping[str, object], automation: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and questions for one event; pure, so the eval sends the same bytes.

    A preset sends its own job text; an authored gate sends the owner's automation.
    """
    question = _question(gate)
    job = (
        SYSTEM_GATE_PRESETS[gate.preset].automation if isinstance(gate, SystemGate) else automation
    )
    state: dict[str, object] = {"event": dict(event), "automation": job}
    return state, {
        TRIGGER_GATE_QUESTION_KEY: {
            "type": "choice",
            "instructions": TRIGGER_GATE_INSTRUCTIONS.format(question=question.question),
            "criteria": question.criteria(),
        }
    }


def skip_probability(gate: TriggerGate, answer: JevChoiceAnswer) -> float:
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
    """Name an email by its sender and subject, as many of them as it has."""
    parts = [_label(view.sender)] if view.sender else []
    if view.subject:
        parts.append(f'"{_label(view.subject)}"')
    return ", ".join(parts) or TRIGGER_GATE_UNTITLED_EVENT.format(trigger_name=trigger_name)


def _event(trigger_name: str, payload: Mapping[str, object]) -> _GateEvent | None:
    """Return the event JEV reads; None when the event runs without asking.

    A Gmail message the signals cannot place runs, so an unreadable payload never
    reaches a skip; one that continues a thread carries that thread. Any other
    trigger sends its matchable catalog fields, and runs when it has none.
    """
    if trigger_name in GMAIL_MESSAGE_TRIGGERS:
        view = gmail_gate_view(payload)
        if view is None or view.continues_thread is None:
            return None
        thread = resolve_payload_value(payload, "thread_id") if view.continues_thread else None
        return _GateEvent(
            view.as_event(),
            _gmail_label(view, trigger_name),
            thread if isinstance(thread, str) else None,
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

    A thread Gmail cannot be asked about runs, so a lookup failure never reaches a skip.
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


async def _ask_jev(gate: TriggerGate, event: _GateEvent, automation: str) -> _Decision:
    state, questions = gate_request(gate, event.fields, automation)
    started = time.perf_counter()
    try:
        async with asyncio.timeout(TRIGGER_GATE_JEV_TIMEOUT_SECONDS):
            body = await post_decisions(state, questions)
        answer = body.choice(TRIGGER_GATE_QUESTION_KEY, _question(gate).labels, label="gate ")
        p_skip = skip_probability(gate, answer)
    except Exception as e:
        # The one degradation a gate has: run as if it were not there.
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
        return _Decision(reason, latency_ms=int((time.perf_counter() - started) * 1000))
    latency_ms = int((time.perf_counter() - started) * 1000)
    if p_skip < TRIGGER_GATE_SKIP_PROBABILITY:
        return _Decision(GateReason.JEV_RUN, answer, p_skip, latency_ms)
    skip = GateSkip(event.label, gate.display_condition, p_skip)
    return _Decision(GateReason.JEV_SKIP, answer, p_skip, latency_ms, skip)


async def gate_skip(
    gate: TriggerGate | None, job: GatedJob, *, trigger_name: str, payload: Mapping[str, object]
) -> GateSkip | None:
    """Decide whether one fired event skips its job's run; None runs it, and any failure runs.

    Counts the decision, writes it to the wide event under the job's id and sends
    trigger:gate_decided. A gate that is absent or turned off is not asked.
    """
    if gate is None or not gate.enabled:
        return None
    try:
        return await _decide(gate, job, trigger_name, payload)
    except Exception:
        # A gate that cannot decide runs its job, and never costs a fan-out its other jobs.
        log.error("trigger_gate.failed", owner=job.owner.value, job_id=job.id, exc_info=True)
        return None


async def _decide(
    gate: TriggerGate, job: GatedJob, trigger_name: str, payload: Mapping[str, object]
) -> GateSkip | None:
    event = _event(trigger_name, payload)
    if event is None or (
        event.continued_thread is not None
        and await _in_conversation(job, event.continued_thread, payload)
    ):
        decision = _Decision(GateReason.FREE_RUN)
    else:
        decision = await _ask_jev(gate, event, job.automation)
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        enforced = gate.kind in ENFORCED_GATE_KINDS and await is_trigger_gates_enforced(job.user_id)
        outcome = (
            GateOutcome.SKIP
            if enforced and decision.reason is GateReason.JEV_SKIP
            else GateOutcome.RUN
        )
        observe_trigger_gate_decision(
            owner=job.owner.value, outcome=outcome.value, reason=decision.reason.value
        )
        answer = decision.answer
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
                enforced=enforced,
                latency_ms=decision.latency_ms,
            ),
        )
    return decision.skip if outcome is GateOutcome.SKIP else None
