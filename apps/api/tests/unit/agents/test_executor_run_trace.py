"""Every executor run opens its trace when it starts and closes it in the state it ended in."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import executor_runner as er
from app.agents.core.background.session import ExecutorRun, RunKind
from app.models.run_trace_models import RunState
from app.models.user_models import AuthenticatedUser
from app.services.executor_trace.recorder import RunOwner

USER_ID = "6812f0b3c9a14e2b7d5a91cc"


def _run(*, user_id: str = USER_ID, active_todo_id: str | None = None) -> ExecutorRun:
    return ExecutorRun(
        stream_id="stream-1",
        conversation_id="conv-1",
        user=AuthenticatedUser(user_id=user_id),
        kind=RunKind.LIVE,
        task_id="task-1",
        user_message_id=None,
        active_todo_id=active_todo_id,
    )


@pytest.fixture
def trace() -> Iterator[SimpleNamespace]:
    with (
        patch.object(er, "begin_run", new_callable=AsyncMock) as begin,
        patch.object(er, "end_run", new_callable=AsyncMock) as end,
        patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
    ):
        yield SimpleNamespace(begin=begin, end=end)


async def _drive(run: ExecutorRun, outcome: er._ExecutorResult | BaseException) -> None:
    execute = (
        AsyncMock(side_effect=outcome)
        if isinstance(outcome, BaseException)
        else AsyncMock(return_value=outcome)
    )
    with patch.object(er, "_execute_executor", execute):
        await er.run_executor_background(run, "do the thing", {"user_id": run.user.user_id})


async def test_a_run_for_a_tracked_todo_opens_and_closes_its_trace_against_that_todo(
    trace: SimpleNamespace,
) -> None:
    await _drive(_run(active_todo_id="todo-1"), er._ExecutorResult("done", "final"))

    owner = RunOwner(user_id=USER_ID, conversation_id="conv-1", run_id="stream-1", todo_id="todo-1")
    trace.begin.assert_awaited_once_with(owner)
    trace.end.assert_awaited_once_with(owner, RunState.FINISHED)


async def test_a_run_started_from_comms_is_traced_with_no_todo(trace: SimpleNamespace) -> None:
    await _drive(_run(), er._ExecutorResult("done", "final"))

    (owner,) = trace.begin.await_args.args
    assert owner.todo_id is None


async def test_a_run_that_fails_closes_its_trace_failed(trace: SimpleNamespace) -> None:
    await _drive(_run(), er._ExecutorResult("boom", "error"))

    assert trace.end.await_args.args[1] is RunState.FAILED


async def test_a_run_cancelled_before_it_has_a_result_closes_its_trace_cancelled(
    trace: SimpleNamespace,
) -> None:
    with pytest.raises(asyncio.CancelledError):
        await _drive(_run(), asyncio.CancelledError())

    assert trace.end.await_args.args[1] is RunState.CANCELLED


async def test_a_run_with_no_user_has_no_trace_to_key_it_by(trace: SimpleNamespace) -> None:
    await _drive(_run(user_id=""), er._ExecutorResult("done", "final"))

    trace.begin.assert_not_awaited()
    trace.end.assert_not_awaited()
