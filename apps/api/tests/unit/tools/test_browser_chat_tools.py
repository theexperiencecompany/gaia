"""Comms' browser-task tools: which job each reaches, whose it must be, and on which turns they act.

Real code over fakeredis, ARQ's keys included; the job is found from the
turn's own identity, never from an id the model wrote.
"""

from typing import Any
from unittest.mock import AsyncMock

from arq.constants import abort_jobs_ss, in_progress_key_prefix
import fakeredis.aioredis
from langchain_core.tools import BaseTool
import pytest

from app.agents.tools.browser_chat_tools import (
    browser_step_done,
    stop_browser_task,
    tell_browser_task,
)
from app.constants.browser import HandoffStatus, JobEnding
from app.constants.chat import ConversationSource
from app.schemas.browser import NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser import job_stop
from app.services.browser.handoff import (
    await_handoff,
    bot_chat_address,
    create_pending_handoff,
    get_handoff,
)
from app.services.browser.jobs import (
    job_ending,
    put_job_state,
    set_job_wait,
    set_latest_job,
    take_job_messages,
)

pytestmark = pytest.mark.unit

USER = "user-1"
CONVERSATION = "conv-1"
REASON = "Sign in to finish the booking"


@pytest.fixture(autouse=True)
def arq(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> fakeredis.aioredis.FakeRedis:
    """ARQ's pool on the same fake Redis."""
    monkeypatch.setattr(job_stop.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    return fake_redis


def _turn(conversation_id: str = CONVERSATION, **extra: Any) -> dict[str, Any]:
    return {"configurable": {"thread_id": conversation_id, "user_id": USER, **extra}}


async def _say(chat_tool: BaseTool, args: dict[str, Any], config: dict[str, Any]) -> str:
    return str(await chat_tool.ainvoke(args, config=config))


async def _running(job_id: str, *keys: str) -> None:
    for key in keys:
        await set_latest_job(key, job_id)
    await put_job_state(
        BrowserJobState(job_id=job_id, status=BrowserJobStatus.RUNNING, task=f"task of {job_id}")
    )


async def _paused(job_id: str, reply_to: str, *, user_id: str = USER) -> str:
    handoff_id = f"h-{job_id}"
    await create_pending_handoff(
        handoff_id,
        NewHandoff(
            job_id=job_id,
            user_id=user_id,
            conversation_id=CONVERSATION,
            reason=REASON,
            reply_to=reply_to,
        ),
    )
    await set_job_wait(job_id, handoff_id)
    return handoff_id


class TestBrowserStepDone:
    async def test_a_done_with_a_note_resumes_the_paused_step_carrying_the_note(self) -> None:
        await _running("job-1", CONVERSATION)
        handoff_id = await _paused("job-1", CONVERSATION)

        await _say(browser_step_done, {"note": " also grab the photo "}, _turn())

        outcome = await await_handoff(handoff_id, 1)
        assert outcome.status is HandoffStatus.COMPLETED
        assert outcome.message == "also grab the photo"
        assert outcome.redirect is False

    async def test_a_redirect_replaces_the_task_with_the_new_instruction(self) -> None:
        await _running("job-1", CONVERSATION)
        handoff_id = await _paused("job-1", CONVERSATION)

        await _say(
            browser_step_done, {"note": "just tell me the headline", "redirect": True}, _turn()
        )

        outcome = await await_handoff(handoff_id, 1)
        assert (outcome.status, outcome.message, outcome.redirect) == (
            HandoffStatus.COMPLETED,
            "just tell me the headline",
            True,
        )

    async def test_a_redirect_without_the_new_instruction_leaves_the_step_waiting(self) -> None:
        await _running("job-1", CONVERSATION)
        handoff_id = await _paused("job-1", CONVERSATION)

        await _say(browser_step_done, {"redirect": True}, _turn())

        record = await get_handoff(handoff_id)
        assert record is not None
        assert record.status is HandoffStatus.PENDING

    async def test_a_done_in_the_dm_resumes_the_run_the_user_started_in_a_group(self) -> None:
        dm = bot_chat_address(ConversationSource.TELEGRAM, USER)
        await _running("job-g", "conv-group", dm)
        handoff_id = await _paused("job-g", dm)

        await _say(browser_step_done, {}, _turn("conv-dm", conversation_source="telegram"))

        record = await get_handoff(handoff_id)
        assert record is not None
        assert record.status is HandoffStatus.COMPLETED

    async def test_another_users_paused_step_is_left_alone(self) -> None:
        await _running("job-1", CONVERSATION)
        handoff_id = await _paused("job-1", CONVERSATION, user_id="someone-else")

        await _say(browser_step_done, {}, _turn())

        record = await get_handoff(handoff_id)
        assert record is not None
        assert record.status is HandoffStatus.PENDING

    @pytest.mark.parametrize(
        "turn",
        [_turn(is_result_narration=True), _turn(execution_mode="background")],
        ids=["narration", "background"],
    )
    async def test_a_turn_with_no_user_message_settles_nothing(self, turn: dict[str, Any]) -> None:
        await _running("job-1", CONVERSATION)
        handoff_id = await _paused("job-1", CONVERSATION)

        await _say(browser_step_done, {}, turn)

        record = await get_handoff(handoff_id)
        assert record is not None
        assert record.status is HandoffStatus.PENDING


class TestStopBrowserTask:
    async def test_a_stop_reaches_the_running_job_and_aborts_its_worker(
        self, arq: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _running("job-1", CONVERSATION)
        await arq.set(f"{in_progress_key_prefix}job-1", "1")

        await _say(stop_browser_task, {}, _turn())

        assert await job_ending("job-1") is JobEnding.STOPPED
        assert await arq.zscore(abort_jobs_ss, "job-1") is not None

    async def test_a_stop_while_paused_stops_the_paused_job_and_settles_its_step(self) -> None:
        dm = bot_chat_address(ConversationSource.TELEGRAM, USER)
        await _running("job-g", "conv-group", dm)
        await _running("job-dm", "conv-dm")
        handoff_id = await _paused("job-g", dm)

        await _say(stop_browser_task, {}, _turn("conv-dm", conversation_source="telegram"))

        record = await get_handoff(handoff_id)
        assert record is not None
        assert record.status is HandoffStatus.CANCELLED
        assert await job_ending("job-g") is JobEnding.STOPPED
        assert await job_ending("job-dm") is None

    async def test_a_narration_turn_stops_nothing(self) -> None:
        await _running("job-1", CONVERSATION)

        await _say(stop_browser_task, {}, _turn(is_result_narration=True))

        assert await job_ending("job-1") is None

    async def test_another_chats_job_is_out_of_reach(self) -> None:
        await _running("job-1", "conv-other")

        await _say(stop_browser_task, {}, _turn())

        assert await job_ending("job-1") is None


class TestTellBrowserTask:
    async def test_the_users_words_reach_the_running_job(self) -> None:
        await _running("job-1", CONVERSATION)

        await _say(tell_browser_task, {"text": " use the blue one "}, _turn())

        assert await take_job_messages("job-1") == ["use the blue one"]

    async def test_a_paused_job_gets_the_words_for_when_it_resumes_and_stays_paused(self) -> None:
        await _running("job-1", CONVERSATION)
        handoff_id = await _paused("job-1", CONVERSATION)

        await _say(tell_browser_task, {"text": "also grab the photo"}, _turn())

        assert await take_job_messages("job-1") == ["also grab the photo"]
        record = await get_handoff(handoff_id)
        assert record is not None
        assert record.status is HandoffStatus.PENDING

    async def test_a_narration_turn_tells_the_job_nothing(self) -> None:
        await _running("job-1", CONVERSATION)

        await _say(tell_browser_task, {"text": "use the blue one"}, _turn(is_result_narration=True))

        assert await take_job_messages("job-1") == []
