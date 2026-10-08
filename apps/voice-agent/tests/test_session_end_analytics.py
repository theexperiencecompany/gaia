"""The voice job's PostHog events are delivered before its process exits.

LiveKit runs one job per process and leaves it through multiprocessing, which
skips atexit, so the client's own exit flush never runs and the batch still
queued (voice:session_ended at least) is lost unless the job flushes it.
"""

import asyncio
from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from livekit.agents import AgentSession, JobContext
from src.agent import _register_session_logging

from shared.py.analytics import PostHogAnalytics, VoiceAnalyticsEvents

USER_ID = "6812f0b3c9a14e2b7d5a91cc"

ShutdownCallback = Callable[[str], Coroutine[Any, Any, None]]


def _run_session_end(analytics: MagicMock) -> None:
    callbacks: list[ShutdownCallback] = []
    ctx = SimpleNamespace(
        room=SimpleNamespace(name=f"voice_{USER_ID}"),
        add_shutdown_callback=callbacks.append,
    )
    session = SimpleNamespace(on=lambda _event: lambda handler: handler)
    identity = {"room": ctx.room.name, "user_id": USER_ID, "job_id": "job-1"}

    _register_session_logging(
        cast(JobContext, ctx), cast(AgentSession, session), identity, "trace-1", analytics
    )
    for callback in callbacks:
        asyncio.run(callback("room_deleted"))


def test_session_end_is_captured_then_the_client_is_shut_down() -> None:
    analytics = MagicMock(spec=PostHogAnalytics)

    _run_session_end(analytics)

    analytics.capture.assert_called_once()
    assert analytics.capture.call_args.args[:2] == (USER_ID, VoiceAnalyticsEvents.SESSION_ENDED)
    assert [call[0] for call in analytics.method_calls] == ["capture", "shutdown"]
