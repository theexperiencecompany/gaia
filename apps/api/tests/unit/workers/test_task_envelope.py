"""Unit tests for the ``arq_task`` observability envelope.

``arq_task`` is applied at import time in ``app.worker``, so the worker
registry smoke test never re-runs the decorator itself. These tests apply it
per test and drive the wrapped coroutine: the envelope's contract (ctx
handling, trace-id propagation, the wide-event fields, the Prometheus
outcome) is only provable by actually calling a freshly wrapped task.
"""

from typing import Any

import pytest

from app.workers.metrics import REGISTRY
from app.workers.queue import TRACE_ID_KWARG
from app.workers.task_envelope import arq_task
from shared.py.wide_events import get_trace_id, log


def _sample(metric: str, task_name: str, status: str) -> float:
    """A worker metric's current value, as Prometheus would scrape it."""
    value = REGISTRY.get_sample_value(metric, {"task_name": task_name, "status": status})
    return 0.0 if value is None else float(value)


def _task_count(task_name: str, status: str) -> float:
    return _sample("arq_task_total", task_name, status)


def _duration_count(task_name: str, status: str) -> float:
    return _sample("arq_task_duration_seconds_count", task_name, status)


class TestTaskBodyInvocation:
    async def test_returns_the_task_result_and_forwards_args(self) -> None:
        @arq_task
        async def echo(ctx: dict[str, Any], value: str, *, upper: bool = False) -> str:
            return value.upper() if upper else value

        assert await echo({}, "hello") == "hello"
        assert await echo({}, "hello", upper=True) == "HELLO"

    async def test_a_bare_ctx_is_the_only_positional_argument_arq_guarantees(self) -> None:
        """ARQ calls ``task(ctx)``; reading any other positional would blow up here."""

        @arq_task
        async def bare(ctx: dict[str, Any]) -> str:
            return "ran"

        assert await bare({"job_id": "j1"}) == "ran"

    async def test_task_exceptions_propagate_to_arq(self) -> None:
        @arq_task
        async def boom(ctx: dict[str, Any]) -> None:
            raise RuntimeError("task blew up")

        with pytest.raises(RuntimeError, match="task blew up"):
            await boom({})

    async def test_preserves_the_name_arq_registers_the_task_under(self) -> None:
        @arq_task
        async def named_task(ctx: dict[str, Any]) -> None:
            return None

        assert named_task.__name__ == "named_task"


class TestTraceIdPropagation:
    async def test_the_enqueuers_trace_id_becomes_the_tasks_trace_id(self) -> None:
        seen: list[str] = []

        @arq_task
        async def observe(ctx: dict[str, Any]) -> None:
            seen.append(get_trace_id())

        await observe({}, **{TRACE_ID_KWARG: "trace-from-enqueuer"})

        assert seen == ["trace-from-enqueuer"]

    async def test_the_trace_kwarg_never_reaches_the_task_body(self) -> None:
        """It is envelope transport; a task signature must not have to accept it."""
        received: list[dict[str, Any]] = []

        @arq_task
        async def strict(ctx: dict[str, Any], **kwargs: Any) -> None:
            received.append(kwargs)

        await strict({}, keep="me", **{TRACE_ID_KWARG: "t1"})

        assert received == [{"keep": "me"}]

    async def test_a_task_enqueued_without_a_trace_id_still_gets_one(self) -> None:
        seen: list[str] = []

        @arq_task
        async def observe(ctx: dict[str, Any]) -> None:
            seen.append(get_trace_id())

        await observe({})

        assert seen[0]


class TestWideEventFields:
    async def test_job_id_and_job_try_land_on_the_worker_event(self) -> None:
        captured: list[dict[str, object]] = []

        @arq_task
        async def retried(ctx: dict[str, Any]) -> None:
            captured.append(log.get())

        await retried({"job_id": "job-7", "job_try": 3})

        assert captured[0]["job_id"] == "job-7"
        assert captured[0]["job_try"] == 3

    async def test_absent_job_keys_are_omitted_rather_than_nulled(self) -> None:
        captured: list[dict[str, object]] = []

        @arq_task
        async def direct(ctx: dict[str, Any]) -> None:
            captured.append(log.get())

        await direct({})

        assert "job_id" not in captured[0]
        assert "job_try" not in captured[0]

    async def test_unrelated_ctx_keys_do_not_leak_onto_the_event(self) -> None:
        captured: list[dict[str, object]] = []

        @arq_task
        async def noisy(ctx: dict[str, Any]) -> None:
            captured.append(log.get())

        await noisy({"job_id": "j", "redis": object(), "score": 1})

        assert "redis" not in captured[0]
        assert "score" not in captured[0]

    async def test_the_event_is_named_after_the_task(self) -> None:
        captured: list[dict[str, object]] = []

        @arq_task
        async def sweep_something(ctx: dict[str, Any]) -> None:
            captured.append(log.get())

        await sweep_something({})

        assert captured[0]["task"] == "sweep_something"


class TestMetrics:
    async def test_a_successful_task_is_counted_as_success(self) -> None:
        @arq_task
        async def metric_success(ctx: dict[str, Any]) -> str:
            return "ok"

        before = _task_count("metric_success", "success")
        await metric_success({})

        assert _task_count("metric_success", "success") == before + 1

    async def test_a_failing_task_is_counted_as_error_not_success(self) -> None:
        @arq_task
        async def metric_error(ctx: dict[str, Any]) -> None:
            raise ValueError("nope")

        before = _task_count("metric_error", "error")
        with pytest.raises(ValueError):
            await metric_error({})

        assert _task_count("metric_error", "error") == before + 1
        assert _task_count("metric_error", "success") == 0

    async def test_duration_is_observed_for_both_outcomes(self) -> None:
        @arq_task
        async def timed(ctx: dict[str, Any], *, fail: bool) -> None:
            if fail:
                raise ValueError("nope")

        before_success = _duration_count("timed", "success")
        before_error = _duration_count("timed", "error")

        await timed({}, fail=False)
        with pytest.raises(ValueError):
            await timed({}, fail=True)

        assert _duration_count("timed", "success") == before_success + 1
        assert _duration_count("timed", "error") == before_error + 1
