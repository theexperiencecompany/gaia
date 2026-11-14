"""call_executor on a conversation the step runs: WorkStarted is logged before the run spawns, or nothing runs."""

from collections.abc import Coroutine
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background.executor_queue import build_lock_value, try_acquire_lock
from app.agents.tools import executor_tool as et
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.db.redis import redis_cache
from app.models.agent_config import StepTurnRef
from app.models.agent_models import AgentConfigurable

pytestmark = pytest.mark.usefixtures("fake_redis")

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
STEP: StepTurnRef = {"epoch": 3, "batch_start": 4, "cause_through": 5, "answers": ["m4", "m5"]}
BUSY_KEY = f"{EXECUTOR_BUSY_PREFIX}conv-1"


def _configurable() -> AgentConfigurable:
    return {"user_id": USER_ID, "thread_id": "conv-1", "conversation_step": STEP}


async def _dispatch() -> str:
    return await et._dispatch_executor(
        task="do the thing",
        task_id="task-1",
        configurable=_configurable(),
        conversation_id="conv-1",
        handoff="call_1",
    )


async def test_a_refused_work_started_dispatches_nothing_and_frees_the_lock() -> None:
    with (
        patch.object(et, "record_work_started", AsyncMock(return_value=False)) as record,
        patch.object(et, "spawn_background_task") as spawn,
    ):
        result = await _dispatch()
    record.assert_awaited_once_with(STEP, "conv-1", USER_ID, "task-1", handoff="call_1")
    spawn.assert_not_called()
    assert await redis_cache.client.get(BUSY_KEY) is None
    assert result == et._NOT_STARTED_STOPPED


async def test_work_started_is_logged_before_the_run_spawns() -> None:
    order: list[str] = []

    async def logged(*_: object, **__: object) -> bool:
        order.append("logged")
        return True

    def spawned(coro: Coroutine[object, object, object], **_: object) -> MagicMock:
        order.append("spawned")
        coro.close()
        return MagicMock()

    with (
        patch.object(et, "record_work_started", side_effect=logged),
        patch.object(et, "spawn_background_task", side_effect=spawned),
    ):
        result = await _dispatch()
    assert order == ["logged", "spawned"]
    assert "Handed to the executor (task_id: task-1)" in result


async def _hold_lock() -> None:
    """Take the conversation's busy lock as the running t-running would."""
    assert await try_acquire_lock(BUSY_KEY, build_lock_value("other-stream", "t-running"))


def _busy(stack: ExitStack, order: list[str], joined: bool) -> AsyncMock:
    """Patch the inbox and record_work_started around a lock another run holds; return the record patch."""

    async def logged(*_: object, **__: object) -> bool:
        order.append("logged")
        return joined

    async def handed(*_: object) -> None:
        order.append("handed")

    inbox = MagicMock()
    inbox.return_value.append = AsyncMock(side_effect=handed)
    stack.enter_context(patch.object(et, "reclaim_dead_lock", AsyncMock(return_value=False)))
    stack.enter_context(
        patch.object(et, "_acquire_lock_through_redirect", AsyncMock(return_value=False))
    )
    stack.enter_context(patch.object(et, "ExecutorInbox", inbox))
    return stack.enter_context(patch.object(et, "record_work_started", side_effect=logged))


async def test_work_handed_to_a_running_executor_is_logged_as_joining_it_first() -> None:
    order: list[str] = []
    await _hold_lock()
    with ExitStack() as stack:
        record = _busy(stack, order, joined=True)
        result = await _dispatch()
    record.assert_awaited_once_with(
        STEP, "conv-1", USER_ID, "task-1", joins="t-running", handoff="call_1"
    )
    assert order == ["logged", "handed"]
    assert "added to the work already in progress" in result


async def test_work_whose_join_is_refused_is_not_handed_over() -> None:
    order: list[str] = []
    await _hold_lock()
    with ExitStack() as stack:
        _busy(stack, order, joined=False)
        result = await _dispatch()
    assert order == ["logged"]
    assert result == et._NOT_STARTED_STOPPED
