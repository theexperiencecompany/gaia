"""A voice session counts once on gaia_voice_session_total, as error when LiveKit closed it for one."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from livekit.agents import AgentSession, CloseEvent, CloseReason, JobContext
from prometheus_client import REGISTRY
import pytest
from src.agent import _register_session_logging
from src.metrics import VoiceSessionOutcome

from shared.py.analytics import PostHogAnalytics, UserId

USER_ID = "6812f0b3c9a14e2b7d5a91cc"


def _close_handler() -> Callable[[CloseEvent], None]:
    handlers: dict[str, Callable[..., Any]] = {}

    def on(event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            handlers[event] = handler
            return handler

        return register

    ctx = SimpleNamespace(
        room=SimpleNamespace(name=f"voice_{USER_ID}"), add_shutdown_callback=lambda _callback: None
    )
    _register_session_logging(
        cast(JobContext, ctx),
        cast(AgentSession, SimpleNamespace(on=on)),
        {"room": ctx.room.name, "user_id": USER_ID, "job_id": "job-1"},
        "trace-1",
        MagicMock(spec=PostHogAnalytics),
        UserId(USER_ID),
    )
    return handlers["close"]


def _count(outcome: VoiceSessionOutcome) -> float:
    return REGISTRY.get_sample_value("gaia_voice_session_total", {"outcome": outcome.value}) or 0.0


@pytest.mark.parametrize(
    ("reason", "counted", "untouched"),
    [
        (CloseReason.USER_INITIATED, VoiceSessionOutcome.OK, VoiceSessionOutcome.ERROR),
        (CloseReason.PARTICIPANT_DISCONNECTED, VoiceSessionOutcome.OK, VoiceSessionOutcome.ERROR),
        (CloseReason.ERROR, VoiceSessionOutcome.ERROR, VoiceSessionOutcome.OK),
    ],
)
def test_a_closed_session_counts_once_under_its_outcome(
    reason: CloseReason, counted: VoiceSessionOutcome, untouched: VoiceSessionOutcome
) -> None:
    on_close = _close_handler()
    counted_before, untouched_before = _count(counted), _count(untouched)

    on_close(CloseEvent(reason=reason))

    assert _count(counted) == counted_before + 1
    assert _count(untouched) == untouched_before
