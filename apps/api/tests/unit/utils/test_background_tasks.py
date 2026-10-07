"""spawn_background_task: a detached task's failure is never lost.

Nobody awaits a fire-and-forget task, so an exception it raises has nowhere to
go; the helper's own done-callback is the one place it can be seen. These pin
that every caller gets that event, and that cancellation stays a clean exit.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log, wide_task
from tests.helpers import WideEventRecorder


class _HeartbeatLost(RuntimeError):
    pass


async def _fails() -> None:
    raise _HeartbeatLost("redis went away")


async def _finishes() -> str:
    return "ok"


async def _settle(task: asyncio.Task[object]) -> None:
    """Let the task end and its done-callbacks run, without re-raising its outcome."""
    await asyncio.wait({task})
    await asyncio.sleep(0)


def _background_events(recorder: WideEventRecorder) -> list[dict[str, object]]:
    return [event for event in recorder.events if event["_message"] == "background_task"]


class TestSpawnBackgroundTaskFailureEvent:
    async def test_a_raised_exception_emits_a_failed_event_with_the_task_name_and_error_type(
        self,
    ) -> None:
        recorder = WideEventRecorder()
        with patch("shared.py.wide_events._loguru", recorder):
            async with wide_task("spawner"):
                trace_id = log.get_trace_id()
                task = spawn_background_task(_fails(), name="browser_job_heartbeat")
            await _settle(task)

        [event] = _background_events(recorder)
        assert event["task"] == "browser_job_heartbeat"
        assert event["outcome"] == "failed"
        assert event["reason"] == "unhandled_exception"
        assert event["error_type"] == "_HeartbeatLost"
        assert event["error"] == "redis went away"
        assert event["trace_id"] == trace_id

    async def test_an_unnamed_task_is_named_after_its_coroutine(self) -> None:
        recorder = WideEventRecorder()
        with patch("shared.py.wide_events._loguru", recorder):
            task = spawn_background_task(_fails())
            await _settle(task)

        [event] = _background_events(recorder)
        assert event["task"] == "_fails"

    async def test_a_cancelled_task_emits_nothing_and_stays_cancelled(self) -> None:
        recorder = WideEventRecorder()
        with patch("shared.py.wide_events._loguru", recorder):
            task = spawn_background_task(asyncio.sleep(60), name="keepalive")
            await asyncio.sleep(0)
            task.cancel()
            await _settle(task)

        assert task.cancelled()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert _background_events(recorder) == []

    async def test_a_task_that_finishes_emits_nothing(self) -> None:
        recorder = WideEventRecorder()
        with patch("shared.py.wide_events._loguru", recorder):
            task = spawn_background_task(_finishes(), name="touch")
            await _settle(task)

        assert task.result() == "ok"
        assert _background_events(recorder) == []

    async def test_the_callers_own_on_done_still_runs(self) -> None:
        seen: list[bool] = []
        with patch("shared.py.wide_events._loguru", WideEventRecorder()):
            task = spawn_background_task(
                _fails(), name="stream", on_done=lambda t: seen.append(t.done())
            )
            await _settle(task)

        assert seen == [True]
