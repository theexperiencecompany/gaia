"""stop_conversation / press_stop: a logged Stop cancels the work it covers, then the rest stops what the log never held."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.core.stream_manager import stream_manager
from app.models.work_cancel_models import WorkCancelled
from app.services import conversation_stop_service
from app.services.browser import job_stop
from app.services.conversation.work_log import WorkNotCancelled
from app.services.conversation_stop_service import press_stop, stop_conversation
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatWorkStopped
from tests.work_cancel_fakes import (
    EXECUTOR_STREAM,
    SUBAGENT_STREAM,
    ApprovalSeams,
    approval_seams,
    claim_subagent,
    seed_live_work,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.usefixtures("fake_redis", "no_approvals", "logged_stops"),
]

CONVERSATION = "conv-stop"
OTHER_CONVERSATION = "conv-other"
USER = "507f1f77bcf86cd799439011"


@pytest.fixture
def no_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=False)


@pytest.fixture(autouse=True)
def no_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_stop, "_abort_if_started", AsyncMock(return_value=True))


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(conversation_stop_service, "capture", mock)
    return mock


LOGGED = WorkCancelled(
    executor_stopped=True, executor_task_id="running-task", pending_task_ids=["queued-task"]
)


class TestStopConversation:
    async def test_nothing_running_is_an_empty_summary_that_touches_nothing(
        self, fake_redis: fakeredis.aioredis.FakeRedis, logged_stops: AsyncMock
    ) -> None:
        result = await stop_conversation(CONVERSATION, USER, None)

        assert result.conversation_id == CONVERSATION
        assert result.work == WorkCancelled()
        logged_stops.assert_awaited_once()
        assert await fake_redis.keys("*") == []

    async def test_the_answer_is_what_the_logged_stop_cancelled_and_the_rest_it_stopped(
        self, logged_stops: AsyncMock
    ) -> None:
        logged_stops.return_value = LOGGED
        subagent_stream = await claim_subagent(CONVERSATION, "s1", dispatched_by="live-turn")

        result = await stop_conversation(CONVERSATION, USER, None)

        assert result.work == LOGGED.model_copy(update={"subagent_ids": ["s1"]})
        assert await stream_manager.is_cancelled(subagent_stream)
        assert [entry.tag for entry in await ExecutorInbox(CONVERSATION).read()] == [
            AgentTag.EXECUTOR_INTERRUPTED
        ]

    async def test_the_executor_is_left_to_the_logged_stop(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await seed_live_work(CONVERSATION)

        await stop_conversation(CONVERSATION, USER, None)

        assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is not None

    async def test_another_conversations_work_keeps_running(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await seed_live_work(OTHER_CONVERSATION)

        await stop_conversation(CONVERSATION, USER, None)

        assert not await stream_manager.is_cancelled(SUBAGENT_STREAM)
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{OTHER_CONVERSATION}") is not None
        assert len(await ExecutorInbox(OTHER_CONVERSATION).read()) == 1


class TestPressStop:
    async def test_a_press_counts_once_with_what_it_stopped(
        self, captured: MagicMock, logged_stops: AsyncMock
    ) -> None:
        logged_stops.return_value = LOGGED
        await seed_live_work(CONVERSATION)

        await press_stop(CONVERSATION, USER, None)

        captured.assert_called_once_with(
            UserId(USER),
            ChatWorkStopped(
                executor_stopped=True,
                pending_tasks=1,
                subagents=1,
                approvals=0,
                browser_jobs=1,
            ),
        )

    async def test_a_press_with_nothing_running_still_answers_and_counts(
        self, captured: MagicMock
    ) -> None:
        result = await press_stop(CONVERSATION, USER, None)

        assert result.work == WorkCancelled()
        captured.assert_called_once_with(
            UserId(USER),
            ChatWorkStopped(
                executor_stopped=False,
                pending_tasks=0,
                subagents=0,
                approvals=0,
                browser_jobs=0,
            ),
        )

    async def test_a_failed_cancel_is_not_counted(
        self, captured: MagicMock, logged_stops: AsyncMock
    ) -> None:
        logged_stops.side_effect = WorkNotCancelled(CONVERSATION)

        with pytest.raises(WorkNotCancelled):
            await press_stop(CONVERSATION, USER, None)

        captured.assert_not_called()
