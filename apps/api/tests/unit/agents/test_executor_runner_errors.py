"""What the user is told when an executor run dies instead of finishing.

The crash path hands comms the run's terminal text. A raw exception string is
not a story, so comms invents one ("The browser task got cancelled partway
through... Want me to run it again?") — wrong about what happened AND an
invitation to re-run work that may have half-landed.
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.errors import GraphRecursionError
import pytest

from app.agents.core.background import executor_runner as er
from app.agents.core.background.session import ExecutorRun, RunKind
from app.constants.executor import EXECUTOR_STEP_LIMIT_MESSAGE
from app.models.user_models import AuthenticatedUser
from app.services.browser import jobs as jobs_mod
from tests._harness.redis_fakes import FakeRedisCache


async def _run_with(
    side_effect: BaseException, conversation_id: str = "conv-1"
) -> er._ExecutorResult:
    """Run _execute_executor with the graph execution raising side_effect."""
    ctx = SimpleNamespace(config={}, configurable={})
    run = ExecutorRun(
        stream_id="stream-1",
        conversation_id=conversation_id,
        user=AuthenticatedUser(user_id="u1"),
        kind=RunKind.LIVE,
        task_id="task-1",
        user_message_id=None,
        bot_message_id=None,
    )
    with (
        patch.object(er, "prepare_executor_execution", AsyncMock(return_value=(ctx, None))),
        patch.object(er, "make_redis_stream_writer", lambda _sid: None),
        patch.object(er, "execute_subagent_stream", AsyncMock(side_effect=side_effect)),
    ):
        return await er._execute_executor("do the thing", {}, run, None)


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> FakeRedisCache:
    fake = FakeRedisCache()
    monkeypatch.setattr(jobs_mod, "redis_cache", fake)
    return fake


@pytest.mark.unit
class TestExecutorCrashText:
    async def test_a_crash_never_hands_comms_the_raw_exception(self) -> None:
        result = await _run_with(RuntimeError("Watchdog timed out after 60s"))

        assert result.type == "error"
        assert "Watchdog timed out" not in result.text

    async def test_a_crash_tells_comms_not_to_offer_a_re_run(self) -> None:
        result = await _run_with(RuntimeError("boom"))

        assert result.text == er.EXECUTOR_CRASH_MESSAGE
        lowered = result.text.lower()
        assert "again" not in lowered
        assert "how they" in lowered or "how the user" in lowered

    async def test_an_exception_with_no_message_still_says_what_happened(self) -> None:
        # str(exc) is "" for plenty of real failures, and an empty error block is
        # exactly when comms invented a story and offered to re-run it.
        result = await _run_with(TimeoutError())

        assert result.type == "error"
        assert result.text == er.EXECUTOR_CRASH_MESSAGE

    async def test_a_user_stop_is_left_to_the_cancellation_path(self) -> None:
        # Swallowing CancelledError here would break cooperative cancellation:
        # a Stop is finalized as cancelled, not narrated as a crash.
        with pytest.raises(asyncio.CancelledError):
            await _run_with(asyncio.CancelledError())

    async def test_the_recursion_limit_keeps_its_own_actionable_message(self) -> None:
        result = await _run_with(GraphRecursionError("limit"))

        assert result.text == EXECUTOR_STEP_LIMIT_MESSAGE


@pytest.mark.unit
class TestOrphanedBrowserJob:
    """A failed run's message is the turn's only ending, so the job it left running must not speak.

    Measured: the executor spun on retrieve_tools and hit the step limit one
    second after enqueueing a browser job. Comms said nothing was done; the
    orphaned job ran three more minutes and delivered its own conclusion.
    """

    async def test_a_step_limit_cancels_the_job_left_in_flight(
        self, fake_cache: FakeRedisCache
    ) -> None:
        await jobs_mod.claim_conversation_slot("conv-1", "job-1")

        result = await _run_with(GraphRecursionError("limit"))

        assert result.text == EXECUTOR_STEP_LIMIT_MESSAGE
        assert await jobs_mod.job_cancel_requested("job-1") is True

    async def test_a_crash_cancels_the_job_left_in_flight(self, fake_cache: FakeRedisCache) -> None:
        await jobs_mod.claim_conversation_slot("conv-1", "job-1")

        result = await _run_with(RuntimeError("boom"))

        assert result.text == er.EXECUTOR_CRASH_MESSAGE
        assert await jobs_mod.job_cancel_requested("job-1") is True

    async def test_another_conversations_job_is_left_alone(
        self, fake_cache: FakeRedisCache
    ) -> None:
        await jobs_mod.claim_conversation_slot("conv-2", "job-2")

        await _run_with(GraphRecursionError("limit"))

        assert await jobs_mod.job_cancel_requested("job-2") is False

    async def test_a_redis_failure_still_hands_comms_the_runs_own_ending(
        self, fake_cache: FakeRedisCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            er, "cancel_conversation_browser_job", AsyncMock(side_effect=ConnectionError("down"))
        )

        result = await _run_with(GraphRecursionError("limit"))

        assert result.type == "error"
        assert result.text == EXECUTOR_STEP_LIMIT_MESSAGE


@pytest.mark.unit
class TestTheOrphanCancelIsOnTheRunsRecord:
    """The cancel happens off-screen, so the run's own wide event is the only trace of it."""

    @staticmethod
    def _lines(log: MagicMock, level: str, phrase: str) -> list[Any]:
        return [c for c in getattr(log, level).call_args_list if phrase in (c.args[0] or "")]

    async def test_a_cancelled_job_is_named_with_its_conversation_and_stream(
        self, fake_cache: FakeRedisCache
    ) -> None:
        await jobs_mod.claim_conversation_slot("conv-1", "job-1")

        with patch.object(er, "log") as log:
            await _run_with(GraphRecursionError("limit"))

        [line] = self._lines(log, "warning", "Cancelled the browser job orphaned")
        assert line.kwargs == {
            "conversation_id": "conv-1",
            "stream_id": "stream-1",
            "browser": {"job_id": "job-1"},
        }

    async def test_a_run_that_left_no_job_records_no_cancel(
        self, fake_cache: FakeRedisCache
    ) -> None:
        with patch.object(er, "log") as log:
            await _run_with(RuntimeError("boom"))

        assert self._lines(log, "warning", "Cancelled the browser job orphaned") == []

    async def test_a_cancel_that_could_not_reach_redis_is_recorded_with_its_cause(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            er, "cancel_conversation_browser_job", AsyncMock(side_effect=ConnectionError("down"))
        )

        with patch.object(er, "log") as log:
            await _run_with(RuntimeError("boom"))

        [line] = self._lines(log, "error", "Could not cancel the browser job")
        assert line.kwargs == {
            "conversation_id": "conv-1",
            "stream_id": "stream-1",
            "error": "down",
        }
