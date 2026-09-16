"""Latitude span scope for real agent turns. Never raises; missing key is a silent no-op."""

from dataclasses import dataclass

from latitude_telemetry import capture
from latitude_telemetry.sdk.context import CaptureScope
from latitude_telemetry.sdk.types import ContextOptions
from opentelemetry import trace
from opentelemetry.trace import Span

from app.config.settings import settings
from app.constants.agents import COMMS_AGENT_NAME
from shared.py.wide_events import log


@dataclass(frozen=True)
class TurnCapture:
    """A Latitude capture scope plus the span it opened.

    The span is read off the current context immediately after
    ``capture.start`` attaches it, so ``end_turn`` tags OUR span directly
    instead of trusting whatever happens to be current thousands of awaits
    later (a leaked child span would otherwise wear the turn's marker).
    Never nested: our flows strictly pair one begin with one end per turn.
    """

    scope: CaptureScope
    span: Span


def _configured() -> bool:
    return bool((settings.LATITUDE_API_KEY or "").strip())


def begin_turn(
    *,
    user_id: str,
    conversation_id: str,
    agent_name: str = COMMS_AGENT_NAME,
    properties: dict[str, str | bool | None] | None = None,
) -> TurnCapture | None:
    """Open a Latitude capture scope for this turn, or None when disabled/failing."""
    if not user_id or not _configured():
        return None
    try:
        metadata: dict[str, object] = {k: v for k, v in (properties or {}).items() if v is not None}
        options: ContextOptions = {
            "user_id": user_id,
            "session_id": conversation_id,
            "project": settings.LATITUDE_PROJECT,
            "metadata": metadata,
        }
        scope = capture.start(agent_name, options)
        return TurnCapture(scope=scope, span=trace.get_current_span())
    except Exception as exc:
        log.warning(
            "latitude_begin_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            conversation_id=conversation_id,
        )
        return None


def end_turn(
    scope: TurnCapture | None, *, error: Exception | None = None, cancelled: bool = False
) -> None:
    """Close a Latitude capture scope. No-op when scope is None. Never raises."""
    if scope is None:
        return
    try:
        # Cancelled is not a failure: end the span cleanly so it reads OK,
        # with an attribute splitting user-stops from real successes. Set on
        # the stored span (see TurnCapture), never the ambient current span.
        if cancelled and error is None and scope.span.is_recording():
            scope.span.set_attribute("cancelled", True)
        capture.end(scope.scope, error)
    except Exception as exc:
        log.warning(
            "latitude_end_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
