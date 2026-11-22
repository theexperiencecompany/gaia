"""A detached run's stream: opened as a queued session once logged, dropped when it closes."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background.executor_queue import run_is_lost
from app.agents.core.background.folded_stream import close_folded_stream, open_folded_stream
from app.agents.core.background.session import (
    RunKind,
    create_session,
    get_session,
    teardown_session,
)
from app.services.conversation.tool_cards import FoldedCards

pytestmark = pytest.mark.unit

FOLDED = "app.agents.core.background.folded_stream"
STREAM = "subagent-stream-1"


@pytest.fixture(autouse=True)
def no_session() -> Iterator[None]:
    teardown_session(STREAM)
    yield
    teardown_session(STREAM)


@contextmanager
def _closing() -> Iterator[None]:
    with (
        patch(f"{FOLDED}.stop_requested", new=AsyncMock(return_value=False)),
        patch(f"{FOLDED}.work_cards", new=AsyncMock(return_value=FoldedCards())),
        patch(f"{FOLDED}.record_work_finished", new=AsyncMock()),
    ):
        yield


async def test_a_logged_run_opens_a_queued_session_on_its_own_stream() -> None:
    with patch(f"{FOLDED}.record_work_carried", new=AsyncMock(return_value=True)):
        assert await open_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")

    session = get_session(STREAM)
    assert session is not None
    assert session.kind == RunKind.QUEUED


async def test_a_run_the_log_refuses_opens_no_session() -> None:
    with patch(f"{FOLDED}.record_work_carried", new=AsyncMock(return_value=False)):
        assert not await open_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")

    assert get_session(STREAM) is None


async def test_closing_the_stream_drops_its_session() -> None:
    with patch(f"{FOLDED}.record_work_carried", new=AsyncMock(return_value=True)):
        await open_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")
    with _closing():
        await close_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")

    assert get_session(STREAM) is None


@pytest.mark.usefixtures("fake_redis")
async def test_an_open_stream_is_alive_to_the_sweep_for_its_conversation_and_task_only() -> None:
    with patch(f"{FOLDED}.record_work_carried", new=AsyncMock(return_value=True)):
        await open_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")

    assert not await run_is_lost("conv-1", STREAM)
    assert await run_is_lost("conv-2", STREAM)
    assert await run_is_lost("conv-1", "another-stream")


@pytest.mark.usefixtures("fake_redis")
async def test_closing_the_stream_stops_its_liveness_beat() -> None:
    with patch(f"{FOLDED}.record_work_carried", new=AsyncMock(return_value=True)):
        await open_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")
    session = get_session(STREAM)
    assert session is not None and session.alive is not None
    beat = session.alive
    with _closing():
        await close_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")
    await asyncio.sleep(0)

    assert beat.cancelled()


@pytest.mark.parametrize("opened", [False, True], ids=["no session", "session with no beat"])
async def test_closing_a_stream_with_nothing_beating_still_ends_it(opened: bool) -> None:
    if opened:
        create_session(STREAM, RunKind.QUEUED)
    with _closing():
        await close_folded_stream(STREAM, conversation_id="conv-1", user_id="u1")

    assert get_session(STREAM) is None
