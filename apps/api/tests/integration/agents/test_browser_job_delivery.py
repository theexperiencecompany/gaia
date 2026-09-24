"""One worker-side browser run reaches both audiences: the web turn's stream and the bot platform.

Real code under test: execute_browser_job with its ProgressEmitter and
BrowserThreadMirror, the job event feed, relay_job_events, make_redis_stream_writer
and BotProgressDelivery. Faked: the browser itself (a scripted stand-in for
BrowserTaskRunner), the browser host session, Redis, and the outbound bot queue.
So this proves the wiring from one card snapshot to every surface that renders
it; it does not prove Browser-Use produces those snapshots.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.core.background import redis_writer as rw
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.redis_writer import STREAM_PUBLISH_TASK_NAME
from app.agents.core.background.session import RunKind, create_session
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus, HandoffStatus
from app.constants.chat import SourceCategory
from app.models.bot_models import BotSessionDocument
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
from app.schemas.browser_job import BrowserJobRequest
from app.services import outbound_delivery as outbound_mod, platform_message_service
from app.services.browser import (
    bot_delivery as bot_mod,
    job_events as job_events_mod,
    job_relay as relay_mod,
    job_runner as jr,
    jobs as jobs_mod,
)
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_relay import relay_job_events
from app.services.browser.job_runner import execute_browser_job
from app.utils import background_tasks
from tests._harness.redis_fakes import FakeRedisCache

pytestmark = pytest.mark.integration

JOB_ID = "job-7"
STREAM_ID = "stream-7"
LIVE_VIEW_LINK = "https://gaia.test/live/abc"
SHOT_URL = "https://cdn.test/browser-step-1.png"
#: A plain progress line the run sends mid-way, as the stall watcher does.
STALL_NOTE = "Still waiting on the page to load."
#: Where the user's DMs land, per their platform link.
DM_ID = "discord-user-7"
#: The group channel the request was sent from.
GROUP_CHANNEL_ID = "discord-channel-42"

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

    async def run(self, task: str) -> BrowserResultSnapshot:
        emit: EmitFn = self._callbacks.emit
        await emit(
            BrowserSessionSnapshot(
                task=task,
                status=BrowserSessionStatus.RUNNING,
                session_id=self.session.session_id,
                live_view_url=self.session.live_view_url,
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
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedisCache:
    """One Redis behind the job's state and its card feed, as in production."""
    cache = FakeRedisCache()
    monkeypatch.setattr(jobs_mod, "redis_cache", cache)
    monkeypatch.setattr(job_events_mod, "redis_cache", cache)
    # The relay's deadline on the feed's fake clock: a relay that misses its stop
    # frame ends at the deadline in fake time instead of spinning the test.
    monkeypatch.setattr(relay_mod, "monotonic", lambda: cache.client.clock)
    return cache


@pytest.fixture
def chunks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every SSE chunk the relay's writer published for this turn."""
    published: list[str] = []
    manager = MagicMock()

    async def _publish_chunk(stream_id: str, chunk: str) -> None:
        assert stream_id == STREAM_ID
        published.append(chunk)

    manager.publish_chunk = _publish_chunk
    manager.is_cancelled = AsyncMock(return_value=False)
    monkeypatch.setattr(rw, "stream_manager", manager)
    monkeypatch.setattr(relay_mod, "stream_manager", manager)
    monkeypatch.setattr(jr, "stream_manager", manager)
    return published


@pytest.fixture
def outbound(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Capture the bot platform's queue: what a Discord user would actually receive."""
    sent: dict[str, list[Any]] = {"messages": [], "photos": []}

    async def _message(platform: Any, user_id: str, blocks: list[str]) -> bool:
        sent["messages"].append((platform, user_id, list(blocks)))
        return True

    async def _photo(platform: Any, user_id: str, url: str, **kwargs: Any) -> bool:
        sent["photos"].append((platform, user_id, url, kwargs.get("caption")))
        return True

    monkeypatch.setattr(bot_mod, "publish_outbound_message", _message)
    monkeypatch.setattr(bot_mod, "publish_outbound_photo", _photo)
    monkeypatch.setattr(bot_mod, "create_live_view_link", AsyncMock(return_value=LIVE_VIEW_LINK))
    return sent


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything outside the process: the host session, the browser LLM, the history write."""
    session = MagicMock(session_id="sess-7", live_view_url="https://host.test/live/sess-7")

    @asynccontextmanager
    async def _session(**kwargs: Any) -> AsyncIterator[MagicMock]:
        yield session

    monkeypatch.setattr(jr, "browser_session", _session)
    monkeypatch.setattr(jr, "build_browser_llm", lambda **_: object())
    monkeypatch.setattr(jr, "BrowserTaskRunner", _ScriptedBrowser)
    monkeypatch.setattr(jr, "record_browser_task", AsyncMock())
    monkeypatch.setattr(jr, "capture_event", MagicMock())


def _request(**overrides: Any) -> BrowserJobRequest:
    return BrowserJobRequest(
        job_id=JOB_ID,
        user_id="user-7",
        conversation_id="conv-7",
        task="book a table for two at 7pm",
        stream_id=STREAM_ID,
        **overrides,
    )


async def _run_and_relay(request: BrowserJobRequest) -> None:
    """Run the job, close its feed the way the worker does, then replay it onto the turn."""
    await execute_browser_job(request)
    await publish_job_event(request.job_id, JOB_TERMINAL_FRAME)
    await relay_job_events(request.job_id, STREAM_ID)
    while pending := [
        task
        for task in background_tasks._background_tasks
        if task.get_name() == STREAM_PUBLISH_TASK_NAME
    ]:
        await asyncio.gather(*pending, return_exceptions=True)


def _frames(chunks: list[str]) -> list[dict[str, Any]]:
    return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]


def _shape(frame: dict[str, Any]) -> str:
    """Name a wire frame the way the frontend reads it: the card name, or the event key."""
    key = next(iter(frame))
    if key == "tool_data":
        name: str = frame["tool_data"]["tool_name"]
        return name
    return key


async def test_a_web_turn_receives_the_whole_run_as_cards_and_a_browser_thread(
    redis: FakeRedisCache, chunks: list[str], browser: None
) -> None:
    """The run happens in a worker with no stream of its own; what the card renderer and the tool thread receive has to be indistinguishable from a run that never left the turn."""
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(_request())

    frames = _frames(chunks)
    assert [_shape(frame) for frame in frames] == [
        BROWSER_TASK_EVENT,
        "subagent_start",
        BROWSER_TASK_EVENT,
        "tool_calls_data",
        "tool_output",
        BROWSER_TASK_EVENT,
        "subagent_end",
    ]
    cards = [f["tool_data"]["data"] for f in frames if _shape(f) == BROWSER_TASK_EVENT]
    assert [card["kind"] for card in cards] == ["session", "step", "result"]
    assert cards[1]["goal"] == "open the booking page"
    assert cards[2]["summary"] == "Table booked for 7pm."


async def test_the_runs_cards_are_collected_onto_the_turns_message_under_one_group(
    redis: FakeRedisCache, chunks: list[str], browser: None
) -> None:
    """Live SSE is only half of it: without the in-process collector the cards are gone on reload, and an action row orphaned from its group renders outside the browser thread."""
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(_request())

    entries = drain_executor_tool_data(STREAM_ID)
    cards = [e for e in entries if e["tool_name"] == BROWSER_TASK_EVENT]
    assert [card["data"]["kind"] for card in cards] == ["session", "step", "result"]
    groups = [e for e in entries if e["tool_name"] == "subagent_group"]
    assert len(groups) == 1
    assert groups[0]["data"]["subagent_id"] == "browser:sess-7"
    group_calls = groups[0]["data"]["tool_calls"]
    assert [call["tool_name"] for call in group_calls] == ["go_to_url"]
    assert group_calls[0]["output"] == "opened example.test/book"


async def test_a_bot_conversation_is_served_the_same_run_over_its_own_transport(
    redis: FakeRedisCache, chunks: list[str], outbound: dict[str, list[Any]], browser: None
) -> None:
    """Bots read RabbitMQ, not SSE, so a run delivered only to the stream is invisible on Discord; both surfaces get the run exactly once."""
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(
        _request(
            source_category=SourceCategory.BOT.value,
            conversation_source=ConversationSource.DISCORD,
        )
    )

    assert [photo[2] for photo in outbound["photos"]] == [SHOT_URL]
    assert [_shape(frame) for frame in _frames(chunks)].count(BROWSER_TASK_EVENT) == 3


async def test_a_web_conversation_is_never_pushed_to_a_bot_platform(
    redis: FakeRedisCache, chunks: list[str], outbound: dict[str, list[Any]], browser: None
) -> None:
    """The bot mirror is chosen from the run's own provenance; a web turn pushed to a platform would arrive as a message the user never asked for."""
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(_request())

    assert outbound["messages"] == []
    assert outbound["photos"] == []


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the bot platform's outbound queue itself: every envelope the backend enqueued, decoded.

    Everything above it is real (BotProgressDelivery, publish_outbound_*), so an
    envelope here is addressed exactly as the bot will deliver it.
    """
    envelopes: list[dict[str, Any]] = []

    class _Publisher:
        async def publish_outbound(
            self, queue_name: str, body: bytes, *, expiration: int | None = None
        ) -> None:
            envelopes.append(json.loads(body))

    monkeypatch.setattr(
        outbound_mod, "get_rabbitmq_publisher", AsyncMock(return_value=_Publisher())
    )
    monkeypatch.setattr(
        outbound_mod.PlatformLinkService,
        "get_linked_platforms",
        AsyncMock(return_value={"discord": {"platformUserId": DM_ID}}),
    )
    monkeypatch.setattr(bot_mod, "create_live_view_link", AsyncMock(return_value=LIVE_VIEW_LINK))
    return envelopes


def _bot_session(channel_id: str | None) -> BotSessionDocument:
    """Build the conversation's bot session: a group's carries its channel, a DM's none."""
    return BotSessionDocument(
        session_key="discord:session",
        conversation_id="conv-7",
        platform="discord",
        platform_user_id=DM_ID,
        channel_id=channel_id,
    )


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


async def test_a_run_asked_for_in_a_group_keeps_its_live_link_and_photos_in_the_requesters_dm(
    redis: FakeRedisCache,
    chunks: list[str],
    queue: list[dict[str, Any]],
    browser: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live link drives the user's browser and a step photo can show a signed-in page, so a group that asked sees neither; only the final answer goes back there."""
    monkeypatch.setattr(jr, "BrowserTaskRunner", _ScriptedBrowserWithHandoff)
    monkeypatch.setattr(
        platform_message_service.bot_session_repository,
        "get_by_conversation_id",
        AsyncMock(return_value=_bot_session(GROUP_CHANNEL_ID)),
    )
    create_session(STREAM_ID, RunKind.LIVE)

    await _run_and_relay(
        _request(
            source_category=SourceCategory.BOT.value,
            conversation_source=ConversationSource.DISCORD,
        )
    )

    assert [(e["destination_id"], e["is_channel"]) for e in queue] == [(DM_ID, False)] * 3
    assert any(LIVE_VIEW_LINK in part for part in queue[0]["text_parts"])
    assert queue[1]["attachment"]["url"] == SHOT_URL
    assert queue[2]["text"] == STALL_NOTE
