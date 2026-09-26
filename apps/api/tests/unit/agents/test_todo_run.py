"""The tracked-todo executor entry's failure paths; the happy path runs in the wiring test."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import session as sess, todo_run
from app.agents.core.background.session import TodoRun, executor_abandoned
from app.agents.core.background.todo_run import (
    TodoRunFailedError,
    TodoRunRequest,
    run_todo_on_executor,
)
from app.models.user_models import AuthenticatedUser
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
