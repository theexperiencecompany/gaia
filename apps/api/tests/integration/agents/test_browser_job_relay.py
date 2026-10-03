"""A background job's cards fold into the message of the turn that started it, on a stream of their own.

Real code under test: relay_job_cards and follow_job_cards, the job feed, the
detached stream's session and its close (folded_stream), over fakeredis. Faked:
the SSE publish, the websocket announce and the conversation repository, so the
frames and the saved entries asserted here are the ones the client really gets.
"""

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from app.agents.core.background import executor_queue, folded_stream, redis_writer as rw
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus
from app.constants.log_tags import LogTag
from app.models.chat_models import MessageModel
from app.schemas.browser import BrowserResultSnapshot, BrowserSessionSnapshot, BrowserStepSnapshot
from app.schemas.browser_job import BrowserJobFinished, BrowserJobRequest, BrowserJobStopped
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_relay import follow_job_cards, relay_job_cards
from app.services.browser.job_runner import publish_frame_to_job
from app.services.browser.jobs import claim_conversation_slot, record_ending
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.integration

JOB_ID = "job-1"
CONVERSATION = "conv-1"
MESSAGE_ID = "bot-msg-1"
REQUEST = BrowserJobRequest(
    job_id=JOB_ID,
    tool_call_id="call-1",
    user_id="u1",
    conversation_id=CONVERSATION,
    task="book",
    in_background=True,
    message_id=MESSAGE_ID,
)
RESULT = BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")


@pytest.fixture(autouse=True)
async def redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.db.redis.redis_cache.redis", client)
    yield client
    await client.aclose()


class Client:
    """What the user's client and the conversation store saw of the relay."""

    def __init__(self) -> None:
        self.announced: list[dict[str, Any]] = []
        self.chunks: dict[str, list[str]] = {}
        self.saved: list[dict[str, Any]] = []

    def frames(self) -> list[dict[str, Any]]:
        [stream] = self.chunks.values()
        return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in stream]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Client:
    seen = Client()

    async def _publish_chunk(stream_id: str, chunk: str) -> None:
        seen.chunks.setdefault(stream_id, []).append(chunk)

    async def _broadcast(_user_id: str, payload: dict[str, Any]) -> None:
        seen.announced.append(payload)

    async def _append(conversation_id: str, **kwargs: Any) -> bool:
        seen.saved.append({"conversation_id": conversation_id, **kwargs})
        return True

    manager = MagicMock()
    manager.publish_chunk = _publish_chunk
    monkeypatch.setattr(rw, "stream_manager", manager)
    monkeypatch.setattr(executor_queue, "StreamManager", AsyncMock())
    monkeypatch.setattr(executor_queue.websocket_manager, "broadcast_to_user", _broadcast)
    conversations = MagicMock()
    conversations.get_message = AsyncMock(
        return_value=MessageModel(type="bot", response="", tool_data=[])
    )
    conversations.append_message_tool_data = _append
    monkeypatch.setattr(folded_stream, "conversation_repository", conversations)
    streams = MagicMock()
    streams.is_cancelled = AsyncMock(return_value=False)
    monkeypatch.setattr(folded_stream, "stream_manager", streams)
    return seen


def _card(
    snapshot: BrowserSessionSnapshot | BrowserStepSnapshot | BrowserResultSnapshot,
) -> dict[str, object]:
    return {BROWSER_TASK_EVENT: snapshot.model_dump(mode="json")}


async def _publish_cards(*, end: bool) -> None:
    """Publish what a worker publishes for a short run; close the feed when end."""
    await publish_frame_to_job(
        JOB_ID,
        _card(
            BrowserSessionSnapshot(task="book", status=BrowserSessionStatus.RUNNING, session_id="s")
        ),
    )
    await publish_frame_to_job(JOB_ID, _card(BrowserStepSnapshot(index=1, goal="open the menu")))
    if end:
        await publish_frame_to_job(JOB_ID, _card(RESULT))
        await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)


async def test_the_cards_fold_into_the_starting_turns_message_and_are_saved_there(
    client: Client,
) -> None:
    """Live on a stream of the job's own, folded into the turn's message; saved there when the job ends, so a reload shows them."""
    await _publish_cards(end=True)

    await relay_job_cards(REQUEST)

    [announce] = client.announced
    assert (announce["bot_message_id"], announce["kind"], announce["task_id"]) == (
        MESSAGE_ID,
        "subagent",
        JOB_ID,
    )
    [stream_id] = client.chunks
    assert stream_id == announce["stream_id"]
    kinds = [frame["tool_data"]["data"]["kind"] for frame in client.frames()]
    assert kinds == ["session", "step", "result"]
    [saved] = client.saved
    assert (saved["conversation_id"], saved["message_id"]) == (CONVERSATION, MESSAGE_ID)
    assert [entry["data"]["kind"] for entry in saved["entries"]] == ["session", "step", "result"]


async def test_a_job_still_running_is_followed_until_its_feed_closes(client: Client) -> None:
    """A run sits minutes on a handoff with nothing new on its feed: the relay must not give up on it."""
    await claim_conversation_slot(CONVERSATION, JOB_ID)
    await _publish_cards(end=False)
    relaying = asyncio.create_task(relay_job_cards(REQUEST))
    for _ in range(50):
        await asyncio.sleep(0)
    assert not relaying.done()

    await publish_frame_to_job(JOB_ID, _card(RESULT))
    await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)
    await asyncio.wait_for(relaying, timeout=5)

    assert [frame["tool_data"]["data"]["kind"] for frame in client.frames()] == [
        "session",
        "step",
        "result",
    ]


@pytest.mark.parametrize("ending", [BrowserJobFinished(result=RESULT), BrowserJobStopped()])
async def test_a_job_that_ended_with_no_worker_left_is_not_followed_forever(
    ending: BrowserJobFinished | BrowserJobStopped,
) -> None:
    """Its worker died after the ending was recorded, so nothing closes the feed: a headless caller would block for hours."""
    await _publish_cards(end=False)
    await record_ending(JOB_ID, ending)
    seen: list[dict[str, object]] = []

    async def _sink(card: dict[str, object]) -> None:
        seen.append(card)

    async with captured_wide_event() as event:
        await asyncio.wait_for(follow_job_cards(JOB_ID, CONVERSATION, _sink), timeout=5)

    assert len(seen) == 2
    [warning] = event["warnings"]
    assert (
        warning["msg"]
        == f"{LogTag.BROWSER} Browser job ended with no worker left to close its feed"
    )
