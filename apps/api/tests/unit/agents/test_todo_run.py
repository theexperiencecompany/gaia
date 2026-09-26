"""The tracked-todo executor entry's failure paths; the happy path runs in the wiring test."""

import asyncio
from unittest.mock import AsyncMock, patch

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
from app.models.user_models import AuthenticatedUser, OnboardingSubdocument
from app.models.workflow_models import TriggerType

pytestmark = pytest.mark.unit

REQUEST = TodoRunRequest(
    user=AuthenticatedUser(user_id="user-1"),
    todo_run=TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO),
    todo_title="Watch the deploy",
    task="Execute the following scheduled task: Watch the deploy",
    conversation_id="run-conv",
)


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    sess._sessions.clear()


async def test_a_conversation_already_running_the_executor_is_refused_before_spawning() -> None:
    spawned = AsyncMock()
    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=False)),
        patch.object(todo_run, "run_executor_background", spawned),
        pytest.raises(TodoRunFailedError, match="already running in conversation run-conv"),
    ):
        await run_todo_on_executor(REQUEST)

    spawned.assert_not_called()


async def test_a_run_that_never_finishes_is_abandoned_and_fails_the_attempt() -> None:
    """Abandoned so its late finalize delivers nothing while the worker's retry runs."""
    stream_ids: list[str] = []
    never = asyncio.Event()

    async def stall(*, run, task, configurable) -> None:
        stream_ids.append(run.stream_id)
        await never.wait()

    with (
        patch.object(todo_run, "try_acquire_lock", AsyncMock(return_value=True)),
        patch.object(todo_run, "run_executor_background", stall),
        patch.object(todo_run, "BACKGROUND_EXECUTOR_WAIT_TIMEOUT", 0.01),
        pytest.raises(TodoRunFailedError, match="did not finish"),
    ):
        await run_todo_on_executor(REQUEST)

    (stream_id,) = stream_ids
    assert executor_abandoned(stream_id)
    never.set()


async def test_the_executor_config_is_a_background_run_bound_to_the_todo() -> None:
    """What a comms turn would have handed the executor, built without one."""
    user = AuthenticatedUser(
        user_id="user-1",
        email="u@gaia.local",
        onboarding=OnboardingSubdocument.model_validate(
            {"preferences": {"profession": "engineer"}, "writing_style": {"summary": "terse"}}
        ),
    )
    request = TodoRunRequest(
        user=user,
        todo_run=TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO),
        todo_title="Watch the deploy",
        task="brief",
        conversation_id="run-conv",
    )
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
