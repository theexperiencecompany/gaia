"""POST /conversations/{id}/stop: the web Stop cancels the turn and every kind of work the conversation runs."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, call, patch

from httpx import AsyncClient
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.core.stream_manager import stream_manager
from app.models.work_cancel_models import WorkCancelled
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
    LEDGER_APPROVAL,
    SUBAGENT_STREAM,
    ApprovalSeams,
    approval_seams,
    seed_live_work,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis", "logged_stops")]

CONVERSATION = "conv-stop"
STOP_URL = f"/api/v1/conversations/{CONVERSATION}/stop"


@pytest.fixture
def pending_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=True)


@pytest.fixture
def no_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=False)


@pytest.fixture(autouse=True)
def no_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_stop, "_abort_if_started", AsyncMock(return_value=True))


@pytest.fixture
def owned(owned_conversations: set[tuple[str, str]]) -> None:
    owned_conversations.add((CONVERSATION, FAKE_USER.user_id))


@pytest.mark.usefixtures("owned")
class TestStopConversation:
    async def test_the_stop_is_logged_on_the_conversation_before_the_work_is_cancelled(
        self, client: AsyncClient, no_approvals: ApprovalSeams, logged_stops: AsyncMock
    ) -> None:
        response = await client.post(STOP_URL)
        assert response.status_code == 200, response.text
        logged_stops.assert_awaited_once()
        assert logged_stops.await_args.args[:2] == (CONVERSATION, FAKE_USER.user_id)

    async def test_the_answer_is_the_logged_stops_cancel_and_the_rest_of_the_stop(
        self, client: AsyncClient, no_approvals: ApprovalSeams, logged_stops: AsyncMock
    ) -> None:
        logged_stops.return_value = WorkCancelled(
            executor_stopped=True,
            executor_task_id=EXECUTOR_TASK,
            pending_task_ids=["queued-task"],
            approval_ids=[APPROVAL, LEDGER_APPROVAL],
        )
        await seed_live_work(CONVERSATION)

        response = await client.post(STOP_URL)

        assert response.status_code == 200
        assert response.json() == {
            "conversation_id": CONVERSATION,
            "work": {
                "executor_stopped": True,
                "executor_task_id": EXECUTOR_TASK,
                "executor_spared": False,
                "pending_task_ids": ["queued-task"],
                "subagent_ids": ["s1"],
                "approval_ids": [APPROVAL, LEDGER_APPROVAL],
                "browser_jobs": {BROWSER_JOB: "stopped"},
                "replay_ids": [],
            },
        }
        # The executor is the logged Stop's to cancel; the subagent no run holds is the rest's.
        assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
        assert await stream_manager.is_cancelled(SUBAGENT_STREAM)
        # The queued hand-over is the logged Stop's to discard, and it is stubbed here.
        assert [entry.tag for entry in await ExecutorInbox(CONVERSATION).read()] == [
            AgentTag.USER_INTERJECTION,
            AgentTag.BROWSER_STOPPED,
            AgentTag.EXECUTOR_INTERRUPTED,
        ]

    @pytest.mark.regression
    async def test_web_stop_logs_the_stop_and_stops_the_browser_job(
        self, client: AsyncClient, no_approvals: ApprovalSeams, logged_stops: AsyncMock
    ) -> None:
        """Regression: the web Stop cancelled the turn's stream and left the executor and browser job running."""
        await seed_live_work(CONVERSATION)

        await client.post(STOP_URL)

        logged_stops.assert_awaited_once()
        assert await job_cancel_requested(BROWSER_JOB)

    async def test_a_web_stop_emits_work_stopped_exactly_once(
        self, client: AsyncClient, no_approvals: ApprovalSeams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = MagicMock()
        monkeypatch.setattr(conversation_stop_service, "capture", captured)

        await client.post(STOP_URL)

        events = [c.args[1] for c in captured.call_args_list]
        assert [type(event) for event in events] == [ChatWorkStopped]

    async def test_the_stop_is_recorded_on_the_wide_event(
        self, client: AsyncClient, no_approvals: ApprovalSeams
    ) -> None:
        with patch("app.api.v1.endpoints.conversations.log") as conversation_log:
            await client.post(STOP_URL)

        assert conversation_log.set.call_args_list == [
            call(
                user={"id": FAKE_USER.user_id},
                conversation={"operation": "stop", "id": CONVERSATION},
            )
        ]
        conversation_log.set_ns.assert_called_once_with("conversation", stopped_work=False)

    async def test_stopping_an_idle_conversation_is_an_empty_summary(
        self, client: AsyncClient, no_approvals: ApprovalSeams, fake_redis
    ) -> None:
        response = await client.post(STOP_URL)

        assert response.status_code == 200
        body = response.json()
        assert body["work"]["executor_stopped"] is False
        assert body["work"]["browser_jobs"] == {}
        assert await fake_redis.keys("*") == []


class TestStopIsRefusedForAnotherUser:
    async def test_another_users_conversation_is_not_found_and_nothing_stops(
        self,
        client: AsyncClient,
        owned_conversations: set[tuple[str, str]],
        pending_approvals: ApprovalSeams,
        fake_redis,
    ) -> None:
        owned_conversations.add((CONVERSATION, FAKE_USER_2.user_id))
        await seed_live_work(CONVERSATION)

        response = await client.post(STOP_URL)

        assert response.status_code == 404
        assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is not None
        pending_approvals.ledger.assert_not_awaited()
