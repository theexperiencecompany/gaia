"""The browser tasks a chat controls, read from the turn's own identity, over fakeredis."""

import pytest

from app.constants.browser import (
    BROWSER_HANDOFF_KEY_PREFIX,
    BROWSER_STOP_REPORTS,
    BrowserStopOutcome,
    HandoffDecision,
)
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable
from app.schemas.browser import NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser.chat_task import (
    ChatTurn,
    PausedStep,
    chat_browser_tasks,
    paused_step,
    stop_report,
    user_message_turn,
)
from app.services.browser.handoff import bot_chat_address, create_pending_handoff, resolve_handoff
from app.services.browser.job_stop import RequesterChat
from app.services.browser.jobs import put_job_state, set_latest_job
from tests.browser_factories import make_browser_job_state
from tests.helpers import captured_wide_event

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

USER = "6812f0b3c9a14e2b7d5a91cc"
WEB_TURN = ChatTurn(conversation_id="conv-1", user_id=USER, source=ConversationSource.WEB)
DM = bot_chat_address(ConversationSource.TELEGRAM, USER)
DM_TURN = ChatTurn(conversation_id="conv-dm", user_id=USER, source=ConversationSource.TELEGRAM)


def _state(job_id: str) -> BrowserJobState:
    return make_browser_job_state(
        job_id,
        status=BrowserJobStatus.RUNNING,
        task="t",
        conversation_id="conv-web",
        user_id=USER,
        in_background=True,
    )


async def _running(job_id: str, *keys: str) -> None:
    for key in keys:
        await set_latest_job(key, job_id)
    await put_job_state(_state(job_id))


async def _paused(handoff_id: str, job_id: str, reply_to: str, user_id: str = USER) -> None:
    await create_pending_handoff(
        handoff_id,
        NewHandoff(
            job_id=job_id,
            user_id=user_id,
            conversation_id="conv-1",
            reason="Sign in",
            reply_to=reply_to,
        ),
    )


class TestUserMessageTurn:
    def test_a_users_turn_carries_its_chat_and_channel(self) -> None:
        configurable: AgentConfigurable = {
            "thread_id": "conv-dm",
            "user_id": USER,
            "conversation_source": "telegram",
        }

        turn = user_message_turn(configurable)

        assert turn == DM_TURN
        assert turn.reply_address == DM
        assert turn.requester == RequesterChat(USER, ConversationSource.TELEGRAM)

    def test_a_web_turn_answers_in_its_own_conversation(self) -> None:
        turn = user_message_turn({"thread_id": "conv-1", "user_id": USER})

        assert turn is not None
        assert (turn.reply_address, turn.requester) == ("conv-1", None)

    @pytest.mark.parametrize(
        "configurable",
        [
            {"thread_id": "conv-1", "user_id": USER, "is_result_narration": True},
            {"thread_id": "conv-1", "user_id": USER, "execution_mode": "background"},
            {"thread_id": "conv-1"},
            {"user_id": USER},
        ],
        ids=["narration", "background", "no-user", "no-chat"],
    )
    def test_a_turn_with_no_users_message_behind_it_is_none(
        self, configurable: AgentConfigurable
    ) -> None:
        assert user_message_turn(configurable) is None


class TestPausedStep:
    async def test_the_step_pending_at_the_reply_address_is_the_one_answered(self) -> None:
        await _paused("h1", "job-1", "conv-1")

        assert await paused_step(WEB_TURN) == PausedStep(
            handoff_id="h1", job_id="job-1", reason="Sign in"
        )

    async def test_a_settled_step_is_no_longer_answered(self) -> None:
        await _paused("h1", "job-1", "conv-1")
        await resolve_handoff("h1", HandoffDecision.CONTINUE, USER)

        assert await paused_step(WEB_TURN) is None

    async def test_another_users_step_is_not_theirs_to_answer(self) -> None:
        await _paused("h1", "job-1", "conv-1", user_id="someone-else")

        async with captured_wide_event() as event:
            assert await paused_step(WEB_TURN) is None

        [warning] = event["warnings"]
        assert warning["msg"] == (
            f"{LogTag.BROWSER} Paused step ignored: the handoff belongs to another user"
        )
        assert (warning["browser"], warning["user_id"]) == ({"handoff_id": "h1"}, USER)

    async def test_a_step_whose_record_expired_is_not_answered(self) -> None:
        await _paused("h1", "job-1", "conv-1")
        await redis_cache.delete(f"{BROWSER_HANDOFF_KEY_PREFIX}h1")

        assert await paused_step(WEB_TURN) is None


class TestChatBrowserTasks:
    async def test_the_conversations_running_task_is_listed_with_nothing_paused(self) -> None:
        await _running("job-1", "conv-1")

        tasks = await chat_browser_tasks(WEB_TURN)

        assert ([job.job_id for job in tasks.running], tasks.paused) == (["job-1"], None)

    async def test_a_paused_run_a_newer_run_displaced_is_still_listed(self) -> None:
        await _running("job-old", DM)
        await _paused("h-old", "job-old", DM)
        await _running("job-new", DM)

        tasks = await chat_browser_tasks(DM_TURN)

        assert [job.job_id for job in tasks.running] == ["job-new", "job-old"]
        assert tasks.paused is not None
        assert tasks.paused.job_id == "job-old"

    async def test_a_paused_run_whose_state_expired_is_not_listed(self) -> None:
        await _running("job-new", DM)
        await _paused("h-old", "job-old", DM)

        tasks = await chat_browser_tasks(DM_TURN)

        assert [job.job_id for job in tasks.running] == ["job-new"]


class TestStopReport:
    def test_any_stop_that_won_reads_as_stopped(self) -> None:
        outcomes = [BrowserStopOutcome.ALREADY_ENDED, BrowserStopOutcome.STOPPED]

        assert stop_report(outcomes) == BROWSER_STOP_REPORTS[BrowserStopOutcome.STOPPED]

    def test_stops_that_all_lost_read_as_already_ended(self) -> None:
        outcomes = iter([BrowserStopOutcome.ALREADY_ENDED])

        assert stop_report(outcomes) == BROWSER_STOP_REPORTS[BrowserStopOutcome.ALREADY_ENDED]
