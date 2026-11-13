"""POST /conversations/{id}/stop: the web Stop cancels the turn and every kind of work the conversation runs."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, call, patch

from httpx import AsyncClient
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.core.stream_manager import stream_manager
from app.services import conversation_stop_service
from app.services.browser import job_stop
from app.services.browser.jobs import job_cancel_requested
from shared.py.analytics.catalog.chat import ChatWorkStopped
from tests.conftest import FAKE_USER, FAKE_USER_2
from tests.work_cancel_fakes import (
    APPROVAL,
    BROWSER_JOB,
    EXECUTOR_STREAM,
    EXECUTOR_TASK,
    SUBAGENT_STREAM,
    approval_seams,
    seed_live_work,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

CONVERSATION = "conv-stop"
TURN = "turn-stream"
STOP_URL = f"/api/v1/conversations/{CONVERSATION}/stop"


@pytest.fixture
def pending_approvals() -> Iterator[AsyncMock]:
    yield from approval_seams(pending=True)


@pytest.fixture
def no_approvals() -> Iterator[AsyncMock]:
    yield from approval_seams(pending=False)


@pytest.fixture(autouse=True)
def no_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_stop, "_abort_if_started", AsyncMock(return_value=True))


@pytest.fixture
def owned(owned_conversations: set[tuple[str, str]]) -> None:
    owned_conversations.add((CONVERSATION, FAKE_USER.user_id))


@pytest.mark.usefixtures("owned")
class TestStopConversation:
    async def test_the_stop_cancels_the_turn_and_the_full_set_of_work(
        self, client: AsyncClient, pending_approvals: AsyncMock
    ) -> None:
        await stream_manager.start_stream(TURN, CONVERSATION, FAKE_USER.user_id)
        await seed_live_work(CONVERSATION)

        response = await client.post(STOP_URL)

        assert response.status_code == 200
        assert response.json() == {
            "conversation_id": CONVERSATION,
            "stream_ids": [TURN],
            "work": {
                "executor_stopped": True,
                "executor_task_id": EXECUTOR_TASK,
                "executor_spared": False,
                "pending_tasks": 1,
                "pending_task_ids": [],
                "subagent_ids": ["s1"],
                "approval_ids": [APPROVAL],
                "browser_jobs": {BROWSER_JOB: "stopped"},
            },
        }
        for stream_id in (TURN, EXECUTOR_STREAM, SUBAGENT_STREAM):
            assert await stream_manager.is_cancelled(stream_id)
        assert await stream_manager.get_active_stream_id(FAKE_USER.user_id, CONVERSATION) is None
        assert [entry.tag for entry in await ExecutorInbox(CONVERSATION).read()] == [
            AgentTag.BROWSER_STOPPED,
            AgentTag.EXECUTOR_INTERRUPTED,
        ]

    @pytest.mark.regression
    async def test_web_stop_cancels_approvals_and_the_browser_job(
        self, client: AsyncClient, pending_approvals: AsyncMock
    ) -> None:
        """Regression: the web Stop cancelled the turn's stream and left approval cards live and the executor running."""
        await stream_manager.start_stream(TURN, CONVERSATION, FAKE_USER.user_id)
        await seed_live_work(CONVERSATION)

        await client.post(STOP_URL)

        pending_approvals.assert_awaited_once_with(CONVERSATION, FAKE_USER.user_id)
        assert await job_cancel_requested(BROWSER_JOB)

    async def test_a_web_stop_emits_work_stopped_exactly_once(
        self, client: AsyncClient, no_approvals: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = MagicMock()
        monkeypatch.setattr(conversation_stop_service, "capture", captured)

        await client.post(STOP_URL)

        events = [c.args[1] for c in captured.call_args_list]
        assert [type(event) for event in events] == [ChatWorkStopped]

    async def test_the_stop_is_recorded_on_the_wide_event(
        self, client: AsyncClient, no_approvals: AsyncMock
    ) -> None:
        await stream_manager.start_stream(TURN, CONVERSATION, FAKE_USER.user_id)

        with patch("app.api.v1.endpoints.conversations.log") as conversation_log:
            await client.post(STOP_URL)

        assert conversation_log.set.call_args_list == [
            call(
                user={"id": FAKE_USER.user_id},
                conversation={"operation": "stop", "id": CONVERSATION},
            )
        ]
        conversation_log.set_ns.assert_called_once_with(
            "conversation", stopped_streams=1, stopped_work=False
        )

    async def test_stopping_an_idle_conversation_is_an_empty_summary(
        self, client: AsyncClient, no_approvals: AsyncMock, fake_redis
    ) -> None:
        response = await client.post(STOP_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["stream_ids"] == []
        assert body["work"]["executor_stopped"] is False
        assert body["work"]["browser_jobs"] == {}
        assert await fake_redis.keys("*") == []


class TestStopIsRefusedForAnotherUser:
    async def test_another_users_conversation_is_not_found_and_nothing_stops(
        self,
        client: AsyncClient,
        owned_conversations: set[tuple[str, str]],
        pending_approvals: AsyncMock,
        fake_redis,
    ) -> None:
        owned_conversations.add((CONVERSATION, FAKE_USER_2.user_id))
        await seed_live_work(CONVERSATION)

        response = await client.post(STOP_URL)

        assert response.status_code == 404
        assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is not None
        pending_approvals.assert_not_awaited()
