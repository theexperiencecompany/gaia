"""A scout follows its integration: one learn queued per connect, everything dropped on disconnect."""

from unittest.mock import AsyncMock, sentinel

import pytest

from app.constants.scouts import LEARN_SCOUT_TASK
from app.services.briefing.scouts import lifecycle
from app.services.briefing.scouts.lifecycle import forget_integration, queue_scout_learn

USER_ID = "64f1c0ffee0000000000abcd"


async def test_a_connect_queues_one_learn_per_user_and_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(
        lifecycle.RedisPoolManager, "get_pool", AsyncMock(return_value=sentinel.pool)
    )
    monkeypatch.setattr(lifecycle, "enqueue_worker_job", enqueue)

    await queue_scout_learn(USER_ID, "linear")

    enqueue.assert_awaited_once_with(
        sentinel.pool,
        LEARN_SCOUT_TASK,
        USER_ID,
        "linear",
        _job_id=f"{LEARN_SCOUT_TASK}:{USER_ID}:linear",
    )


async def test_a_disconnect_drops_the_scout_and_its_signal_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drop_scout, drop_memory = AsyncMock(return_value=1), AsyncMock(return_value=3)
    monkeypatch.setattr(lifecycle.scouts_repository, "delete_for", drop_scout)
    monkeypatch.setattr(lifecycle.signal_memory_repository, "delete_for_integration", drop_memory)

    await forget_integration(USER_ID, "linear")

    drop_scout.assert_awaited_once_with(USER_ID, "linear")
    drop_memory.assert_awaited_once_with(USER_ID, "linear")
