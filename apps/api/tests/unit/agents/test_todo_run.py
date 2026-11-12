"""The tracked-todo executor entry: its lock, the wake it logs, how its outcome is read, the thread reset.

The run through the step and delivery runs end to end in
tests/integration/real/test_conversation_runtime_real.py.
"""

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import session as sess, todo_run
from app.agents.core.background.session import executor_abandoned
from app.agents.core.background.todo_run import (
    ExecutorBusyError,
    TodoRunCancelledError,
    TodoRunFailedError,
    TodoRunRequest,
    _finished_run,
    _todo_run_configurable,
    run_todo_on_executor,
)
from app.agents.llm.lane import AgentRole
from app.constants.log_tags import LogTag
from app.db.repositories.conversation_log import EMPTY_LOG_STATE
from app.models.conversation_log_models import (
    ConversationState,
    LiveWork,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    TodoReportForm,
    TodoWoke,
    WorkFinished,
    WorkOutcome,
)
from app.models.user_models import AuthenticatedUser, OnboardingSubdocument
from app.services.checkpoint_thread_reset import ThreadReset
from app.services.conversation.outcome import EntryOutcome
from tests.unit.services.conversation.log_helpers import todo_run as typed_todo_run

pytestmark = pytest.mark.unit

RUN = typed_todo_run()
REQUEST = TodoRunRequest(
    user=AuthenticatedUser(user_id="user-1"),
    todo_run=RUN,
    task="Execute the following scheduled task: Watch the Acme thread",
    conversation_id="run-conv",
    fresh_thread=False,
)
WOKE = LoggedEntry(seq=3, at=datetime.now(UTC), entry=TodoWoke(id="todo:run_1", run=RUN))


def _done(task_id: str, *, reply: ReplyOutcome = ReplyOutcome.ANSWERED) -> EntryOutcome:
    settled = ReplySettled(
        id="a:settled",
        reply_id=task_id,
        outcome=reply,
        answers=("todo:run_1",),
        through=4,
        quote_target=None,
    )
    finished = WorkFinished(
        id=f"work:{task_id}:finished", task_id=task_id, outcome=WorkOutcome.DONE, report="report"
    )
    shown = Reply(id="a:reply", reply_id=task_id, attempt_id="a", text="written up")
    return EntryOutcome(settled=settled, reply=shown, work=(finished,))


@pytest.fixture(autouse=True)
def _clean_sessions() -> Iterator[None]:
    yield
    sess._sessions.clear()


class _Seams:
    """The Redis/Postgres/log seams around a run, each a mock recording into one shared order."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.reset = AsyncMock(side_effect=self._reset)
        self.release = AsyncMock()
        self.wake = AsyncMock(side_effect=self._wake)
        self.state = AsyncMock(return_value=EMPTY_LOG_STATE)
        self.outcome = AsyncMock(side_effect=self._outcome)
        self.finish = AsyncMock(return_value=None)
        self.task_ids: list[str] = []

    def _reset(self, *_args: object, **_kwargs: object) -> ThreadReset:
        self.order.append("reset")
        return ThreadReset(2, 0)

    def _wake(self, _request: TodoRunRequest, task_id: str) -> LoggedEntry:
        self.order.append("wake")
        self.task_ids.append(task_id)
        return WOKE

    def _outcome(self, *_args: object) -> EntryOutcome:
        return _done(self.task_ids[-1])


@pytest.fixture
def seams() -> Iterator[_Seams]:
    found = _Seams([])
    ports = SimpleNamespace(log=SimpleNamespace(state=found.state))
    configurable = {"user_id": "user-1", "stream_id": "s", "work_on_log": True}
    with ExitStack() as stack:
        stack.enter_context(patch.object(todo_run, "reset_conversation_threads", found.reset))
        stack.enter_context(patch.object(todo_run, "release_lock_if_owned", found.release))
        stack.enter_context(patch.object(todo_run, "_log_the_wake", found.wake))
        stack.enter_context(patch.object(todo_run, "runtime_ports", lambda: ports))
        stack.enter_context(patch.object(todo_run, "await_outcome", found.outcome))
        stack.enter_context(patch.object(todo_run, "finish_todo_run", found.finish))
        stack.enter_context(
            patch.object(todo_run, "_todo_run_configurable", AsyncMock(return_value=configurable))
        )
        yield found


def _recording_run(order: list[str]) -> AsyncMock:
    return AsyncMock(side_effect=lambda **_: order.append("run"))


async def test_a_conversation_already_running_the_executor_is_refused_before_spawning(
    seams: _Seams,
) -> None:
    spawned = AsyncMock()
    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=False)),
        patch.object(todo_run, "run_executor_background", spawned),
        pytest.raises(ExecutorBusyError, match="already running in conversation run-conv"),
    ):
        await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

    spawned.assert_not_called()
    # Refused before the lock was ever its own: another run's threads and the log are left alone.
    seams.reset.assert_not_awaited()
    seams.wake.assert_not_awaited()


async def test_the_run_is_logged_as_started_only_once_the_chat_is_its_own(seams: _Seams) -> None:
    started = AsyncMock(side_effect=lambda: seams.order.append("started"))
    run = _recording_run(seams.order)
    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
        patch.object(todo_run, "run_executor_background", run),
    ):
        await run_todo_on_executor(replace(REQUEST, on_started=started))

    assert seams.order == ["started", "wake", "run"]
    dispatched = run.await_args.kwargs["run"]
    assert dispatched.task_id == seams.task_ids[0]
    finished, user = seams.finish.await_args.args
    assert (finished.run_id, finished.write_up, finished.result_text) == (
        "run_1",
        "written up",
        "report",
    )
    assert user is REQUEST.user


async def test_a_wake_the_log_refuses_frees_the_lock_and_runs_nothing(seams: _Seams) -> None:
    """Regression guard: the lock is taken before any run owns it, so nothing else would free it."""
    seams.wake.side_effect = TodoRunCancelledError("a Stop came first")
    spawned = AsyncMock()
    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
        patch.object(todo_run, "run_executor_background", spawned),
        pytest.raises(TodoRunCancelledError, match="a Stop came first"),
    ):
        await run_todo_on_executor(REQUEST)

    spawned.assert_not_called()
    conversation_id, stream_id, task_id = seams.release.await_args.args
    assert conversation_id == "run-conv"
    assert stream_id and task_id


async def test_a_run_parked_on_an_approval_delivers_nothing_yet(seams: _Seams) -> None:
    def parked(*_args: object) -> ConversationState:
        work = LiveWork(
            task_id=seams.task_ids[-1],
            cause_through=3,
            answers=("todo:run_1",),
            pending_approvals=frozenset({"a1"}),
        )
        return EMPTY_LOG_STATE.model_copy(update={"work": (work,)})

    seams.state.side_effect = parked
    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
        patch.object(todo_run, "run_executor_background", AsyncMock()),
    ):
        await run_todo_on_executor(REQUEST)

    seams.outcome.assert_not_awaited()
    seams.finish.assert_not_awaited()


async def test_a_run_that_never_finishes_is_stopped_before_the_attempt_fails(
    seams: _Seams,
) -> None:
    """Regression: a run left going past its wait kept calling tools while the worker's retry ran the todo again."""
    abandoned_when_stopped: list[bool] = []

    async def stall(*, run, task, configurable) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            abandoned_when_stopped.append(executor_abandoned(run.stream_id))

    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
        patch.object(todo_run, "run_executor_background", stall),
        patch.object(todo_run, "BACKGROUND_EXECUTOR_WAIT_TIMEOUT", 0.01),
        pytest.raises(TodoRunFailedError, match="did not finish"),
    ):
        await run_todo_on_executor(REQUEST)

    # Stopped before the attempt failed, and marked abandoned first so its finalize logs nothing.
    assert abandoned_when_stopped == [True]
    seams.finish.assert_not_awaited()


class TestWhatTheRunsReplySettledTo:
    def test_a_written_up_run_is_handed_on_with_its_report_and_its_write_up(self) -> None:
        finished = _finished_run(REQUEST, "t1", _done("t1"))
        assert (finished.reply, finished.write_up, finished.result_text) == (
            ReplyOutcome.ANSWERED,
            "written up",
            "report",
        )
        assert finished.report_form is TodoReportForm.WRITE_UP

    def test_a_silent_write_up_is_handed_on_as_silent(self) -> None:
        finished = _finished_run(REQUEST, "t1", _done("t1", reply=ReplyOutcome.SILENT))
        assert finished.reply is ReplyOutcome.SILENT

    def test_a_run_a_stop_dropped_before_any_reply_is_reported_stopped(self) -> None:
        """Regression: a stopped run returned as if it finished, so the worker moved on as a success."""
        with pytest.raises(TodoRunCancelledError, match="stopped the run in conversation run-conv"):
            _finished_run(REQUEST, "t1", EntryOutcome(settled=None, reply=None, work=()))

    def test_a_run_whose_write_up_was_stopped_is_reported_stopped(self) -> None:
        done = _done("t1")
        assert done.settled is not None
        stopped = done.settled.model_copy(update={"outcome": ReplyOutcome.STOPPED})
        with pytest.raises(TodoRunCancelledError):
            _finished_run(REQUEST, "t1", EntryOutcome(stopped, done.reply, done.work))

    @pytest.mark.parametrize("ended", [WorkOutcome.FAILED, WorkOutcome.LOST])
    def test_work_that_did_not_finish_fails_the_run_with_its_report(
        self, ended: WorkOutcome
    ) -> None:
        done = _done("t1")
        failed = done.work[0].model_copy(update={"outcome": ended, "report": "the inbox timed out"})
        with pytest.raises(TodoRunFailedError, match="the inbox timed out"):
            _finished_run(REQUEST, "t1", EntryOutcome(done.settled, done.reply, (failed,)))


class TestTheExecutorThreadReset:
    async def test_a_new_run_starts_from_an_empty_executor_thread_keeping_the_chats_own(
        self, seams: _Seams
    ) -> None:
        run = _recording_run(seams.order)
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", run),
            patch.object(todo_run, "log") as log,
        ):
            await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

        seams.reset.assert_awaited_once_with("run-conv", keep_conversation_thread=True)
        assert seams.order.index("reset") < seams.order.index("run")
        log.set_ns.assert_any_call("tracked_todo", threads_reset=2, threads_skipped_inflight=0)
        log.warning.assert_not_called()

    async def test_with_no_checkpointer_the_reset_is_skipped_loudly(self, seams: _Seams) -> None:
        """A dev box has no Postgres checkpointer, so there is no persisted thread to replay."""
        seams.reset.side_effect = None
        seams.reset.return_value = None
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", AsyncMock()),
            patch.object(todo_run, "log") as log,
        ):
            await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

        log.warning.assert_called_once_with(
            f"{LogTag.TODO} Todo chat executor-thread reset skipped — no checkpointer pool",
            conversation_id="run-conv",
        )

    async def test_an_approval_resume_continues_the_thread_it_parked(self, seams: _Seams) -> None:
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", AsyncMock()),
        ):
            await run_todo_on_executor(REQUEST)

        seams.reset.assert_not_awaited()

    async def test_a_failed_reset_fails_the_run_before_it_starts_and_frees_the_lock(
        self, seams: _Seams
    ) -> None:
        """Regression: a failed reset was only logged, so the run quietly replayed the previous run's thread."""
        seams.reset.side_effect = RuntimeError("postgres is down")
        run = AsyncMock()
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", run),
            pytest.raises(RuntimeError, match="postgres is down"),
        ):
            await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

        run.assert_not_called()
        seams.wake.assert_not_awaited()
        assert seams.release.await_args.args[0] == "run-conv"


async def test_the_executor_config_is_a_background_run_bound_to_the_todo() -> None:
    """What a comms turn would have handed the executor, built without one."""
    user = AuthenticatedUser(
        user_id="user-1",
        email="u@gaia.local",
        onboarding=OnboardingSubdocument.model_validate(
            {"preferences": {"profession": "engineer"}, "writing_style": {"summary": "terse"}}
        ),
    )
    request = replace(REQUEST, user=user, task="brief")
    built = AsyncMock(return_value={"configurable": {"thread_id": "run-conv"}})
    with patch.object(todo_run, "build_agent_config", built):
        configurable = await _todo_run_configurable(request, "stream-1")

    assert configurable == {
        "thread_id": "run-conv",
        "stream_id": "stream-1",
        "work_on_log": True,
    }
    kwargs = built.await_args.kwargs
    assert kwargs["identity"].conversation_id == "run-conv"
    assert kwargs["identity"].agent_name == "executor_agent"
    assert kwargs["identity"].user["user_id"] == "user-1"
    assert kwargs["lane"].role is AgentRole.EXECUTOR
    turn = kwargs["turn"]
    assert (turn.active_todo_id, turn.execution_mode) == ("todo_1", "background")
    assert turn.user_messages == ["Tracked todo: Watch the Acme thread"]
    assert turn.user_preferences == {"profession": "engineer"}
    assert turn.writing_style == {"summary": "terse"}
