"""Trigger gates: one JEV question about a fired event, asked before it costs a run.

Both fan-outs of TriggerHandler.process_event call gate_skip before anything is
claimed, buffered or queued, so a skipped event leaves nothing behind that marks
it handled. Only P(skip label) >= 0.95 skips; every other answer, and every
failure, runs the job as if the gate were not there.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import time

import httpx

from app.constants.trigger_gates import (
    AUTHORED_GATE_QUESTION,
    AUTHORED_GATE_RUN_LABEL,
    AUTHORED_GATE_SKIP_MEANING,
    ENFORCED_GATE_KINDS,
    GMAIL_MESSAGE_TRIGGERS,
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_AUTOMATION_MAX_CHARS,
    TRIGGER_GATE_FIELD_MAX_CHARS,
    TRIGGER_GATE_INSTRUCTIONS,
    TRIGGER_GATE_JEV_TIMEOUT_SECONDS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_LABEL,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_SKIPPED_SUMMARY,
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
from app.services.triggers.condition_matching import resolve_payload_value
from app.services.triggers.gmail_signals import gmail_gate_view
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
    """A gated event that must not run; summary is the line its run history shows."""

    condition: str

    @property
    def summary(self) -> str:
        return TRIGGER_GATE_SKIPPED_SUMMARY.format(condition=self.condition)


@dataclass(frozen=True, slots=True)
class GatedJob:
    """The job a gate stands in front of: a workflow or one todo subscription, and what it does."""

    owner: GateOwner
    id: str
    user_id: str
    automation: str


@dataclass(frozen=True, slots=True)
class _Decision:
    reason: GateReason
    answer: JevChoiceAnswer | None = None
    skip_probability: float | None = None
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


def _event(trigger_name: str, payload: Mapping[str, object]) -> dict[str, object] | None:
    """Return the event JEV reads; None when the event runs without asking.

    A Gmail message that continues a thread runs, and so does one the signals
    cannot place, so an unreadable payload never reaches a skip. Any other
    trigger sends its matchable catalog fields, and runs when it has none.
    """
    if trigger_name in GMAIL_MESSAGE_TRIGGERS:
        view = gmail_gate_view(payload)
        if view is None or view.continues_thread is not False:
            return None
        return view.as_event()
    entry = get_matchable_trigger(trigger_name)
    if entry is None:
        return None
    event = {
        name: value
        for name in entry.field_names
        if (value := _clip(resolve_payload_value(payload, name))) is not None
    }
    return event or None


async def _ask_jev(gate: TriggerGate, event: Mapping[str, object], automation: str) -> _Decision:
    state, questions = gate_request(gate, event, automation)
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
    reason = GateReason.JEV_SKIP if p_skip >= TRIGGER_GATE_SKIP_PROBABILITY else GateReason.JEV_RUN
    return _Decision(reason, answer, p_skip, int((time.perf_counter() - started) * 1000))


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
    decision = (
        _Decision(GateReason.FREE_RUN)
        if event is None
        else await _ask_jev(gate, event, job.automation)
    )
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
    return GateSkip(gate.display_condition) if outcome is GateOutcome.SKIP else None
