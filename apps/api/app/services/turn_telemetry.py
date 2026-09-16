"""One fan-out for turn telemetry across Agnost, Latitude, and Laminar.

Both agent entry points (streaming chat, silent background) open the three
vendor scopes together and close them with one shared outcome, so a turn reads
identically in every dashboard: user-cancelled stays separable from failure
everywhere, errors carry the same exception, properties match.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

from agnost import Interaction

from app.config.settings import settings
from app.constants.agents import COMMS_AGENT_NAME
from app.services import agnost_service, laminar_service, latitude_service
from app.services.laminar_service import TurnScope
from app.services.latitude_service import TurnCapture
from shared.py.wide_events import log


class TurnOutcome(StrEnum):
    """Terminal outcome of a turn, mapped explicitly per vendor.

    Cancelled is its own outcome, not a failure: a user hitting Stop and a
    provider outage must read differently in every dashboard (and in Laminar
    signals), or "is the model getting worse or are users just impatient?"
    becomes unanswerable months from now.
    """

    SUCCESS = "success"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TurnHandles(TypedDict):
    """One vendor scope per telemetry backend; any may be None when disabled."""

    agnost: Interaction | None
    latitude: TurnCapture | None
    laminar: TurnScope | None


# Logged once per process when a turn opens zero scopes, so "telemetry is
# deliberately off" is greppable and distinct from per-backend failure
# warnings. A rotated-but-typo'd key otherwise reads as weeks of silence.
_disabled_logged = False


@dataclass(frozen=True)
class TurnSpec:
    """What identifies a turn across all three backends.

    A single value (instead of seven parallel arguments) so every entry
    point — streaming, silent, narrator, executor, HIL-approval — opens its
    turn the same way. ``source``/``mode``/``tier``/``env`` are owned by the
    fan-out (uniformity is the point); anything else rides in ``properties``.

    ``mode`` has deliberately NO default: every turn knows whether a user is
    waiting on it, and a default would let a future reader (or mutant) blur
    interactive and background turns into each other silently.
    """

    user_id: str
    conversation_id: str
    user_input: str
    mode: str
    source: str | None = None
    tier: str = COMMS_AGENT_NAME
    properties: dict[str, str | bool | None] | None = None


def begin_turn_all(spec: TurnSpec) -> TurnHandles:
    """Open all three vendor scopes. Never raises (each service guards)."""
    # Reserved keys win by application order alone — a caller key colliding
    # with one is overwritten below, so no separate filter is needed.
    # env splits shared dashboards (one org/project across dev/staging/prod).
    props = {
        **(spec.properties or {}),
        "source": spec.source or "background",
        "mode": spec.mode,
        "tier": spec.tier,
        "env": settings.ENV,
    }
    handles: TurnHandles = {
        "agnost": agnost_service.begin_turn(
            user_id=spec.user_id,
            conversation_id=spec.conversation_id,
            user_input=spec.user_input,
            agent_name=COMMS_AGENT_NAME,
            properties=props,
        ),
        "latitude": latitude_service.begin_turn(
            user_id=spec.user_id,
            conversation_id=spec.conversation_id,
            agent_name=COMMS_AGENT_NAME,
            properties=props,
        ),
        "laminar": laminar_service.begin_turn(
            user_id=spec.user_id,
            conversation_id=spec.conversation_id,
            agent_name=COMMS_AGENT_NAME,
            user_input=spec.user_input,
            properties=props,
        ),
    }
    global _disabled_logged
    if not _disabled_logged and all(v is None for v in handles.values()):
        _disabled_logged = True
        log.info("turn_telemetry_no_scopes", reason="keys unset or all begins failed")
    return handles


def end_turn_all(
    handles: TurnHandles | None,
    *,
    output: str,
    error: Exception | None = None,
    cancelled: bool = False,
) -> None:
    """Close all three scopes with one outcome. None handles is a no-op. Never raises."""
    if handles is None:
        return
    # An explicit error dominates: a turn that both errored and saw a cancel
    # flag failed — the exception is what needs debugging.
    outcome = (
        TurnOutcome.FAILED
        if error is not None
        else TurnOutcome.CANCELLED
        if cancelled
        else TurnOutcome.SUCCESS
    )
    outcome_value = outcome.value
    properties: dict[str, str | bool | None] = {
        "cancelled": outcome is TurnOutcome.CANCELLED,
        "has_error": error is not None,
        "outcome": outcome_value,
    }
    agnost_service.end_turn(
        handles["agnost"],
        output=output,
        success=outcome is TurnOutcome.SUCCESS,
        properties=properties,
    )
    latitude_service.end_turn(
        handles["latitude"], error=error, cancelled=outcome is TurnOutcome.CANCELLED
    )
    laminar_service.end_turn(
        handles["laminar"],
        output=output,
        error=error,
        cancelled=outcome is TurnOutcome.CANCELLED,
    )
