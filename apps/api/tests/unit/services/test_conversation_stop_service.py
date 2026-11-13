"""stop_conversation / press_stop: one Stop cancels the conversation's turns and all its work, and only its own."""

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
from app.services.conversation_stop_service import press_stop, stop_conversation
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatWorkStopped
from tests.work_cancel_fakes import (
    EXECUTOR_STREAM,
    approval_seams,
    claim_subagent,
    seed_live_work,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis", "no_approvals")]

CONVERSATION = "conv-stop"
OTHER_CONVERSATION = "conv-other"
USER = "507f1f77bcf86cd799439011"


@pytest.fixture
def no_approvals() -> Iterator[AsyncMock]:
    yield from approval_seams(pending=False)


@pytest.fixture(autouse=True)
def no_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_stop, "_abort_if_started", AsyncMock(return_value=True))


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(conversation_stop_service, "capture", mock)
    return mock


class TestStopConversation:
    async def test_nothing_running_is_an_empty_summary_that_touches_nothing(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        result = await stop_conversation(CONVERSATION, USER, None)

        assert result.conversation_id == CONVERSATION
        assert result.stream_ids == []
        assert result.work == WorkCancelled()
        assert await fake_redis.keys("*") == []

    async def test_an_older_turn_the_caller_holds_is_cancelled_beside_the_live_one(self) -> None:
        """Only the newest turn is indexed; an older concurrent one is reached only by name."""
        await stream_manager.start_stream("older-turn", CONVERSATION, USER)
        await stream_manager.start_stream("live-turn", CONVERSATION, USER)

        result = await stop_conversation(CONVERSATION, USER, None, held_stream_id="older-turn")

        assert result.stream_ids == ["older-turn", "live-turn"]
        assert await stream_manager.is_cancelled("older-turn")
        assert await stream_manager.is_cancelled("live-turn")

    async def test_a_subagent_the_turn_dispatched_is_counted_and_its_stop_announced(self) -> None:
        """Cancelling the turn must leave its subagents to the sweep, which reports what it stopped."""
        await stream_manager.start_stream("live-turn", CONVERSATION, USER)
        subagent_stream = await claim_subagent(CONVERSATION, "s1", dispatched_by="live-turn")

        result = await stop_conversation(CONVERSATION, USER, None)

        assert result.work.subagent_ids == ["s1"]
        assert await stream_manager.is_cancelled(subagent_stream)
        assert [entry.tag for entry in await ExecutorInbox(CONVERSATION).read()] == [
            AgentTag.EXECUTOR_INTERRUPTED
        ]

    async def test_another_conversations_work_keeps_running(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await stream_manager.start_stream("other-turn", OTHER_CONVERSATION, USER)
        await seed_live_work(OTHER_CONVERSATION)
        await stream_manager.start_stream("live-turn", CONVERSATION, USER)

        await stop_conversation(CONVERSATION, USER, None)

        assert await stream_manager.is_cancelled("live-turn")
        assert not await stream_manager.is_cancelled("other-turn")
        assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{OTHER_CONVERSATION}") is not None
        assert len(await ExecutorInbox(OTHER_CONVERSATION).read()) == 1


class TestPressStop:
    async def test_a_press_counts_once_with_what_it_stopped(self, captured: MagicMock) -> None:
        await stream_manager.start_stream("live-turn", CONVERSATION, USER)
        await seed_live_work(CONVERSATION)

        await press_stop(CONVERSATION, USER, None)

        captured.assert_called_once_with(
            UserId(USER),
            ChatWorkStopped(
                streams=1,
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
                streams=0,
                executor_stopped=False,
                pending_tasks=0,
                subagents=0,
                approvals=0,
                browser_jobs=0,
            ),
        )

    async def test_the_held_stream_reaches_the_stop(self, captured: MagicMock) -> None:
        await stream_manager.start_stream("older-turn", CONVERSATION, USER)
        await stream_manager.start_stream("live-turn", CONVERSATION, USER)

        result = await press_stop(CONVERSATION, USER, None, held_stream_id="older-turn")

        assert result.stream_ids == ["older-turn", "live-turn"]
        assert await stream_manager.is_cancelled("older-turn")

    async def test_a_failed_cancel_is_not_counted(
        self, captured: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            conversation_stop_service,
            "cancel_all_work",
            AsyncMock(side_effect=RuntimeError("redis unavailable")),
        )

        with pytest.raises(RuntimeError, match="redis unavailable"):
            await press_stop(CONVERSATION, USER, None)

        captured.assert_not_called()
