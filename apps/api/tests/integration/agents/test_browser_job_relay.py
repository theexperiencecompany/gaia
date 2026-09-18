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
from app.schemas.browser import BrowserSessionSnapshot, BrowserStepSnapshot
from app.services.browser import job_events as job_events_mod, job_relay as relay_mod
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_relay import relay_job_events
from app.services.browser.job_runner import publish_frame_to_job
from app.utils import background_tasks

pytestmark = pytest.mark.integration

JOB_ID = "job-1"
STREAM_ID = "stream-1"


class _FakeStreamClient:
    """Enough Redis stream for one job's feed: monotonic ids, reads after a cursor."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._seq = 0

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self._seq += 1
        entry_id = f"{self._seq}-0"
        self.streams.setdefault(name, []).append((entry_id, dict(fields)))
        return entry_id

    async def expire(self, name: str, time: int) -> bool:
        return True

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        results = []
        for name, cursor in streams.items():
            after = [e for e in self.streams.get(name, []) if _order(e[0]) > _order(cursor)]
            if after:
                results.append((name, after))
        return results


def _order(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    return int(ms), int(seq or 0)


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> _FakeStreamClient:
    client = _FakeStreamClient()
    cache = MagicMock()
    cache.client = client
    monkeypatch.setattr(job_events_mod, "redis_cache", cache)
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
    feed: _FakeStreamClient, chunks: list[str]
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
    feed: _FakeStreamClient, chunks: list[str]
) -> None:
    """The whole reason the worker does not publish to the stream itself: only a writer bound to the session collects the cards, so a reload still shows them."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()

    await relay_job_events(JOB_ID, STREAM_ID)

    entries = drain_executor_tool_data(STREAM_ID)
    assert [e["tool_name"] for e in entries] == [BROWSER_TASK_EVENT, BROWSER_TASK_EVENT]


async def test_the_terminal_frame_ends_the_relay_and_is_never_shown(
    feed: _FakeStreamClient, chunks: list[str]
) -> None:
    """A sentinel on the wire would reach the frontend as an unknown tool event; it is the relay's stop signal, not a card."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()

    await asyncio.wait_for(relay_job_events(JOB_ID, STREAM_ID), timeout=5)
    await _drain_publishes()

    assert all("browser_job_done" not in chunk for chunk in chunks)


async def test_a_cancelled_turn_stops_the_relay(
    feed: _FakeStreamClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user stopped this turn; the worker's own cancel path ends the run, and nothing more belongs on a stream nobody is reading."""
    create_session(STREAM_ID, RunKind.LIVE)
    await _publish_a_run()
    monkeypatch.setattr(relay_mod.stream_manager, "is_cancelled", AsyncMock(return_value=True))

    await asyncio.wait_for(relay_job_events(JOB_ID, STREAM_ID), timeout=5)
    await _drain_publishes()

    assert chunks == []


async def test_a_feed_that_cannot_be_read_never_takes_the_turn_down_with_it(
    feed: _FakeStreamClient, chunks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay runs as fire-and-forget background work beside the turn; an unhandled error here would surface as a failed turn instead of a missing card."""
    create_session(STREAM_ID, RunKind.LIVE)
    fake_log = MagicMock()
    monkeypatch.setattr(relay_mod, "log", fake_log)

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(relay_mod, "read_job_events", _boom)

    await relay_job_events(JOB_ID, STREAM_ID)

    fake_log.error.assert_called_once()
    assert chunks == []
