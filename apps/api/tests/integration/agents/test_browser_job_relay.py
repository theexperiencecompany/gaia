"""A background job's cards reach the turn that asked for them — live on the wire and persisted on the message.

Real code under test: relay_job_events, the job event feed, make_redis_stream_writer
and the stream session collector. Only Redis and the SSE publish are faked, so
the frames asserted here are the ones the browser card renderer really receives.
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.core.background import redis_writer as rw
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.redis_writer import STREAM_PUBLISH_TASK_NAME
from app.agents.core.background.session import RunKind, create_session
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserSessionSnapshot, BrowserStepSnapshot
from app.services.browser import job_events as job_events_mod, job_relay as relay_mod
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_lifetime import (
    browser_job_deadline_seconds,
    browser_job_ttl_seconds,
)
from app.services.browser.job_relay import relay_job_events
from app.services.browser.job_runner import publish_frame_to_job
from app.utils import background_tasks
from tests._harness.redis_fakes import FakeRedisClient
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.integration

JOB_ID = "job-1"
STREAM_ID = "stream-1"


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> FakeRedisClient:
    client = FakeRedisClient()
    cache = MagicMock()
    cache.client = client
    monkeypatch.setattr(job_events_mod, "redis_cache", cache)
    # The relay's deadline runs on the feed's clock, which only an empty
    # blocking read advances: a relay that never stops ends at its deadline in
    # fake time rather than spinning the test until it is killed.
    monkeypatch.setattr(relay_mod, "monotonic", lambda: client.clock)
    return client


@pytest.fixture
def chunks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    published: list[str] = []
    manager = MagicMock()

    async def _publish_chunk(stream_id: str, chunk: str) -> None:
        assert stream_id == STREAM_ID
        published.append(chunk)

    manager.publish_chunk = _publish_chunk
    manager.is_cancelled = AsyncMock(return_value=False)
    # Both halves of the relay reach the same manager: the writer publishes
    # through it and the relay reads this turn's cancel flag off it.
    monkeypatch.setattr(rw, "stream_manager", manager)
    monkeypatch.setattr(relay_mod, "stream_manager", manager)
    return published


async def _drain_publishes() -> None:
    """Wait out the fire-and-forget XADDs make_redis_stream_writer scheduled."""
    while pending := [
        t for t in background_tasks._background_tasks if t.get_name() == STREAM_PUBLISH_TASK_NAME
    ]:
        await asyncio.gather(*pending, return_exceptions=True)


async def _publish_a_run() -> None:
    """Publish what a worker publishes for a two-card run, then close the feed."""
    await publish_frame_to_job(
        JOB_ID,
        {
            BROWSER_TASK_EVENT: BrowserSessionSnapshot(
                task="book a table", status=BrowserSessionStatus.RUNNING, session_id="sess-1"
            ).model_dump(mode="json")
        },
    )
    await publish_frame_to_job(
        JOB_ID,
        {
            BROWSER_TASK_EVENT: BrowserStepSnapshot(index=1, goal="open the menu").model_dump(
                mode="json"
            )
        },
    )
    await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)


def _frames(chunks: list[str]) -> list[dict[str, Any]]:
    return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]


async def test_every_card_published_before_the_relay_started_still_reaches_the_turn(
    feed: FakeRedisClient, chunks: list[str]
) -> None:
    """The relay reads from 0-0, so a turn that joins late (or after a restart) shows the run from step 1 rather than from wherever it happened to attach."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()

    await relay_job_events(JOB_ID, STREAM_ID)
    await _drain_publishes()

    cards = [f["tool_data"] for f in _frames(chunks)]
    assert [c["tool_name"] for c in cards] == [BROWSER_TASK_EVENT, BROWSER_TASK_EVENT]
    assert [c["data"]["kind"] for c in cards] == ["session", "step"]
    assert cards[1]["data"]["goal"] == "open the menu"


async def test_the_relayed_cards_are_collected_onto_the_turns_message(
    feed: FakeRedisClient, chunks: list[str]
) -> None:
    """The whole reason the worker does not publish to the stream itself: only a writer bound to the session collects the cards, so a reload still shows them."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()

    await relay_job_events(JOB_ID, STREAM_ID)

    entries = drain_executor_tool_data(STREAM_ID)
    assert [e["tool_name"] for e in entries] == [BROWSER_TASK_EVENT, BROWSER_TASK_EVENT]


async def test_the_terminal_frame_ends_the_relay_and_is_never_shown(
    feed: FakeRedisClient, chunks: list[str]
) -> None:
    """A sentinel on the wire would reach the frontend as an unknown tool event; it is the relay's stop signal, not a card."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()

    async with captured_wide_event() as event:
        await relay_job_events(JOB_ID, STREAM_ID)
    await _drain_publishes()

    assert all("browser_job_done" not in chunk for chunk in chunks)
    assert event["browser"] == {"job_id": JOB_ID, "relay_end": "job_finished"}


async def test_cards_published_while_the_relay_reads_continue_from_its_cursor(
    feed: FakeRedisClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run publishes as it goes: each read picks up after the last card, never from the top."""
    create_session(STREAM_ID, RunKind.LIVE)
    read_feed = relay_mod.read_job_events
    reads = 0

    async def _run_publishes_between_reads(job_id: str, cursor: str, block_ms: int) -> Any:
        nonlocal reads
        reads += 1
        if reads == 2:
            await publish_frame_to_job(
                JOB_ID,
                {
                    BROWSER_TASK_EVENT: BrowserStepSnapshot(
                        index=1, goal="open the menu"
                    ).model_dump(mode="json")
                },
            )
            await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)
        return await read_feed(job_id, cursor, block_ms)

    monkeypatch.setattr(relay_mod, "read_job_events", _run_publishes_between_reads)
    await publish_frame_to_job(
        JOB_ID,
        {
            BROWSER_TASK_EVENT: BrowserSessionSnapshot(
                task="book a table", status=BrowserSessionStatus.RUNNING, session_id="sess-1"
            ).model_dump(mode="json")
        },
    )

    await relay_job_events(JOB_ID, STREAM_ID)
    await _drain_publishes()

    assert [f["tool_data"]["data"]["kind"] for f in _frames(chunks)] == ["session", "step"]


async def test_a_cancelled_turn_stops_the_relay(
    feed: FakeRedisClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user stopped this turn; the worker's own cancel path ends the run, and nothing more belongs on a stream nobody is reading."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()
    monkeypatch.setattr(
        relay_mod.stream_manager,
        "is_cancelled",
        AsyncMock(side_effect=lambda stream_id: stream_id == STREAM_ID),
    )

    async with captured_wide_event() as event:
        await relay_job_events(JOB_ID, STREAM_ID)
    await _drain_publishes()

    assert chunks == []
    assert event["browser"] == {"job_id": JOB_ID, "relay_end": "turn_cancelled"}


async def test_a_feed_that_cannot_be_read_never_takes_the_turn_down_with_it(
    feed: FakeRedisClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay runs as fire-and-forget background work beside the turn; an unhandled error here would surface as a failed turn instead of a missing card."""
    create_session(STREAM_ID, RunKind.LIVE)
    fake_log = MagicMock()
    monkeypatch.setattr(relay_mod, "log", fake_log)

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(relay_mod, "read_job_events", _boom)

    await relay_job_events(JOB_ID, STREAM_ID)

    fake_log.error.assert_called_once_with(
        f"{LogTag.BROWSER} Browser job relay stopped",
        error_type="RuntimeError",
        error="redis down",
        browser={"job_id": JOB_ID},
    )
    assert chunks == []


async def test_the_relay_waits_out_the_longest_run_the_worker_allows(
    feed: FakeRedisClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that sat in handoffs for hours still ends on the turn: the relay must not give up while the worker would still let it run."""
    create_session(STREAM_ID, RunKind.LIVE)
    read_feed = relay_mod.read_job_events

    async def _read_after_a_long_wait(job_id: str, cursor: str, block_ms: int) -> Any:
        if feed.clock == 0.0:
            # Nothing yet: the run is waiting on a human, almost as long as it may.
            feed.clock = browser_job_deadline_seconds() - 1.0
            return []
        return await read_feed(job_id, cursor, block_ms)

    monkeypatch.setattr(relay_mod, "read_job_events", _read_after_a_long_wait)
    await _publish_a_run()

    await relay_job_events(JOB_ID, STREAM_ID)
    await _drain_publishes()

    assert len(_frames(chunks)) == 2


async def test_the_relay_stops_reading_at_its_deadline_and_says_so(
    feed: FakeRedisClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The feed expires then; a card that lands at that instant reaches no one, and the log shows why."""
    create_session(STREAM_ID, RunKind.LIVE)
    budget = browser_job_ttl_seconds()
    read_feed = relay_mod.read_job_events

    async def _card_lands_at_the_deadline(job_id: str, cursor: str, block_ms: int) -> Any:
        if feed.clock == budget:
            await _publish_a_run()
        return await read_feed(job_id, cursor, block_ms)

    monkeypatch.setattr(relay_mod, "read_job_events", _card_lands_at_the_deadline)
    fake_log = MagicMock()
    monkeypatch.setattr(relay_mod, "log", fake_log)

    await relay_job_events(JOB_ID, STREAM_ID)

    assert chunks == []
    fake_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Browser job relay gave up before the job finished",
        browser={"job_id": JOB_ID},
        budget_seconds=budget,
    )
