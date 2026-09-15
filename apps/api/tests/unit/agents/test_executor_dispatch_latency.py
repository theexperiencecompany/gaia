"""Unit tests for executor dispatch + run latency spans (Tasks 5-6).

Dispatch stamps t_dispatch_perf; the runner turns it into queue-wait, TTFT,
active and E2E observations. The LLM/graph itself is never driven —
run_executor_background runs with its execute step stubbed and its
delivery/lock boundaries mocked, so the assertions cover the timing and
PostHog wiring only.
"""

import asyncio
from contextlib import contextmanager
import sys
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import REGISTRY

from app.agents.core.background import executor_runner as er, session as sess
from app.agents.core.background.executor_runner import _ExecutorResult, run_executor_background
from app.agents.core.background.session import ExecutorRun, RunKind, get_session, teardown_session
from app.agents.tools import executor_tool as et
from app.constants.executor import EXECUTOR_PAUSED
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents


def _count(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0


def _sum(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_sum", labels) or 0.0


def _configurable(stream_id: str) -> dict[str, Any]:
    return {
        "stream_id": stream_id,
        "user_message_id": "umsg-1",
        "bot_message_id": "bmsg-1",
        "user_id": "user-1",
        "thread_id": "conv-1",
    }


def _run(stream_id: str, **overrides: Any) -> ExecutorRun:
    kwargs: dict[str, Any] = {
        "stream_id": stream_id,
        "conversation_id": "conv-1",
        "user": AuthenticatedUser(user_id="user-1"),
        "kind": RunKind.LIVE,
        "task_id": "task-1",
        "user_message_id": "umsg-1",
        "bot_message_id": None,
    }
    kwargs.update(overrides)
    return ExecutorRun(**kwargs)


def _mock_redis(held_value: str | None) -> MagicMock:
    """Stand in for the executor_tool redis_cache binding.

    Patches the module attribute, not the client property, which would lazily
    open a real connection.
    """
    mock_redis = MagicMock()
    mock_redis.client.get = AsyncMock(return_value=held_value)
    return mock_redis


class TestDispatchLatency:
    def setup_method(self) -> None:
        sess._sessions.clear()

    def teardown_method(self) -> None:
        sess._sessions.clear()

    async def test_busy_lock_queues_and_carries_dispatch_stamp(self) -> None:
        """The queued item carries the dispatch stamp the runner measures queue-wait from."""
        stream_id = "dispatch-queued"
        with (
            patch.object(et, "try_acquire_lock", AsyncMock(return_value=False)),
            patch.object(et, "redis_cache", _mock_redis("other-stream:other-task")),
            patch.object(et, "_acquire_lock_through_redirect", AsyncMock(return_value=False)),
            patch.object(et, "enqueue_task", AsyncMock()) as mock_enqueue,
            patch.object(et, "spawn_background_task") as mock_spawn,
        ):
            result = await et._dispatch_executor(
                task="do the thing",
                task_id="task-q",
                configurable=_configurable(stream_id),  # type: ignore[arg-type] -- minimal dispatch bag
                conversation_id="conv-1",
            )

        assert "queued" in result
        mock_spawn.assert_not_called()
        mock_enqueue.assert_called_once()
        session = get_session(stream_id)
        assert session is not None
        assert session.executor_queued_task_id == "task-q"
        item = mock_enqueue.call_args.args[1]
        assert item["task_id"] == "task-q"
        assert isinstance(item["t_dispatch_perf"], float)
        assert item["queued"] is True

    async def test_free_lock_spawns_live_run_with_dispatch_stamp(self) -> None:
        stream_id = "dispatch-live"
        captured: dict[str, Any] = {}
        real_from_config = ExecutorRun.from_configurable.__func__

        def _capture_from_config(
            cls: Any, configurable: Any, *, identity: Any, workflow_execution_id: Any = None
        ) -> ExecutorRun:
            run = real_from_config(
                cls, configurable, identity=identity, workflow_execution_id=workflow_execution_id
            )
            captured["run"] = run
            return run

        with (
            patch.object(et, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(
                et.ExecutorRun, "from_configurable", new=classmethod(_capture_from_config)
            ),
            patch.object(et, "spawn_background_task"),
        ):
            result = await et._dispatch_executor(
                task="do the thing",
                task_id="task-live",
                configurable=_configurable(stream_id),  # type: ignore[arg-type] -- minimal dispatch bag
                conversation_id="conv-1",
            )

        assert "Task accepted (task_id: task-live)" in result
        session = get_session(stream_id)
        assert session is not None and session.executor_spawned is True
        assert isinstance(captured["run"].t_dispatch_perf, float)
        teardown_session(stream_id)

    async def test_same_turn_duplicate_dispatch_emits_nothing(self) -> None:
        stream_id = "dispatch-dup"
        with (
            patch.object(et, "try_acquire_lock", AsyncMock(return_value=False)),
            patch.object(et, "redis_cache", _mock_redis(f"{stream_id}:task-first")),
            patch.object(et, "enqueue_task", AsyncMock()) as mock_enqueue,
            patch.object(et, "spawn_background_task") as mock_spawn,
        ):
            result = await et._dispatch_executor(
                task="do it again",
                task_id="task-second",
                configurable=_configurable(stream_id),  # type: ignore[arg-type] -- minimal dispatch bag
                conversation_id="conv-1",
            )

        assert "already running" in result
        mock_enqueue.assert_not_called()
        mock_spawn.assert_not_called()
        assert get_session(stream_id) is None

    async def test_redirect_wait_is_measured_within_budget(self) -> None:
        """The redirect wait is stamped on the wide event, within the redirect budget."""
        stream_id = "dispatch-redirect"
        attempts = {"n": 0}

        async def _flaky_acquire(lock_key: str, lock_value: str) -> bool:
            attempts["n"] += 1
            return attempts["n"] >= 3

        fake_time = MagicMock()
        # t_dispatch, redirect_start, then the stamp: a 3rd-decimal delta so the
        # rounding precision (2 vs 3 vs none) is load-bearing.
        fake_time.perf_counter.side_effect = [10.0, 20.0, 20.1234567]

        with (
            patch.object(et, "try_acquire_lock", side_effect=_flaky_acquire),
            patch.object(et, "redis_cache", _mock_redis("dying-stream:old-task")),
            patch.object(et.StreamManager, "is_cancelled", AsyncMock(return_value=True)),
            patch.object(et, "spawn_background_task"),
            patch.object(et, "log") as mock_log,
            patch.object(et, "time", new=fake_time),
        ):
            result = await et._dispatch_executor(
                task="redirected work",
                task_id="task-r",
                configurable=_configurable(stream_id),  # type: ignore[arg-type] -- minimal dispatch bag
                conversation_id="conv-1",
            )

        assert "Task accepted (task_id: task-r)" in result
        tool_logs = [
            call.kwargs["tool"]
            for call in mock_log.set.call_args_list
            if "redirect_wait_ms" in call.kwargs.get("tool", {})
        ]
        assert tool_logs == [
            {
                "name": et.CALL_EXECUTOR_NAME,
                "action": "dispatch",
                "task_id": "task-r",
                "redirect_wait_ms": 123.46,
            }
        ]
        teardown_session(stream_id)


class TestExecutorRunLatency:
    def setup_method(self) -> None:
        sess._sessions.clear()

    def teardown_method(self) -> None:
        sess._sessions.clear()

    async def _background(
        self,
        run: ExecutorRun,
        *,
        first_frame_at: float | None = None,
        result: _ExecutorResult | None = None,
        record_pause: bool | AsyncMock = True,
    ) -> MagicMock:
        """Drive run_executor_background with execute stubbed and the boundaries mocked.

        Returns the PostHog capture mock.
        """
        if first_frame_at is not None:
            session = sess.create_session(run.stream_id, run.kind)
            session.executor_first_frame_perf = first_frame_at
        pause_recorder = (
            record_pause
            if isinstance(record_pause, AsyncMock)
            else AsyncMock(return_value=record_pause)
        )
        with (
            patch.object(
                er,
                "_execute_executor",
                AsyncMock(return_value=result or _ExecutorResult("done", "final")),
            ),
            patch.object(er, "_record_pause", pause_recorder),
            patch.object(er, "_finalize_paused_run", AsyncMock()),
            patch.object(er, "_deliver_terminal_outcome", AsyncMock()),
            patch.object(er, "release_lock_if_owned", AsyncMock()),
            patch.object(er, "_close_queued_stream", AsyncMock()),
            patch.object(er, "_queue_collection_if_uncollected", AsyncMock()),
            patch.object(er, "reclaim_stranded_task", AsyncMock(return_value=None)),
            patch.object(er, "capture_event") as mock_capture,
        ):
            await run_executor_background(
                run=run, task="do the thing", configurable={"conversation_source": "web"}
            )
        return mock_capture

    async def test_pause_record_failure_labels_the_active_span_error(self) -> None:
        """Labelled error, not the pre-pause paused, to agree with the E2E/run-total labels."""
        run = _run("exec-pause-lost", t_dispatch_perf=time.perf_counter())
        error_before = _count("executor_active_seconds", {"status": "error"})
        paused_before = _count("executor_active_seconds", {"status": "paused"})

        mock_capture = await self._background(
            run,
            result=_ExecutorResult("", EXECUTOR_PAUSED, ("appr-1",)),
            record_pause=False,
        )

        assert _count("executor_active_seconds", {"status": "error"}) == error_before + 1
        assert _count("executor_active_seconds", {"status": "paused"}) == paused_before
        failed = [c for c in mock_capture.call_args_list if c.args[1] == "agent:run_failed"]
        assert len(failed) == 1

    async def test_recorded_pause_labels_the_active_span_paused(self) -> None:
        """A pause that records cleanly stays paused on the active span."""
        run = _run("exec-pause-ok", t_dispatch_perf=time.perf_counter())
        paused_before = _count("executor_active_seconds", {"status": "paused"})
        error_before = _count("executor_active_seconds", {"status": "error"})

        await self._background(
            run,
            result=_ExecutorResult("", EXECUTOR_PAUSED, ("appr-1",)),
            record_pause=True,
        )

        assert _count("executor_active_seconds", {"status": "paused"}) == paused_before + 1
        assert _count("executor_active_seconds", {"status": "error"}) == error_before

    async def test_active_histogram_agrees_with_the_active_ms_it_reports(self) -> None:
        """Recording the pause is bookkeeping I/O after the run went idle and must stretch neither."""
        run = _run("exec-slow-pause-record", t_dispatch_perf=time.perf_counter())
        sum_before = (
            REGISTRY.get_sample_value("executor_active_seconds_sum", {"status": "error"}) or 0.0
        )

        async def _slow_pause_record(*_args: Any, **_kwargs: Any) -> bool:
            await asyncio.sleep(0.3)
            return False

        mock_capture = await self._background(
            run,
            result=_ExecutorResult("", EXECUTOR_PAUSED, ("appr-1",)),
            record_pause=AsyncMock(side_effect=_slow_pause_record),
        )

        failed = [c for c in mock_capture.call_args_list if c.args[1] == "agent:run_failed"]
        active_ms = failed[0].args[2]["executor_active_ms"]
        observed_s = (
            REGISTRY.get_sample_value("executor_active_seconds_sum", {"status": "error"})
            - sum_before
        )
        assert abs(observed_s - active_ms / 1000.0) < 0.05

    async def test_queue_wait_is_labelled_by_whether_the_run_was_queued(self) -> None:
        """A live run's dispatch-to-start gap is spawn delay; a backlog would hide behind ~0s samples."""
        live_before = _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})
        queued_before = _count("executor_queue_wait_seconds", {"source": "web", "queued": "true"})

        await self._background(_run("exec-live-qw", t_dispatch_perf=time.perf_counter()))
        await self._background(
            _run(
                "exec-queued-qw",
                kind=RunKind.QUEUED,
                queued=True,
                t_dispatch_perf=time.perf_counter(),
            )
        )

        assert (
            _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})
            == live_before + 1
        )
        assert (
            _count("executor_queue_wait_seconds", {"source": "web", "queued": "true"})
            == queued_before + 1
        )

    async def test_hil_resume_is_not_labelled_queued(self) -> None:
        """A HIL resume runs on RunKind.QUEUED but never waited on the busy lock."""

        def _run_total(queued: str) -> float:
            return (
                REGISTRY.get_sample_value(
                    "executor_run_total", {"status": "success", "queued": queued}
                )
                or 0.0
            )

        resume_before = _run_total("false")
        queued_before = _run_total("true")

        await self._background(_run("exec-resume", kind=RunKind.QUEUED, queued=False))

        assert _run_total("false") == resume_before + 1
        assert _run_total("true") == queued_before

    async def test_live_run_reports_queue_wait_ttft_and_e2e(self) -> None:
        stream_id = "exec-live"
        t_dispatch = time.perf_counter()
        run = _run(stream_id, t_dispatch_perf=t_dispatch)
        active_before = _count("executor_active_seconds", {"status": "success"})
        e2e_before = _count("executor_e2e_seconds", {"status": "success", "queued": "false"})

        mock_capture = await self._background(run, first_frame_at=t_dispatch + 0.4)

        assert _count("executor_active_seconds", {"status": "success"}) == active_before + 1
        assert (
            _count("executor_e2e_seconds", {"status": "success", "queued": "false"})
            == e2e_before + 1
        )
        completed = [
            call for call in mock_capture.call_args_list if call.args[1] == "agent:run_completed"
        ]
        assert len(completed) == 1
        props = completed[0].args[2]
        assert props["queued"] is False
        assert props["queue_wait_ms"] >= 0.0
        assert props["executor_ttft_ms"] >= 400.0
        assert props["executor_active_ms"] >= 0.0

    async def test_run_without_dispatch_stamp_omits_queue_wait(self) -> None:
        """Runs predating the stamp degrade to missing timings, never zero-filled."""
        stream_id = "exec-legacy"
        run = _run(stream_id)
        mock_capture = await self._background(run)
        completed = [
            call for call in mock_capture.call_args_list if call.args[1] == "agent:run_completed"
        ]
        assert len(completed) == 1
        props = completed[0].args[2]
        assert "queue_wait_ms" not in props
        assert "executor_ttft_ms" not in props

    async def test_mixed_epoch_dispatch_stamp_measures_nothing(self) -> None:
        """A stamp from another monotonic epoch yields garbage deltas that must not be reported."""
        stream_id = "exec-restarted"
        run = _run(stream_id, t_dispatch_perf=time.perf_counter() + 3600.0)
        e2e_before = _count("executor_e2e_seconds", {"status": "success", "queued": "false"})
        mock_capture = await self._background(run)
        assert (
            _count("executor_e2e_seconds", {"status": "success", "queued": "false"}) == e2e_before
        )
        completed = [
            call for call in mock_capture.call_args_list if call.args[1] == "agent:run_completed"
        ]
        assert len(completed) == 1
        assert "queue_wait_ms" not in completed[0].args[2]


class TestQueueWaitMeasurement:
    """_queue_wait_ms in isolation: exact millis, label values, and the no-stamp and mixed-epoch guards."""

    def setup_method(self) -> None:
        sess._sessions.clear()

    def teardown_method(self) -> None:
        sess._sessions.clear()

    def test_exact_millis_are_rounded_and_observed(self) -> None:
        run = _run("qw-exact", t_dispatch_perf=0.0)
        before = _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})

        result = er._queue_wait_ms(run, 0.123456, {"conversation_source": "web"}, queued=False)

        assert result == 123.46
        assert (
            _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})
            == before + 1
        )

    def test_exactly_zero_wait_is_still_a_measurement(self) -> None:
        # Dispatch and start at the same monotonic instant: a legitimate 0.0,
        # not the mixed-epoch garbage the negative guard exists to drop.
        run = _run("qw-zero", t_dispatch_perf=5.0)
        before = _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})

        assert er._queue_wait_ms(run, 5.0, {"conversation_source": "web"}, queued=False) == 0.0
        assert (
            _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})
            == before + 1
        )

    def test_negative_delta_is_dropped(self) -> None:
        run = _run("qw-negative", t_dispatch_perf=5.0)
        before = _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"})

        assert er._queue_wait_ms(run, 4.0, {"conversation_source": "web"}, queued=False) is None
        assert _count("executor_queue_wait_seconds", {"source": "web", "queued": "false"}) == before

    def test_missing_stamp_is_dropped(self) -> None:
        run = _run("qw-unstamped")
        assert er._queue_wait_ms(run, 1.0, {"conversation_source": "web"}, queued=False) is None

    def test_missing_source_falls_back_to_unknown(self) -> None:
        run = _run("qw-unknown", t_dispatch_perf=0.0)
        before = _count("executor_queue_wait_seconds", {"source": "unknown", "queued": "true"})

        assert er._queue_wait_ms(run, 0.123456, {}, queued=True) == 123.46
        assert (
            _count("executor_queue_wait_seconds", {"source": "unknown", "queued": "true"})
            == before + 1
        )


class TestExecutorTtftMeasurement:
    """_executor_ttft_ms in isolation: exact millis, base selection, and the missing/negative guards."""

    def setup_method(self) -> None:
        sess._sessions.clear()

    def teardown_method(self) -> None:
        sess._sessions.clear()

    def test_exact_millis_from_the_dispatch_stamp(self) -> None:
        run = _run("ttft-exact", t_dispatch_perf=2.0)
        sess.create_session("ttft-exact", run.kind).executor_first_frame_perf = 2.123456

        assert er._executor_ttft_ms(run, 999.0) == 123.46

    def test_exact_millis_from_run_start_without_a_stamp(self) -> None:
        run = _run("ttft-nostamp")
        sess.create_session("ttft-nostamp", run.kind).executor_first_frame_perf = 0.123456

        assert er._executor_ttft_ms(run, 0.0) == 123.46

    def test_sub_millisecond_frame_is_kept(self) -> None:
        run = _run("ttft-sub-ms", t_dispatch_perf=2.0)
        sess.create_session("ttft-sub-ms", run.kind).executor_first_frame_perf = 2.0005

        assert er._executor_ttft_ms(run, 999.0) == 0.5

    def test_zero_delta_is_kept_not_dropped(self) -> None:
        run = _run("ttft-zero", t_dispatch_perf=2.0)
        sess.create_session("ttft-zero", run.kind).executor_first_frame_perf = 2.0

        assert er._executor_ttft_ms(run, 999.0) == 0.0

    def test_negative_delta_is_dropped(self) -> None:
        run = _run("ttft-negative", t_dispatch_perf=5.0)
        sess.create_session("ttft-negative", run.kind).executor_first_frame_perf = 4.0

        assert er._executor_ttft_ms(run, 999.0) is None

    def test_no_frame_is_none(self) -> None:
        run = _run("ttft-no-frame", t_dispatch_perf=2.0)
        sess.create_session("ttft-no-frame", run.kind)

        assert er._executor_ttft_ms(run, 999.0) is None

    def test_no_session_is_none(self) -> None:
        run = _run("ttft-no-session", t_dispatch_perf=2.0)
        assert er._executor_ttft_ms(run, 999.0) is None


class TestBackgroundRunExactWiring:
    """The background run's seams, pinned.

    The execute call's arguments, the exact timing values on both metric and log
    surfaces, the cancellation decision, and the initialization sentinels.
    """

    def setup_method(self) -> None:
        sess._sessions.clear()

    def teardown_method(self) -> None:
        sess._sessions.clear()

    @contextmanager
    def _env(
        self,
        run: ExecutorRun,
        *,
        perf_values: list[float],
        result: _ExecutorResult | None = None,
        is_cancelled: bool = False,
    ):
        """Run with the I/O boundaries mocked and the clock pinned to perf_values.

        _finalize_executor_run is patched out so the run's own metrics are the
        only ones emitted; its surface is covered by its own tests.
        """
        execute = AsyncMock(return_value=result or _ExecutorResult("done", "final"))
        is_cancelled_mock = AsyncMock(return_value=is_cancelled)
        with (
            patch.object(er, "_execute_executor", execute),
            patch.object(er, "_record_pause", AsyncMock(return_value=True)),
            patch.object(er, "_finalize_executor_run", AsyncMock()),
            patch.object(er, "_finalize_paused_run", AsyncMock()),
            patch.object(er, "_deliver_terminal_outcome", AsyncMock()),
            patch.object(er, "release_lock_if_owned", AsyncMock()),
            patch.object(er, "_close_queued_stream", AsyncMock()),
            patch.object(er, "_queue_collection_if_uncollected", AsyncMock()),
            patch.object(er, "reclaim_stranded_task", AsyncMock(return_value=None)),
            patch.object(er, "capture_event", MagicMock()),
            patch.object(er.StreamManager, "is_cancelled", is_cancelled_mock),
            patch.object(er.time, "perf_counter", side_effect=list(perf_values)),
        ):
            yield SimpleNamespace(execute=execute, is_cancelled=is_cancelled_mock)

    async def test_execute_executor_receives_the_run_arguments(self) -> None:
        run = _run("exec-args")
        configurable = {"conversation_source": "web"}
        with self._env(run, perf_values=[1000.0, 1000.0, 1000.5]) as env:
            await run_executor_background(run=run, task="the task", configurable=configurable)

        env.execute.assert_awaited_once_with("the task", configurable, "exec-args", None)

    async def test_ttft_helper_receives_the_run_and_its_start(self) -> None:
        run = _run("exec-ttft-args")
        ttft = MagicMock(return_value=None)
        with (
            self._env(run, perf_values=[1000.0, 1000.0, 1000.5]),
            patch.object(er, "_executor_ttft_ms", ttft),
        ):
            await run_executor_background(run=run, task="t", configurable={"user_id": "u1"})

        ttft.assert_called_once_with(run, 1000.0)

    async def test_ttft_histogram_and_log_payload_are_exact(self) -> None:
        run = _run("exec-ttft-exact", kind=RunKind.QUEUED, queued=True)
        sess.create_session(
            "exec-ttft-exact", RunKind.QUEUED
        ).executor_first_frame_perf = 1000.123456
        true_before = _count("executor_ttft_seconds", {"queued": "true"})
        true_sum_before = _sum("executor_ttft_seconds", {"queued": "true"})
        false_before = _count("executor_ttft_seconds", {"queued": "false"})
        mock_log = MagicMock()

        with (
            self._env(run, perf_values=[1000.0, 1000.0, 1000.123456]),
            patch.object(er, "log", mock_log),
        ):
            await run_executor_background(run=run, task="t", configurable={"user_id": "u1"})

        assert _count("executor_ttft_seconds", {"queued": "true"}) == true_before + 1
        assert (
            abs((_sum("executor_ttft_seconds", {"queued": "true"}) - true_sum_before) - 0.12346)
            < 1e-9
        )
        assert _count("executor_ttft_seconds", {"queued": "false"}) == false_before
        mock_log.set.assert_called_once_with(
            executor={
                "queued": True,
                "executor_ttft_ms": 123.46,
                "executor_active_ms": 123.46,
            }
        )

    async def test_active_histogram_uses_exact_millis(self) -> None:
        run = _run("exec-active-exact")
        before = _count("executor_active_seconds", {"status": "success"})
        sum_before = _sum("executor_active_seconds", {"status": "success"})

        with self._env(run, perf_values=[1000.0, 1000.0, 1000.123456]):
            await run_executor_background(run=run, task="t", configurable={"user_id": "u1"})

        assert _count("executor_active_seconds", {"status": "success"}) == before + 1
        assert (
            abs((_sum("executor_active_seconds", {"status": "success"}) - sum_before) - 0.12346)
            < 1e-9
        )

    async def test_cancelled_run_labels_active_span_and_reads_the_engines_stream(self) -> None:
        run = _run("exec-cancelled")
        before = _count("executor_active_seconds", {"status": "cancelled"})
        sum_before = _sum("executor_active_seconds", {"status": "cancelled"})

        with self._env(run, perf_values=[1000.0, 1000.0, 1000.123456], is_cancelled=True) as env:
            await run_executor_background(run=run, task="t", configurable={"user_id": "u1"})

        env.is_cancelled.assert_awaited_once_with("exec-cancelled")
        assert _count("executor_active_seconds", {"status": "cancelled"}) == before + 1
        assert (
            abs((_sum("executor_active_seconds", {"status": "cancelled"}) - sum_before) - 0.12346)
            < 1e-9
        )

    async def test_timing_sentinels_start_as_none(self) -> None:
        """ttft_ms and active_ms begin unset so _timing_fields omits a span that never happened."""
        run = _run("exec-sentinel")
        captured: dict[str, Any] = {}
        real_run_props = er._run_props

        def _probe(target: ExecutorRun) -> dict[str, Any]:
            frame = sys._getframe(1)
            captured["ttft_ms"] = frame.f_locals.get("ttft_ms")
            captured["active_ms"] = frame.f_locals.get("active_ms")
            return real_run_props(target)

        with (
            self._env(run, perf_values=[1000.0, 1000.0, 1000.5]),
            patch.object(er, "_run_props", _probe),
        ):
            await run_executor_background(run=run, task="t", configurable={"user_id": "u1"})

        assert captured["ttft_ms"] is None
        assert captured["active_ms"] is None


class TestCaptureExecutorTerminalWiring:
    """The terminal lifecycle event's exact payload: the user-id sentinel and dedupe key."""

    def test_an_empty_user_id_captures_nothing(self) -> None:
        run = _run("terminal-user", user=AuthenticatedUser(user_id=""))

        with patch.object(er, "capture_event") as capture:
            er._capture_executor_terminal(
                run,
                run_props={"agent": "executor"},
                queued=False,
                timing_fields={},
                result_type="final",
            )

        capture.assert_not_called()

    def test_dedupe_key_prefers_the_task_id_and_carries_exact_props(self) -> None:
        run = _run("s1", user=AuthenticatedUser(user_id="u1"), task_id="task-1")

        with patch.object(er, "capture_event") as capture:
            er._capture_executor_terminal(
                run,
                run_props={"agent": "executor"},
                queued=False,
                timing_fields={"executor_active_ms": 12.5},
                result_type="final",
            )

        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.AGENT_RUN_COMPLETED,
            {"agent": "executor", "queued": False, "executor_active_ms": 12.5},
            dedupe_key="task-1",
        )


class TestResumeForwarding:
    def setup_method(self) -> None:
        sess._sessions.clear()

    def teardown_method(self) -> None:
        sess._sessions.clear()

    async def test_the_resume_command_reaches_the_executor(self) -> None:
        """Dropping the resume Command would replay the run instead of continuing past the approval."""
        run = _run("exec-resume-forward")
        sentinel = object()
        with (
            patch.object(
                er, "_execute_executor", AsyncMock(return_value=_ExecutorResult("done", "final"))
            ) as execute,
            patch.object(er, "_record_pause", AsyncMock(return_value=True)),
            patch.object(er, "_finalize_paused_run", AsyncMock()),
            patch.object(er, "_deliver_terminal_outcome", AsyncMock()),
            patch.object(er, "release_lock_if_owned", AsyncMock()),
            patch.object(er, "_close_queued_stream", AsyncMock()),
            patch.object(er, "_queue_collection_if_uncollected", AsyncMock()),
            patch.object(er, "reclaim_stranded_task", AsyncMock(return_value=None)),
            patch.object(er, "release_resume_dispatch", AsyncMock()),
            patch.object(er, "capture_event"),
        ):
            await run_executor_background(
                run=run,
                task="do the thing",
                configurable={"conversation_source": "web"},
                resume=sentinel,  # type: ignore[arg-type] -- sentinel object proves forwarding by identity; intentionally not a Command
            )

        assert execute.await_args.args[3] is sentinel
