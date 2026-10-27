"""The tracked-todo executor entry: failure paths, the todo-chat stream it owns, the thread reset.

The happy path runs end to end in the wiring test (test_tracked_todo_run_delivery).
"""

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import session as sess, todo_run
from app.agents.core.background.session import TodoRun, executor_abandoned
from app.agents.core.background.todo_run import (
    TodoRunFailedError,
    TodoRunRequest,
    _todo_run_configurable,
    run_todo_on_executor,
)
from app.agents.llm.lane import AgentRole
from app.constants.streaming import DetachedStreamKind
from app.models.user_models import AuthenticatedUser, OnboardingSubdocument
from app.models.workflow_models import TriggerType
from app.services.checkpoint_thread_reset import ThreadReset

pytestmark = pytest.mark.unit

REQUEST = TodoRunRequest(
    user=AuthenticatedUser(user_id="user-1"),
    todo_run=TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO),
    todo_title="Watch the deploy",
    task="Execute the following scheduled task: Watch the deploy",
    conversation_id="run-conv",
    fresh_thread=False,
)


@pytest.fixture(autouse=True)
def _clean_sessions() -> Iterator[None]:
    yield
    sess._sessions.clear()


class _Seams:
    """The Redis/Postgres seams around a run, each a mock recording into one shared order."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.announce = AsyncMock(side_effect=lambda *a, **k: order.append("announce"))
        self.end = AsyncMock(side_effect=lambda *a, **k: order.append("end"))
        self.reset = AsyncMock(
            side_effect=lambda *a, **k: order.append("reset") or ThreadReset(2, 0)
        )
        self.release = AsyncMock()
        self.stream_manager = MagicMock()
        self.stream_manager.is_cancelled = AsyncMock(return_value=False)


@pytest.fixture
def seams() -> Iterator[_Seams]:
    found = _Seams([])
    with ExitStack() as stack:
        stack.enter_context(patch.object(todo_run, "announce_detached_stream", found.announce))
        stack.enter_context(patch.object(todo_run, "end_detached_stream", found.end))
        stack.enter_context(patch.object(todo_run, "reset_conversation_threads", found.reset))
        stack.enter_context(patch.object(todo_run, "release_lock_if_owned", found.release))
        stack.enter_context(patch.object(todo_run, "StreamManager", found.stream_manager))
        stack.enter_context(
            patch.object(
                todo_run,
                "_todo_run_configurable",
                AsyncMock(return_value={"user_id": "user-1", "stream_id": "s"}),
            )
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
        pytest.raises(TodoRunFailedError, match="already running in conversation run-conv"),
    ):
        await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

    spawned.assert_not_called()
    # Refused before the lock was ever its own: another run's threads are left alone.
    seams.reset.assert_not_awaited()
    seams.announce.assert_not_awaited()


async def test_a_run_that_never_finishes_is_stopped_before_the_attempt_fails(
    seams: _Seams,
) -> None:
    """Regression: a run left going past its wait kept calling tools while the worker's retry ran the todo again."""
    stream_ids: list[str] = []
    abandoned_when_stopped: list[bool] = []

    async def stall(*, run, task, configurable) -> None:
        stream_ids.append(run.stream_id)
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

    # Stopped before the attempt failed, and marked abandoned first so its finalize delivers nothing.
    assert abandoned_when_stopped == [True]
    assert len(stream_ids) == 1
    # The chat's live view still closes, or its placeholder spins until the client gives up.
    seams.end.assert_awaited_once_with(stream_ids[0], cancelled=False)


class TestTheStreamInTheTodosChat:
    async def test_the_run_streams_into_its_todos_chat_and_closes_after_delivery(
        self, seams: _Seams
    ) -> None:
        run = _recording_run(seams.order)
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", run),
        ):
            await run_todo_on_executor(REQUEST)

        # Ended only once the run (delivery included) is over: a client reading the
        # chat at [DONE] must find the report already saved.
        assert seams.order == ["announce", "run", "end"]
        dispatched = run.await_args.kwargs["run"]
        announced = seams.announce.await_args
        assert announced.args == (dispatched.stream_id,)
        assert announced.kwargs == {
            "conversation_id": "run-conv",
            "user_id": "user-1",
            "task_id": dispatched.task_id,
            "bot_message_id": None,
            "kind": DetachedStreamKind.EXECUTOR,
        }
        # The placeholder the client opens is keyed by task_id; the frames and the
        # saved report must land on that same message.
        assert dispatched.render_message_id == dispatched.task_id
        assert dispatched.executor_owns_tool_data is True

    async def test_a_stream_the_user_stopped_closes_silently(self, seams: _Seams) -> None:
        seams.stream_manager.is_cancelled = AsyncMock(return_value=True)
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", AsyncMock()),
        ):
            await run_todo_on_executor(REQUEST)

        assert seams.end.await_args.kwargs == {"cancelled": True}

    async def test_a_failed_announce_frees_the_lock_and_runs_nothing(self, seams: _Seams) -> None:
        """Regression guard: the lock is taken before any run owns it, so nothing else would free it."""
        seams.announce.side_effect = RuntimeError("redis is down")
        spawned = AsyncMock()
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", spawned),
            pytest.raises(RuntimeError, match="redis is down"),
        ):
            await run_todo_on_executor(REQUEST)

        spawned.assert_not_called()
        conversation_id, stream_id, task_id = seams.release.await_args.args
        assert conversation_id == "run-conv"
        assert stream_id and task_id
        seams.end.assert_not_awaited()


class TestTheExecutorThreadReset:
    async def test_a_new_run_starts_from_an_empty_executor_thread_keeping_the_chats_own(
        self, seams: _Seams
    ) -> None:
        run = _recording_run(seams.order)
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", run),
        ):
            await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

        seams.reset.assert_awaited_once_with("run-conv", keep_conversation_thread=True)
        assert seams.order.index("reset") < seams.order.index("run")

    async def test_an_approval_resume_continues_the_thread_it_parked(self, seams: _Seams) -> None:
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", AsyncMock()),
        ):
            await run_todo_on_executor(REQUEST)

        seams.reset.assert_not_awaited()

    async def test_a_failed_reset_is_reported_and_the_run_goes_ahead(self, seams: _Seams) -> None:
        seams.reset.side_effect = RuntimeError("postgres is down")
        run = AsyncMock()
        with (
            patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
            patch.object(todo_run, "run_executor_background", run),
            patch.object(todo_run, "log") as log,
        ):
            await run_todo_on_executor(replace(REQUEST, fresh_thread=True))

        run.assert_awaited_once()
        assert "reset failed" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["error"] == "postgres is down"
        assert log.warning.call_args.kwargs["conversation_id"] == "run-conv"


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

    assert configurable == {"thread_id": "run-conv", "stream_id": "stream-1"}
    kwargs = built.await_args.kwargs
    assert kwargs["identity"].conversation_id == "run-conv"
    assert kwargs["identity"].agent_name == "executor_agent"
    assert kwargs["identity"].user["user_id"] == "user-1"
    assert kwargs["lane"].role is AgentRole.EXECUTOR
    turn = kwargs["turn"]
    assert (turn.active_todo_id, turn.execution_mode) == ("todo-1", "background")
    assert turn.user_messages == ["Tracked todo: Watch the deploy"]
    assert turn.user_preferences == {"profession": "engineer"}
    assert turn.writing_style == {"summary": "terse"}
