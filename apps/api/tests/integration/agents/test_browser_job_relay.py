"""A background job's cards reach the turn that started it, and its result waits for that turn.

Real code under test: relay_job_events, the job feed, the result hold the worker
waits on, publish_to_stream and the stream session collector, over fakeredis.
Only the SSE publish is faked, so the frames asserted here are the ones the
browser card renderer really receives.
"""

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from app.agents.core.background import redis_writer as rw
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.session import (
    RunKind,
    create_session,
    signal_executor_done,
    teardown_session,
)
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.schemas.browser import BrowserResultSnapshot, BrowserSessionSnapshot, BrowserStepSnapshot
from app.services.browser import job_relay as relay_mod
from app.services.browser.job_events import (
    JOB_GUIDANCE_FRAME,
    JOB_TERMINAL_FRAME,
    publish_job_event,
)
from app.services.browser.job_relay import relay_job_events
from app.services.browser.job_runner import publish_frame_to_job
from app.services.browser.jobs import await_result_unclaimed, request_job_cancel
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.integration

JOB_ID = "job-1"
STREAM_ID = "stream-1"


@pytest.fixture(autouse=True)
async def redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.db.redis.redis_cache.redis", client)
    yield client
    teardown_session(STREAM_ID)
    await client.aclose()


@pytest.fixture
def chunks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    published: list[str] = []

    async def _publish_chunk(stream_id: str, chunk: str) -> None:
        assert stream_id == STREAM_ID
        published.append(chunk)

    manager = MagicMock()
    manager.publish_chunk = _publish_chunk
    monkeypatch.setattr(rw, "stream_manager", manager)
    return published


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
    # A signal to a join, which the turn's stream must never show.
    await publish_job_event(JOB_ID, JOB_GUIDANCE_FRAME)
    if end:
        await publish_frame_to_job(
            JOB_ID,
            _card(
                BrowserResultSnapshot(
                    status=BrowserSessionStatus.COMPLETED, success=True, summary="ok"
                )
            ),
        )
        await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)


async def _let_the_loop_run() -> None:
    """Hand the event loop over for long enough that anything not blocked on an event moves on."""
    for _ in range(50):
        await asyncio.sleep(0)


def _kinds(chunks: list[str]) -> list[str]:
    frames = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]
    return [frame["tool_data"]["data"]["kind"] for frame in frames]


async def test_every_card_reaches_the_turn_in_order_and_lands_on_its_message(
    chunks: list[str],
) -> None:
    """Read from the top, so a late relay still shows step 1; collected, so a reload still shows the cards; the end of the feed is a signal, never a card."""
    create_session(STREAM_ID, RunKind.LIVE)
    signal_executor_done(STREAM_ID)
    await _publish_cards(end=True)

    async with captured_wide_event() as event:
        await relay_job_events(JOB_ID, STREAM_ID)

    assert event["browser"] == {"job_id": JOB_ID, "relay_end": "job_finished"}
    assert "errors" not in event

    assert _kinds(chunks) == ["session", "step", "result"]
    assert all("browser_job_done" not in chunk for chunk in chunks)
    assert [entry["data"]["kind"] for entry in drain_executor_tool_data(STREAM_ID)] == [
        "session",
        "step",
        "result",
    ]


async def test_the_result_waits_for_the_run_that_started_it_and_no_longer(
    chunks: list[str],
) -> None:
    """The executor that started the run may still join and speak it; once that run ends the worker speaks it at once, not after a guessed grace."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_cards(end=True)
    relay = asyncio.create_task(relay_job_events(JOB_ID, STREAM_ID))
    await _let_the_loop_run()
    worker = asyncio.create_task(await_result_unclaimed(JOB_ID))
    await _let_the_loop_run()

    assert not worker.done(), "the worker spoke over a run that could still join"

    signal_executor_done(STREAM_ID)
    await asyncio.wait_for(asyncio.gather(relay, worker), timeout=2)


async def test_a_turn_that_ended_stops_the_relay_but_a_stopped_job_is_followed_to_its_card(
    chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody reads a finished turn's stream; a stop ends the turn too, yet the stopped card is what tells the user it stopped."""
    await _publish_cards(end=False)
    async with captured_wide_event() as event:
        await relay_job_events(JOB_ID, STREAM_ID)
    assert _kinds(chunks) == ["session", "step"]
    assert event["browser"] == {"job_id": JOB_ID, "relay_end": "turn_ended"}

    chunks.clear()
    await request_job_cancel(JOB_ID)
    first_read = asyncio.Event()
    read_feed = relay_mod.read_job_events

    async def _read_then_mark(job_id: str, cursor: str) -> Any:
        events = await read_feed(job_id, cursor)
        first_read.set()
        return events

    monkeypatch.setattr(relay_mod, "read_job_events", _read_then_mark)
    relay = asyncio.create_task(relay_job_events(JOB_ID, STREAM_ID))
    # Past its first read, the turn is over: only the stop keeps the relay going.
    await first_read.wait()
    await publish_frame_to_job(
        JOB_ID,
        _card(
            BrowserResultSnapshot(status=BrowserSessionStatus.CANCELLED, success=False, summary="x")
        ),
    )
    await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)
    await asyncio.wait_for(relay, timeout=5)

    assert _kinds(chunks)[-1] == "result"


async def test_a_feed_that_cannot_be_read_never_takes_the_turn_down_with_it(
    chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay runs beside the turn; an unhandled error here would surface as a failed turn instead of a missing card."""
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


async def test_a_turn_still_streaming_is_relayed_to_even_with_no_executor_run_on_it(
    chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await stream_manager.start_stream(STREAM_ID, "conv-1", "user-1")
    await _publish_cards(end=False)
    first_read = asyncio.Event()
    read_feed = relay_mod.read_job_events

    async def _read_then_mark(job_id: str, cursor: str) -> Any:
        events = await read_feed(job_id, cursor)
        first_read.set()
        return events

    monkeypatch.setattr(relay_mod, "read_job_events", _read_then_mark)
    relay = asyncio.create_task(relay_job_events(JOB_ID, STREAM_ID))
    await first_read.wait()
    await publish_frame_to_job(
        JOB_ID,
        _card(
            BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")
        ),
    )
    await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)
    await asyncio.wait_for(relay, timeout=5)

    assert _kinds(chunks) == ["session", "step", "result"]


async def test_the_hold_is_re_armed_while_the_run_lives(
    chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hold lapses by itself if the API dies, so a live run re-arms it on a beat."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_cards(end=True)
    monkeypatch.setattr(relay_mod, "BROWSER_JOB_JOINER_REFRESH_SECONDS", 0.01)
    holds: list[tuple[str, str]] = []
    re_armed = asyncio.Event()
    hold = relay_mod.hold_result_for_run

    async def _counted(job_id: str, stream_id: str) -> None:
        holds.append((job_id, stream_id))
        await hold(job_id, stream_id)
        if len(holds) == 3:
            re_armed.set()

    monkeypatch.setattr(relay_mod, "hold_result_for_run", _counted)
    relay = asyncio.create_task(relay_job_events(JOB_ID, STREAM_ID))

    await asyncio.wait_for(re_armed.wait(), timeout=5)
    signal_executor_done(STREAM_ID)
    await asyncio.wait_for(relay, timeout=5)

    assert set(holds) == {(JOB_ID, STREAM_ID)}
    await asyncio.wait_for(await_result_unclaimed(JOB_ID), timeout=2)


async def test_a_relay_past_the_feeds_life_gives_up_and_says_so(
    chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_cards(end=False)
    monkeypatch.setattr(relay_mod, "browser_job_ttl_seconds", lambda: 0.05)

    async with captured_wide_event() as event:
        await relay_job_events(JOB_ID, STREAM_ID)

    [warning] = event["warnings"]
    assert "gave up before the job finished" in warning["msg"]
    assert warning["browser"] == {"job_id": JOB_ID}


async def test_a_run_still_going_is_relayed_to_even_with_its_turn_stream_gone(
    chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executor that started the job still collects onto its message after the live stream ended."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_cards(end=False)
    first_read = asyncio.Event()
    read_feed = relay_mod.read_job_events

    async def _read_then_mark(job_id: str, cursor: str) -> Any:
        events = await read_feed(job_id, cursor)
        first_read.set()
        return events

    monkeypatch.setattr(relay_mod, "read_job_events", _read_then_mark)
    relay = asyncio.create_task(relay_job_events(JOB_ID, STREAM_ID))
    await first_read.wait()
    await publish_frame_to_job(
        JOB_ID,
        _card(
            BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")
        ),
    )
    await publish_job_event(JOB_ID, JOB_TERMINAL_FRAME)
    signal_executor_done(STREAM_ID)
    await asyncio.wait_for(relay, timeout=5)

    assert _kinds(chunks) == ["session", "step", "result"]
