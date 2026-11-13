"""A background job is logged work of its own: started when its relay opens, finished with its cards.

Real code under test: relay_job_cards and follow_job_cards, the job feed, the
detached stream's session and its close (folded_stream), the work log through
the conversation reducer, and the named-work cancel, over fakeredis. Faked: the
SSE publish and the in-memory log store, so the frames and entries asserted here
are what the client and the log really get.
"""

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from app.agents.core.background import executor_queue, folded_stream, redis_writer as rw
from app.agents.core.background.work_cancel import cancel_named_work
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus, JobEnding
from app.constants.log_tags import LogTag
from app.models.conversation_log_models import WorkFinished, WorkOutcome, WorkStarted
from app.schemas.browser import BrowserResultSnapshot, BrowserSessionSnapshot, BrowserStepSnapshot
from app.schemas.browser_job import BrowserJobFinished, BrowserJobRequest, BrowserJobStopped
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_relay import follow_job_cards, relay_job_cards
from app.services.browser.job_runner import publish_frame_to_job
from app.services.browser.jobs import claim_conversation_slot, done_state, record_ending
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.work_log import record_user_stop
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import user
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, USER, Runtime

pytestmark = pytest.mark.integration

JOB_ID = "job-1"
TASK_ID = f"browser_{JOB_ID}"
REQUEST = BrowserJobRequest(
    job_id=JOB_ID,
    tool_call_id="call-1",
    user_id=USER,
    conversation_id=CONVERSATION,
    task="book",
    in_background=True,
    message_id="bot-msg-1",
)
RESULT = BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")


@pytest.fixture(autouse=True)
async def redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.db.redis.redis_cache.redis", client)
    yield client
    await client.aclose()


@pytest.fixture
async def runtime() -> Runtime:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    return runtime


class Client:
    """What the user's client saw of the relay's stream."""

    def __init__(self) -> None:
        self.chunks: dict[str, list[str]] = {}

    def frames(self) -> list[dict[str, Any]]:
        [stream] = self.chunks.values()
        return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in stream]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, runtime: Runtime) -> Client:
    seen = Client()

    async def _publish_chunk(stream_id: str, chunk: str) -> None:
        seen.chunks.setdefault(stream_id, []).append(chunk)

    manager = MagicMock()
    manager.publish_chunk = _publish_chunk
    monkeypatch.setattr(rw, "stream_manager", manager)
    monkeypatch.setattr(executor_queue, "StreamManager", AsyncMock())
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


async def test_the_job_is_logged_work_whose_finish_carries_its_cards_and_wakes_nothing(
    client: Client, runtime: Runtime
) -> None:
    await _publish_cards(end=True)

    await relay_job_cards(REQUEST)

    assert [frame["tool_data"]["data"]["kind"] for frame in client.frames()] == [
        "session",
        "step",
        "result",
    ]
    [_, started, ended] = await runtime.entries()
    assert isinstance(started.entry, WorkStarted)
    assert (started.entry.task_id, started.entry.detached) == (TASK_ID, True)
    assert isinstance(ended.entry, WorkFinished)
    assert (ended.entry.task_id, ended.entry.outcome) == (TASK_ID, WorkOutcome.DONE)
    assert [card["data"]["kind"] for card in ended.entry.tool_data] == ["session", "step", "result"]
    state = await runtime.log.state(CONVERSATION, USER)
    assert (state.work, state.finished_work) == ((), ())


async def test_a_stop_while_the_job_runs_cancels_it(client: Client, runtime: Runtime) -> None:
    await claim_conversation_slot(CONVERSATION, JOB_ID)
    await _publish_cards(end=False)
    relaying = asyncio.create_task(relay_job_cards(REQUEST))
    for _ in range(50):
        await asyncio.sleep(0)
    live = await runtime.log.state(CONVERSATION, USER)
    assert [work.task_id for work in live.work] == [TASK_ID]

    await record_user_stop(CONVERSATION, USER, "s1")
    [cancel] = [call.argument for call in runtime.effects.calls if call.name == "cancel_work"]
    assert isinstance(cancel, tuple)
    assert TASK_ID in cancel
    cancelled = await cancel_named_work(CONVERSATION, USER, cancel, approval_ids=())

    assert list(cancelled.browser_jobs) == [JOB_ID]
    ending = await done_state(JOB_ID)
    assert ending is not None
    assert ending.ending is JobEnding.STOPPED
    relaying.cancel()


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
