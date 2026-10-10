"""The ARQ task envelope's deadline: a job cut off at its time limit says so.

ARQ enforces a job timeout by cancelling the task, which a wide-event boundary
records as a clean cancel. The envelope owns each task's deadline so the
cut-off reads as a failure with reason task_timeout, and ARQ's own timeout
sits past it as a backstop only.
"""

import asyncio
from collections.abc import Mapping
from unittest.mock import patch

import pytest

from app.workers.config.worker_settings import ARQ_BACKSTOP_GRACE_SECONDS
from app.workers.queue import TRACE_ID_KWARG
from app.workers.task_envelope import arq_function, arq_task
from tests.helpers import WideEventRecorder

pytestmark = pytest.mark.unit


async def _outlives_its_deadline(ctx: Mapping[str, object]) -> str:
    await asyncio.sleep(60)
    return "finished"


async def _raises_its_own_timeout(ctx: Mapping[str, object]) -> str:
    raise TimeoutError("upstream read timed out")


async def test_a_task_cut_off_at_its_deadline_fails_with_reason_task_timeout() -> None:
    recorder = WideEventRecorder()
    wrapped = arq_task(_outlives_its_deadline, timeout_seconds=0.01)
    with (
        patch("shared.py.wide_events._loguru", recorder),
        pytest.raises(TimeoutError),
    ):
        await wrapped({"job_id": "j1", "job_try": 1})

    event = recorder.event("_outlives_its_deadline")
    assert event["outcome"] == "failed"
    assert event["reason"] == "task_timeout"
    assert event["timeout_seconds"] == 0.01


async def test_the_task_body_still_cleans_up_when_its_deadline_cuts_it_off() -> None:
    cleaned_up: list[bool] = []

    async def _holds_a_slot(ctx: Mapping[str, object]) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cleaned_up.append(True)
            raise

    with (
        patch("shared.py.wide_events._loguru", WideEventRecorder()),
        pytest.raises(TimeoutError),
    ):
        await arq_task(_holds_a_slot, timeout_seconds=0.01)({})

    assert cleaned_up == [True]


async def test_a_timeout_the_task_raised_itself_is_not_the_deadline() -> None:
    recorder = WideEventRecorder()
    with (
        patch("shared.py.wide_events._loguru", recorder),
        pytest.raises(TimeoutError),
    ):
        await arq_task(_raises_its_own_timeout, timeout_seconds=60)({})

    event = recorder.event("_raises_its_own_timeout")
    assert event["outcome"] == "failed"
    assert "reason" not in event


def test_a_task_registered_with_its_own_deadline_gets_arqs_backstop_past_it() -> None:
    registered = arq_function(_outlives_its_deadline, name="slow_job", timeout_seconds=7200)

    assert registered.name == "slow_job"
    assert registered.timeout_s == 7200 + ARQ_BACKSTOP_GRACE_SECONDS


async def test_the_task_body_gets_arqs_ctx_and_the_jobs_own_arguments() -> None:
    received: list[tuple[Mapping[str, object], tuple[object, ...], dict[str, object]]] = []

    async def _records_its_call(ctx: Mapping[str, object], *args: object, **kwargs: object) -> str:
        received.append((ctx, args, kwargs))
        return "done"

    ctx = {"job_id": "j1", "job_try": 1, "redis": object()}
    with patch("shared.py.wide_events._loguru", WideEventRecorder()):
        result = await arq_task(_records_its_call)(ctx, "user-1", limit=5)

    assert result == "done"
    assert received == [(ctx, ("user-1",), {"limit": 5})]


async def test_the_propagated_trace_id_joins_the_event_and_never_reaches_the_task() -> None:
    """enqueue_worker_job appends the trace id to the job's kwargs; a task body that saw it would crash on an unexpected keyword."""
    received: list[dict[str, object]] = []

    async def _takes_no_trace_id(ctx: Mapping[str, object], **kwargs: object) -> None:
        received.append(kwargs)

    recorder = WideEventRecorder()
    with patch("shared.py.wide_events._loguru", recorder):
        await arq_task(_takes_no_trace_id)({}, user_id="u1", **{TRACE_ID_KWARG: "trace-abc"})

    assert received == [{"user_id": "u1"}]
    assert recorder.event("_takes_no_trace_id")["trace_id"] == "trace-abc"


async def test_a_task_registered_with_its_own_deadline_is_cut_off_at_that_deadline() -> None:
    """Not at the default one: the envelope and ARQ's backstop must read the same number."""

    async def _outlives_a_zero_deadline(ctx: Mapping[str, object]) -> str:
        await asyncio.sleep(1)
        return "finished"

    registered = arq_function(_outlives_a_zero_deadline, name="instant_job", timeout_seconds=0)
    recorder = WideEventRecorder()
    with (
        patch("shared.py.wide_events._loguru", recorder),
        pytest.raises(TimeoutError),
    ):
        await registered.coroutine({})

    assert recorder.event("_outlives_a_zero_deadline")["reason"] == "task_timeout"


def test_a_registered_tasks_retry_and_result_policy_reach_arq() -> None:
    """A non-idempotent task registered with max_tries=1 must not be retried by ARQ's default of five."""
    registered = arq_function(
        _outlives_its_deadline, name="once_job", timeout_seconds=60, max_tries=1, keep_result=0
    )

    assert registered.max_tries == 1
    assert registered.keep_result_s == 0
