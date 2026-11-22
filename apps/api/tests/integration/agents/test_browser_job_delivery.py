"""One worker-side browser run reaches every surface as cards: the web turn's stream and the bot's follower read the same ones.

Real code under test: execute_browser_job with its ProgressEmitter and
BrowserThreadMirror, the job event feed, follow_job_cards and the session collector.
Faked: the browser itself (a scripted stand-in for BrowserTaskRunner), the browser host
session, Redis, and the outbound bot queue (to prove nothing reaches it). So this proves
the wiring from one card snapshot to the cards every surface renders; it does not prove
Browser-Use produces those snapshots, nor the bot follower that renders them.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from app.agents.core.background import session_writer as sw
from app.agents.core.background.session import RunKind, create_session, teardown_session
from app.constants.browser import (
    BROWSER_TASK_EVENT,
    BrowserEngine,
    BrowserSessionStatus,
    HandoffStatus,
)
from app.constants.chat import SourceCategory
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserAction,
    BrowserActionOutput,
    BrowserCardSnapshot,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services import outbound_delivery as outbound_mod
from app.services.browser import job_runner as jr
from app.services.browser.job_relay import follow_job_cards
from app.services.browser.job_runner import execute_browser_job
from app.services.browser.jobs import put_job_state
from app.services.browser.ledger import RunLedger
from app.services.conversation.work_deltas import WorkDeltas, work_cards

pytestmark = pytest.mark.integration

JOB_ID = "job-7"
STREAM_ID = "stream-7"
LIVE_VIEW_LINK = "https://gaia.test/live/abc"
SHOT_URL = "https://cdn.test/browser-step-1.png"
#: A plain progress line the run sends mid-way, as the stall watcher does.
STALL_NOTE = "Still waiting on the page to load."

EmitFn = Callable[[BrowserCardSnapshot], Awaitable[None]]


class _ScriptedBrowser:
    """A browser run with no browser: one session, one step with a result, then done.

    Stands in for BrowserTaskRunner at the seam execute_browser_job builds it,
    driving the same callbacks in the same order the real runner does.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._callbacks = kwargs["callbacks"]
        self.session = kwargs["session"]
        self.used_fallback = False
        self.ledger = RunLedger()
        #: The run below succeeds, so it gives no reason it failed.
        self.failure = None

    async def run(self, task: str) -> BrowserResultSnapshot:
        emit: EmitFn = self._callbacks.emit
        await emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self.session.session_id,
            )
        )
        await emit(
            BrowserStepSnapshot(
                index=1,
                goal="open the booking page",
                actions=[
                    BrowserAction(
                        name="go_to_url",
                        inputs={"url": "https://example.test/book"},
                        target="example.test",
                    )
                ],
                url="https://example.test/book",
                screenshot=SHOT_URL,
            )
        )
        assert self._callbacks.action_results is not None
        await self._callbacks.action_results(
            1, [BrowserActionOutput(position=0, output="opened example.test/book")]
        )
        result = BrowserResultSnapshot(
            status=BrowserSessionStatus.COMPLETED,
            success=True,
            summary="Table booked for 7pm.",
            steps=1,
        )
        await self._callbacks.note(STALL_NOTE)
        await emit(result)
        return result


@pytest.fixture
async def redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """One Redis behind the job's state and its card feed, as in production."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.db.redis.redis_cache.redis", client)
    yield client
    teardown_session(STREAM_ID)
    await client.aclose()


@pytest.fixture
def chunks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Every frame the relay collected on this turn's stream."""
    collected: list[dict[str, object]] = []

    def _collect(stream_id: str, data: dict[str, object]) -> None:
        assert stream_id == STREAM_ID
        collected.append(data)

    monkeypatch.setattr(sw, "collect_frame", _collect)
    return collected


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything outside the process: the host session, the engine choice, the history write."""
    session = MagicMock(
        session_id="sess-7",
        engine=BrowserEngine.CHROMIUM,
    )

    @asynccontextmanager
    async def _session(**kwargs: Any) -> AsyncIterator[MagicMock]:
        yield session

    monkeypatch.setattr(jr, "browser_session", _session)
    # Chrome, the default engine: the user has not opted into Obscura.
    monkeypatch.setattr(jr, "is_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(jr, "BrowserTaskRunner", _ScriptedBrowser)
    monkeypatch.setattr(jr, "record_browser_task", AsyncMock())
    monkeypatch.setattr(jr, "capture", MagicMock())


def _request(**overrides: Any) -> BrowserJobRequest:
    return BrowserJobRequest(
        job_id=JOB_ID,
        tool_call_id="call-7",
        user_id="6812f0b3c9a14e2b7d5a91c7",
        conversation_id="conv-7",
        task="book a table for two at 7pm",
        in_background=False,
        stream_id=STREAM_ID,
        **overrides,
    )


async def _run_and_relay(request: BrowserJobRequest) -> None:
    """Run the job, which closes its own feed, then follow the feed onto the turn's stream."""
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.QUEUED))
    await execute_browser_job(request)
    deltas = WorkDeltas(request.conversation_id, STREAM_ID)

    def publish(data: dict[str, object]) -> None:
        sw.collect_frame(STREAM_ID, data)
        deltas(data)

    await follow_job_cards(request.job_id, request.conversation_id, publish)
    await deltas.drain()


def _shape(frame: dict[str, Any]) -> str:
    """Name a wire frame the way the frontend reads it: the card name, or the event key."""
    key = next(iter(frame))
    if key == "tool_data":
        name: str = frame["tool_data"]["tool_name"]
        return name
    return key


async def test_a_web_turn_receives_the_whole_run_as_cards_and_a_browser_thread(
    redis: fakeredis.aioredis.FakeRedis, chunks: list[dict[str, Any]], browser: None
) -> None:
    """The run happens in a worker with no stream of its own; what the card renderer and the tool thread receive has to be indistinguishable from a run that never left the turn."""
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(_request())

    frames = chunks
    assert [_shape(frame) for frame in frames] == [
        BROWSER_TASK_EVENT,
        "subagent_start",
        BROWSER_TASK_EVENT,
        "tool_calls_data",
        "tool_output",
        BROWSER_TASK_EVENT,
        BROWSER_TASK_EVENT,
        "subagent_end",
    ]
    cards = [f["tool_data"]["data"] for f in frames if _shape(f) == BROWSER_TASK_EVENT]
    assert [card["kind"] for card in cards] == ["session", "step", "session", "result"]
    assert cards[1]["goal"] == "open the booking page"
    assert cards[2]["detail"] == STALL_NOTE
    assert cards[3]["summary"] == "Table booked for 7pm."


async def test_the_runs_cards_are_collected_onto_the_turns_message_under_one_group(
    redis: fakeredis.aioredis.FakeRedis, chunks: list[dict[str, Any]], browser: None
) -> None:
    """Live SSE is only half of it: without the in-process collector the cards are gone on reload, and an action row orphaned from its group renders outside the browser thread."""
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(_request())

    entries = (await work_cards(_request().conversation_id, [STREAM_ID])).tool_data
    cards = [e for e in entries if e["tool_name"] == BROWSER_TASK_EVENT]
    assert [card["data"]["kind"] for card in cards] == ["session", "step", "session", "result"]
    groups = [e for e in entries if e["tool_name"] == "subagent_group"]
    assert len(groups) == 1
    assert groups[0]["data"]["subagent_id"] == "browser:call-7"
    group_calls = groups[0]["data"]["tool_calls"]
    assert [call["tool_name"] for call in group_calls] == ["go_to_url"]
    assert group_calls[0]["output"] == "opened example.test/book"


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the bot platform's outbound queue itself: every envelope the backend enqueued, decoded."""
    envelopes: list[dict[str, Any]] = []

    class _Publisher:
        async def publish_outbound(
            self, queue_name: str, body: bytes, *, expiration: int | None = None
        ) -> None:
            envelopes.append(json.loads(body))

    monkeypatch.setattr(
        outbound_mod, "get_rabbitmq_publisher", AsyncMock(return_value=_Publisher())
    )
    monkeypatch.setattr(jr, "create_live_view_link", AsyncMock(return_value=LIVE_VIEW_LINK))
    return envelopes


class _ScriptedBrowserWithHandoff(_ScriptedBrowser):
    """The scripted run, pausing once for the user to take over before it finishes."""

    async def run(self, task: str) -> BrowserResultSnapshot:
        await self._callbacks.emit(
            BrowserHandoffSnapshot(
                handoff_id="handoff-7",
                reason="Sign in to finish the booking.",
                session_id=self.session.session_id,
                status=HandoffStatus.PENDING,
            )
        )
        return await super().run(task)


def _handoff_cards(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        f["tool_data"]["data"]
        for f in chunks
        if _shape(f) == BROWSER_TASK_EVENT and f["tool_data"]["data"]["kind"] == "handoff"
    ]


async def test_a_bot_run_carries_its_live_link_on_the_cards_and_sends_nothing_over_the_bot_queue(
    redis: fakeredis.aioredis.FakeRedis,
    chunks: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    browser: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bot's follower renders the run from the same cards web shows; a second channel ordered its posts apart from the reply."""
    monkeypatch.setattr(jr, "BrowserTaskRunner", _ScriptedBrowserWithHandoff)
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(
        _request(
            source_category=SourceCategory.BOT.value,
            conversation_source=ConversationSource.DISCORD,
        )
    )

    [handoff] = _handoff_cards(chunks)
    assert handoff["live_view_url"] == LIVE_VIEW_LINK
    assert queue == []


async def test_a_web_run_mints_no_live_link(
    redis: fakeredis.aioredis.FakeRedis,
    chunks: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    browser: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A web user takes over in the card's own live view; a capability link minted for them is one more key to the browser."""
    monkeypatch.setattr(jr, "BrowserTaskRunner", _ScriptedBrowserWithHandoff)
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(_request())

    [handoff] = _handoff_cards(chunks)
    assert handoff["live_view_url"] is None
    assert queue == []
