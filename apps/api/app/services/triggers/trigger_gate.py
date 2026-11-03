"""Trigger gates: decide, at fire time, whether an event is worth its workflow or todo run.

Both fan-outs of TriggerHandler.process_event call admit_event before anything is
claimed, buffered or queued, so a skipped event leaves no trace that it was handled.
Code owns the safety rule: only a skip choice at the gate's min confidence skips; a
low-confidence verdict, a JEV error, a timeout or a malformed answer runs the job.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import time

from app.constants.trigger_gates import (
    TRIGGER_GATE_AUTOMATION_MAX_CHARS,
    TRIGGER_GATE_FALLBACK_MAX_FIELDS,
    TRIGGER_GATE_FIELD_MAX_CHARS,
    TRIGGER_GATE_INSTRUCTIONS,
    TRIGGER_GATE_JEV_TIMEOUT_SECONDS,
    TRIGGER_GATE_QUESTION_KEY,
    GateOutcome,
    GateOwner,
    GateReason,
)
from app.models.jev_models import JevChoiceAnswer
from app.models.trigger_subscription_models import (
    ConditionMatch,
    SubscriptionCondition,
    TriggerGate,
)
from app.services.analytics_service import capture
from app.services.feature_flags import is_trigger_gates_enforced
from app.services.hil.jev_client import post_decisions
from app.services.latency_metrics import observe_trigger_gate_decision
from app.services.triggers.condition_matching import conditions_match, resolve_payload_value
from app.services.triggers.matchable_fields import get_matchable_trigger
from app.utils.general_utils import clip_text
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.catalog.workflows import WorkflowTriggerGateDecided
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class GateDecision:
    """One event's verdict; detail is the plain-text reason a skipped run shows."""

    outcome: GateOutcome
    reason: GateReason
    detail: str
    choice: str | None = None
    confidence: float | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """A decision plus whether it was allowed to act; a shadow gate never skips."""

    decision: GateDecision
    enforced: bool

    @property
    def skips(self) -> bool:
        return self.enforced and self.decision.outcome is GateOutcome.SKIP


def _clip_value(value: object) -> object | None:
    if isinstance(value, str):
        return clip_text(" ".join(value.split()), TRIGGER_GATE_FIELD_MAX_CHARS)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [clip_text(v, TRIGGER_GATE_FIELD_MAX_CHARS) for v in value]
    return None


def event_fields(trigger_name: str, payload: Mapping[str, object]) -> dict[str, object]:
    """Return the event as JEV reads it: the trigger's curated fields, else its first scalar fields."""
    entry = get_matchable_trigger(trigger_name)
    if entry is not None:
        names = entry.field_names
        pairs = ((name, resolve_payload_value(payload, name)) for name in names)
    else:
        pairs = ((k, v) for k, v in payload.items())
    fields: dict[str, object] = {}
    for name, raw in pairs:
        value = _clip_value(raw)
        if value is None:
            continue
        fields[name] = value
        if entry is None and len(fields) >= TRIGGER_GATE_FALLBACK_MAX_FIELDS:
            break
    return fields


def gate_request(
    gate: TriggerGate, trigger_name: str, payload: Mapping[str, object], automation: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Build the Decisions state and question for one event: event fields plus the job's intent."""
    state: dict[str, object] = {
        "event": event_fields(trigger_name, payload),
        "automation": clip_text(automation, TRIGGER_GATE_AUTOMATION_MAX_CHARS),
    }
    question: dict[str, object] = {
        "type": "choice",
        "instructions": TRIGGER_GATE_INSTRUCTIONS.format(question=gate.question),
        "criteria": {choice.label: choice.meaning for choice in gate.choices},
    }
    return state, {TRIGGER_GATE_QUESTION_KEY: question}


def automation_text(title: str, description: str | None) -> str:
    """Name the job a gate guards, as JEV reads it: its title and what it is for."""
    return f"{title}: {description}" if description else title


def _describe_rule(condition: SubscriptionCondition) -> str:
    return f"{condition.field_name} {condition.operator.value.replace('_', ' ')} {condition.value}"


def settle_gate(gate: TriggerGate, answer: JevChoiceAnswer, latency_ms: int) -> GateDecision:
    """Apply the code rule to JEV's answer. Pure, shared by prod and the eval."""
    confidence = float(answer.confidence or 0.0)
    meaning = next(c.meaning for c in gate.choices if c.label == answer.choice)
    detail = f"{meaning} ({answer.choice}, {confidence:.2f})"
    if answer.choice not in gate.skip_on:
        outcome, reason = GateOutcome.RUN, GateReason.JEV_RUN
    elif confidence >= gate.min_confidence:
        outcome, reason = GateOutcome.SKIP, GateReason.JEV_SKIP
    else:
        outcome, reason = GateOutcome.RUN, GateReason.JEV_UNSURE
    return GateDecision(outcome, reason, detail, answer.choice, confidence, latency_ms)


async def decide_gate(
    gate: TriggerGate, trigger_name: str, payload: Mapping[str, object], automation: str
) -> GateDecision:
    """Free rules first, then one JEV call; any JEV failure decides run."""
    for condition in gate.run_when:
        if conditions_match(trigger_name, [condition], payload, ConditionMatch.ALL):
            return GateDecision(GateOutcome.RUN, GateReason.RULE, _describe_rule(condition))
    for condition in gate.skip_when:
        if conditions_match(trigger_name, [condition], payload, ConditionMatch.ALL):
            return GateDecision(GateOutcome.SKIP, GateReason.RULE, _describe_rule(condition))
    state, questions = gate_request(gate, trigger_name, payload, automation)
    started = time.perf_counter()
    try:
        body = await post_decisions(
            state, questions, timeout_seconds=TRIGGER_GATE_JEV_TIMEOUT_SECONDS
        )
        answer = body.choice(
            TRIGGER_GATE_QUESTION_KEY, [c.label for c in gate.choices], label="gate "
        )
    except Exception as e:
        # The one degradation a gate has: run as if it were not there.
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.warning(
            "trigger_gate.jev_failed",
            trigger_name=trigger_name,
            error=str(e)[:300],
            error_type=type(e).__name__,
            latency_ms=latency_ms,
        )
        return GateDecision(
            GateOutcome.RUN,
            GateReason.JEV_ERROR,
            f"gate check failed ({type(e).__name__})",
            latency_ms=latency_ms,
        )
    return settle_gate(gate, answer, int((time.perf_counter() - started) * 1000))


async def admit_event(
    gate: TriggerGate | None,
    *,
    owner: GateOwner,
    user_id: str,
    trigger_name: str,
    payload: Mapping[str, object],
    automation: str,
) -> GateVerdict | None:
    """Decide and record one gated event; None when there is no enabled gate to ask."""
    if gate is None or not gate.enabled:
        return None
    decision = await decide_gate(gate, trigger_name, payload, automation)
    verdict = GateVerdict(decision, enforced=await is_trigger_gates_enforced(user_id))
    observe_trigger_gate_decision(
        owner=owner.value,
        outcome=decision.outcome.value,
        reason=decision.reason.value,
        enforced=verdict.enforced,
    )
    log.set(
        trigger_gate={
            "owner": owner.value,
            "outcome": decision.outcome.value,
            "reason": decision.reason.value,
            "choice": decision.choice,
            "confidence": decision.confidence,
            "latency_ms": decision.latency_ms,
            "enforced": verdict.enforced,
            "skipped": verdict.skips,
        }
    )
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        capture(
            UserId(user_id),
            WorkflowTriggerGateDecided(
                owner_type=owner.value,
                trigger_name=trigger_name,
                outcome=decision.outcome.value,
                reason=decision.reason.value,
                author=gate.author.value,
                enforced=verdict.enforced,
                skipped=verdict.skips,
                latency_ms=decision.latency_ms,
            ),
        )
    return verdict
