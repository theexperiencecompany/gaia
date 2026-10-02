"""A chat message read against a paused browser task: it resolves the handoff, or reaches the running task.

The text-channel equivalent of the handoff card's buttons. Real code under
test: _browser_turn_note, the reply resolution and the handoff bridge over
fakeredis; only the reply classifier (an LLM call) is scripted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.constants.browser import (
    BROWSER_HANDOFF_REPLY_NOTE,
    BROWSER_HANDOFF_REPLY_READINGS,
    BROWSER_RUN_STOPPED_BY_MESSAGE_NOTE,
    HandoffStatus,
)
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.models.message_models import MessageRequestWithHistory
from app.schemas.browser import NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser import job_stop, resolution
from app.services.browser.handoff import create_pending_handoff, get_handoff, reply_address
from app.services.browser.jobs import (
    claim_conversation_slot,
    job_cancel_requested,
    put_job_state,
    set_job_wait,
    set_latest_job,
    take_job_messages,
)
from app.services.chat import stream as chat_stream
from app.services.chat.stream import _browser_turn_note
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

CONVERSATION_ID = "conv-1"
USER_ID = "user-1"
REASON = "Sign in to finish the booking."


def _body(message: str) -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message=message,
        messages=[{"role": "user", "content": message}],
        conversation_id=CONVERSATION_ID,
    )


def _classifier(action: resolution.HandoffReplyAction, note: str | None = None) -> AsyncMock:
    return AsyncMock(return_value=resolution.HandoffReplyDecision(action=action, note=note))


def _reads_running(action: str) -> AsyncMock:
    return AsyncMock(return_value=resolution.RunningTaskMessageDecision(action=action))


@pytest.fixture(autouse=True)
def redis(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> fakeredis.aioredis.FakeRedis:
    """Back the app's cache and ARQ's pool with the same fake Redis."""
    monkeypatch.setattr(job_stop.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    return fake_redis


async def _running(job_id: str, *addresses: str) -> None:
    """Start a job in the conversation, findable by a stop at each address."""
    await claim_conversation_slot(CONVERSATION_ID, job_id)
    for address in addresses:
        await set_latest_job(address, job_id)
    await put_job_state(BrowserJobState(job_id=job_id, status=BrowserJobStatus.RUNNING, task="t"))


async def test_a_reply_that_finishes_the_step_resolves_it_and_tells_the_turn_so() -> None:
    """The turn's reply is written knowing what the message already did, with no fake exchange put in the thread."""
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-7",
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            reason=REASON,
            reply_to=CONVERSATION_ID,
        ),
    )

    classifier = _classifier("continue")
    with patch.object(resolution, "ainvoke_structured_gemini", classifier):
        note = await _browser_turn_note(_body("done, signed in"), USER_ID, CONVERSATION_ID, "web")

    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.COMPLETED
    _schema, prompt = classifier.await_args.args
    assert "done, signed in" in prompt
    assert note == BROWSER_HANDOFF_REPLY_NOTE.format(
        reason=REASON, reading=BROWSER_HANDOFF_REPLY_READINGS["continue"]
    )


async def test_a_dm_reply_resolves_the_handoff_of_a_run_started_in_a_group() -> None:
    """A bot sends the prompt to the requester's DM whichever chat started the run, so that is where the answer comes from."""
    dm = reply_address("conv-group", USER_ID, ConversationSource.TELEGRAM)
    await _running("job-2", "conv-group", dm)
    await create_pending_handoff(
        "h2",
        NewHandoff(
            job_id="job-2",
            user_id=USER_ID,
            conversation_id="conv-group",
            reason=REASON,
            reply_to=dm,
        ),
    )
    await set_job_wait("job-2", "h2")

    with patch.object(resolution, "ainvoke_structured_gemini", _classifier("cancel")):
        note = await _browser_turn_note(_body("stop it"), USER_ID, "conv-dm", "telegram")

    record = await get_handoff("h2")
    assert record is not None
    assert record.status is HandoffStatus.CANCELLED
    assert await job_cancel_requested("job-2") is True
    assert note is not None


async def test_a_message_that_answers_no_handoff_reaches_the_running_task() -> None:
    """What the user says mid-run is something they said, for the run's agent to weigh at its next step."""
    await _running("job-7", CONVERSATION_ID)

    classifier = _reads_running("other")
    with patch.object(resolution, "ainvoke_structured_gemini", classifier):
        async with captured_wide_event() as event:
            note = await _browser_turn_note(
                _body("use the blue one"), USER_ID, CONVERSATION_ID, "web"
            )

    assert note is None
    assert await take_job_messages("job-7") == ["use the blue one"]
    assert event["browser"] == {"job_id": "job-7", "message_to_running_job": True}
    _schema, prompt = classifier.await_args.args
    assert "use the blue one" in prompt
    assert await job_cancel_requested("job-7") is False


async def test_a_stop_said_while_the_task_runs_stops_it_and_the_turn_says_so() -> None:
    """Read as a note, a "stop" let the run's own agent end it as a failure its executor then narrated."""
    await _running("job-7", CONVERSATION_ID)

    with patch.object(resolution, "ainvoke_structured_gemini", _reads_running("stop")):
        note = await _browser_turn_note(_body("stop"), USER_ID, CONVERSATION_ID, "telegram")

    assert note == BROWSER_RUN_STOPPED_BY_MESSAGE_NOTE
    assert await job_cancel_requested("job-7") is True
    assert await take_job_messages("job-7") == []


async def test_a_reply_the_model_finds_unrelated_to_the_paused_step_reaches_the_task() -> None:
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-7",
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            reason=REASON,
            reply_to=CONVERSATION_ID,
        ),
    )
    await _running("job-7", CONVERSATION_ID)

    with patch.object(resolution, "ainvoke_structured_gemini", _classifier("unrelated")):
        note = await _browser_turn_note(_body("which card?"), USER_ID, CONVERSATION_ID, "web")

    assert note is None
    assert await take_job_messages("job-7") == ["which card?"]


async def test_a_message_with_no_user_behind_it_reaches_no_task() -> None:
    await claim_conversation_slot(CONVERSATION_ID, "job-7")

    assert await _browser_turn_note(_body("use the blue one"), None, CONVERSATION_ID, "web") is None
    assert await take_job_messages("job-7") == []


async def test_a_failed_lookup_leaves_the_turn_as_it_was() -> None:
    """An optional lookup failing must not take chat down; the failure is logged by type."""
    with (
        patch.object(chat_stream, "log") as log,
        patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(side_effect=ValueError("boom"))
        ),
    ):
        note = await _browser_turn_note(_body("done"), USER_ID, CONVERSATION_ID, "web")

    assert note is None
    log.error.assert_called_once_with(
        f"{LogTag.CHAT} Pending browser-handoff check failed; normal turn",
        error_type="ValueError",
    )


async def test_a_failed_read_for_a_stop_still_delivers_the_message_to_the_task() -> None:
    """The read shared the handoff lookup's failure path, which dropped the user's instruction."""
    await _running("job-7", CONVERSATION_ID)

    with (
        patch.object(chat_stream, "log") as log,
        patch.object(
            resolution, "ainvoke_structured_gemini", AsyncMock(side_effect=RuntimeError("503"))
        ),
    ):
        note = await _browser_turn_note(_body("use the blue one"), USER_ID, CONVERSATION_ID, "web")

    assert note is None
    assert await take_job_messages("job-7") == ["use the blue one"]
    log.error.assert_called_once_with(
        f"{LogTag.CHAT} Reading a mid-run message for a stop failed; it goes to the task",
        error_type="RuntimeError",
    )
