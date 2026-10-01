"""A chat message read against a paused browser task: it resolves the handoff, or reaches the running task.

The text-channel equivalent of the handoff card's buttons. Real code under
test: _browser_turn_note, the reply resolution and the handoff bridge over
fakeredis; only the reply classifier (an LLM call) is scripted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.constants.browser import HandoffStatus
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.models.message_models import MessageRequestWithHistory
from app.services.browser import resolution
from app.services.browser.handoff import create_pending_handoff, get_handoff, reply_address
from app.services.browser.jobs import claim_conversation_slot, take_job_messages
from app.services.chat import stream as chat_stream
from app.services.chat.stream import _browser_turn_note

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


@pytest.fixture(autouse=True)
def redis(fake_redis: fakeredis.aioredis.FakeRedis) -> fakeredis.aioredis.FakeRedis:
    return fake_redis


async def test_a_reply_that_finishes_the_step_resolves_it_and_tells_the_turn_so() -> None:
    """The turn's reply is written knowing what the message already did, with no fake exchange put in the thread."""
    await create_pending_handoff("h1", USER_ID, CONVERSATION_ID, REASON, reply_to=CONVERSATION_ID)

    with patch.object(resolution, "ainvoke_structured_gemini", _classifier("continue")):
        note = await _browser_turn_note(_body("done, signed in"), USER_ID, CONVERSATION_ID, "web")

    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.COMPLETED
    assert note is not None
    assert REASON in note


async def test_a_dm_reply_resolves_the_handoff_of_a_run_started_in_a_group() -> None:
    """A bot sends the prompt to the requester's DM whichever chat started the run, so that is where the answer comes from."""
    await create_pending_handoff(
        "h2",
        USER_ID,
        "conv-group",
        REASON,
        reply_to=reply_address("conv-group", USER_ID, ConversationSource.TELEGRAM),
    )

    with patch.object(resolution, "ainvoke_structured_gemini", _classifier("cancel")):
        note = await _browser_turn_note(_body("stop it"), USER_ID, "conv-dm", "telegram")

    record = await get_handoff("h2")
    assert record is not None
    assert record.status is HandoffStatus.CANCELLED
    assert note is not None


async def test_a_message_that_answers_no_handoff_reaches_the_running_task() -> None:
    """What the user says mid-run is something they said, for the run's agent to weigh at its next step."""
    await claim_conversation_slot(CONVERSATION_ID, "job-7")

    note = await _browser_turn_note(_body("use the blue one"), USER_ID, CONVERSATION_ID, "web")

    assert note is None
    assert await take_job_messages("job-7") == ["use the blue one"]


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
