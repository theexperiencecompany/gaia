"""GET /conversations/{id}/events over real HTTP, Mongo and Redis: what wire 2 and after send, in bytes."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
import json
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
import httpx
from pydantic import JsonValue, TypeAdapter
import pytest
from redis.asyncio import Redis

from app.api.v1.middleware.auth import PostHogRequestContextMiddleware
from app.api.v1.middleware.logging import LoggingMiddleware
from app.constants.chat import ConversationSource
from app.constants.conversation import EVENTS_KEY_PREFIX
from app.constants.summarization import MAX_OUTPUT_CHARS
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import EntryUpdatedFrame
from app.models.conversation_log_models import (
    ApprovalRequested,
    Reaction,
    StepClaim,
    UserMessage,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation import event_stream
from app.services.conversation.event_stream import RedisStreamFrames, read_frames
from app.services.conversation.log import accept, publish_appended
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.screen import project_screen
from app.services.conversation.screen_patches import ScreenTracker
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation.work_deltas import WorkDeltas, work_payloads
from app.services.conversation.work_log import (
    WorkReport,
    record_approval_requested,
    record_work_finished,
)
from app.utils.artifact_utils import FILE_LINKS
from shared.py.conversation_patch import with_changes
from shared.py.conversation_wire import ItemChange
from shared.py.wide_events import EventsResume
from tests.conftest import FAKE_USER
from tests.helpers import serve_asgi
from tests.unit.services.conversation.log_helpers import SEND_EMAIL
from tests.unit.services.conversation.runtime_doubles import (
    RecordingAnalytics,
    RecordingEffects,
    ScriptedApprovals,
    ScriptedRunner,
    TickGate,
)

pytestmark = pytest.mark.service

USER = FAKE_USER.user_id
#: One tool call's output: large beside the frame around it, as a fetched page or a query result is.
OUTPUT_BYTES = 20_000
MEGABYTE = 1024 * 1024
_CHANGES: TypeAdapter[list[ItemChange]] = TypeAdapter(list[ItemChange])
_Json = dict[str, JsonValue]


async def _no_tick() -> None:
    return None


@pytest.fixture
def ports(conversations_collection: object, real_redis: Redis) -> RuntimePorts:
    """Install the real Mongo log and Redis stream; nothing answers, so a test writes every entry itself."""
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    installed = RuntimePorts(
        log=log,
        runner=ScriptedRunner(TickGate()),
        frames=RedisStreamFrames(),
        effects=RecordingEffects(),
        approvals=ScriptedApprovals(),
        analytics=RecordingAnalytics(),
        clock=lambda: datetime.now(UTC),
        tick=_no_tick,
        links=FILE_LINKS,
    )
    install_runtime_ports(installed)
    return installed


@pytest.fixture
def quick_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wait 50 ms for a live frame, so a stream whose client left ends before the server stops."""
    monkeypatch.setattr(event_stream, "read_frames", partial(read_frames, block_ms=50))


@pytest.fixture
async def api(test_app: FastAPI, quick_reads: None) -> AsyncIterator[str]:
    # The request's analytics context is bound by its middleware, as in production.
    async with serve_asgi(PostHogRequestContextMiddleware(app=test_app)) as base_url:
        yield base_url


@dataclass
class Client:
    """What a client holds after the frames it read: its items by id, and the bytes it was sent."""

    items: dict[str, _Json] = field(default_factory=dict)
    frames: list[_Json] = field(default_factory=list)
    received: int = 0
    head: int = 0

    def take(self, line: str) -> _Json:
        self.received += len(line.encode())
        frame: _Json = json.loads(line)["frame"]
        self.frames.append(frame)
        match frame["kind"]:
            case "screen":
                self.items.update((str(item["id"]), item) for item in _items(frame["items"]))
            case "screen_insert" | "screen_update":
                item = _item(frame["item"])
                self.items[str(item["id"])] = item
            case "screen_patch":
                held = self.items[str(frame["id"])]
                changes = _CHANGES.validate_python(frame["changes"])
                self.items[str(frame["id"])] = _item(with_changes(held, changes))
        if isinstance(head := frame.get("head"), int) and frame["kind"] != "state":
            self.head = max(self.head, head)
        return frame

    def kinds(self) -> list[str]:
        return [str(frame["kind"]) for frame in self.frames]


def _item(value: JsonValue) -> _Json:
    assert isinstance(value, dict)
    return value


def _items(value: JsonValue) -> list[_Json]:
    assert isinstance(value, list)
    return [_item(item) for item in value]


@dataclass
class Follow:
    """One open connection to the events route, read as far as a test needs."""

    client: Client
    lines: AsyncIterator[str]

    async def until(self, held: Callable[[Client], bool]) -> Client:
        """Read on until the client holds what held names; a stream that never gets there times out."""
        async for line in self.lines:
            if not line.startswith("data: "):
                continue
            self.client.take(line.removeprefix("data: "))
            if held(self.client):
                break
        return self.client


@asynccontextmanager
async def _following(api: str, conversation_id: str, **params: int) -> AsyncIterator[Follow]:
    url = f"{api}/api/v1/conversations/{conversation_id}/events"
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http,
        http.stream("GET", url, params=params) as response,
    ):
        assert response.status_code == 200, await response.aread()
        yield Follow(Client(), response.aiter_lines())


async def _read(api: str, conversation_id: str, **params: int) -> Client:
    """Open the events route and read the screen it opens on, through its state."""
    async with _following(api, conversation_id, **params) as follow:
        return await follow.until(_opened)


def _opened(client: Client) -> bool:
    return "state" in client.kinds()


def _call(index: int) -> dict[str, object]:
    return {
        "tool_name": "tool_calls_data",
        "tool_category": "googledrive",
        "data": {
            "tool_name": "LIST_FILES",
            "tool_category": "googledrive",
            "message": f"Listing page {index}",
            "tool_call_id": f"call_{index}",
            "inputs": {"page": index},
        },
    }


def _output(index: int, chars: int) -> dict[str, object]:
    return {"tool_call_id": f"call_{index}", "output": chr(97 + index % 26) * chars}


@dataclass
class Conversation:
    """One conversation in real storage, written entry by entry as production writes it."""

    ports: RuntimePorts
    id: str
    claim: StepClaim | None = None

    async def say(self, message_id: str) -> int:
        accepted = await accept(
            self.ports,
            self.id,
            USER,
            UserMessage(
                id=message_id, text=f"text of {message_id}", surface=ConversationSource.WEB
            ),
        )
        return accepted.appended.logged.seq

    async def start_work(self, task_id: str, cause_through: int) -> None:
        # One step holds the conversation for the whole test, as a turn that keeps handing off does.
        self.claim = self.claim or await self.ports.log.claim(self.id, USER)
        assert self.claim is not None
        entry = WorkStarted(id=f"work:{task_id}", task_id=task_id, cause_through=cause_through)
        appended = await self.ports.log.append_fenced(self.claim, entry)
        await publish_appended(self.ports.frames, self.id, appended)

    async def run_tools(
        self, task_id: str, calls: Iterator[int], output_chars: int = OUTPUT_BYTES
    ) -> None:
        """Publish each call's card, then its output, as the executor's stream writer does."""
        deltas = WorkDeltas(self.id, task_id)
        for index in calls:
            deltas({"tool_data": _call(index)})
            deltas({"tool_output": _output(index, output_chars)})
        await deltas.drain()

    async def finish_work(self, task_id: str) -> None:
        cards = fold_cards(await work_payloads(self.id, task_id)).tool_data
        await record_work_finished(
            self.id, USER, task_id, WorkOutcome.DONE, WorkReport("done", tool_data=cards)
        )

    async def screen(self) -> dict[str, _Json]:
        """Return the screen the server projects now, as wire 2 writes an item."""
        entries = await self.ports.log.read_after(self.id, USER, 0)
        return {
            item.id: _item(item.model_dump(mode="json", exclude={"tool_data"}))
            for item in project_screen(self.id, entries, FILE_LINKS)
        }


@pytest.fixture
async def conversation(
    ports: RuntimePorts, make_conversation: Callable[..., Awaitable[str]]
) -> Conversation:
    conversation_id = f"convrt-{uuid4().hex[:10]}"
    await make_conversation(USER, conversation_id)
    return Conversation(ports, conversation_id)


def _outputs_held(client: Client, task_id: str) -> int:
    work = client.items.get(f"work:{task_id}")
    if work is None:
        return 0
    timeline = _item(work["timeline"])
    return sum(1 for step in _items(timeline["steps"]) if "output" in _item(_item(step)["data"]))


async def test_wire_2_opens_on_each_card_once_within_the_bytes_of_its_outputs(
    api: str, conversation: Conversation
) -> None:
    calls = 40
    await conversation.start_work("t1", await conversation.say("m1"))
    await conversation.run_tools("t1", iter(range(calls)))
    await conversation.finish_work("t1")
    before = await _read(api, conversation.id)
    lean = await _read(api, conversation.id, wire=2)
    outputs = calls * OUTPUT_BYTES
    assert before.received > 2 * outputs
    assert outputs < lean.received < 1.1 * outputs
    assert all("tool_data" not in item for item in lean.items.values())
    assert _outputs_held(lean, "t1") == calls
    assert lean.items == await conversation.screen()


async def test_a_live_run_on_wire_2_sends_each_output_once_and_patches_to_the_projection(
    api: str, conversation: Conversation
) -> None:
    calls = 30
    await conversation.start_work("t1", await conversation.say("m1"))
    async with _following(api, conversation.id, wire=2) as follow:
        opened = (await follow.until(_opened)).received
        await conversation.run_tools("t1", iter(range(calls)))
        live = await follow.until(lambda held: _outputs_held(held, "t1") == calls)
    assert live.received - opened < 1.2 * calls * OUTPUT_BYTES
    assert "screen_patch" in live.kinds()
    assert "screen_update" not in live.kinds()
    assert live.items["work:t1"] == (await _live_screen(conversation))["work:t1"]


def _outputs(client: Client, task_id: str) -> list[tuple[int, JsonValue]]:
    """Return each call's kept output length and the full length it names, as the client holds the work."""
    steps = _items(_item(client.items[f"work:{task_id}"]["timeline"])["steps"])
    calls = [_item(step["data"]) for step in steps]
    return [(len(str(call["output"])), call.get("output_original_length")) for call in calls]


@pytest.mark.regression
async def test_a_run_whose_outputs_pass_mongos_document_cap_saves_its_finish_with_each_cut(
    api: str, conversation: Conversation
) -> None:
    calls = 18
    await conversation.start_work("t1", await conversation.say("m1"))
    await conversation.run_tools("t1", iter(range(calls)), output_chars=MEGABYTE)

    await conversation.finish_work("t1")

    lean = await _read(api, conversation.id, wire=2)
    assert lean.items["work:t1"]["status"] == "done"
    assert _outputs(lean, "t1") == [(MAX_OUTPUT_CHARS, MEGABYTE)] * calls
    assert lean.received < 1.1 * calls * MAX_OUTPUT_CHARS
    assert lean.items == await conversation.screen()


async def test_a_live_output_past_the_limit_reaches_wire_2_cut_and_its_finish_resends_none_of_it(
    api: str, conversation: Conversation
) -> None:
    await conversation.start_work("t1", await conversation.say("m1"))
    async with _following(api, conversation.id, wire=2) as follow:
        opened = (await follow.until(_opened)).received
        await conversation.run_tools("t1", iter(range(2)), output_chars=3 * MAX_OUTPUT_CHARS)
        live = await follow.until(lambda held: _outputs_held(held, "t1") == 2)
        running = live.received
        assert running - opened < 2.2 * MAX_OUTPUT_CHARS
        assert _outputs(live, "t1") == [(MAX_OUTPUT_CHARS, 3 * MAX_OUTPUT_CHARS)] * 2
        assert live.items["work:t1"] == (await _live_screen(conversation))["work:t1"]

        await conversation.finish_work("t1")
        done = await follow.until(lambda held: held.items["work:t1"]["status"] == "done")
    assert done.received - running < 0.05 * MAX_OUTPUT_CHARS
    assert done.items == await conversation.screen()


async def _live_screen(conversation: Conversation) -> dict[str, _Json]:
    """Return the screen with its running work's cards, as wire 2 writes an item."""
    entries = await conversation.ports.log.read_after(conversation.id, USER, 0)
    tracker = await ScreenTracker.load(conversation.id, entries)
    return {
        item.id: _item(item.model_dump(mode="json", exclude={"tool_data"}))
        for item in tracker.items
    }


async def test_a_reconnect_after_the_head_it_reached_is_sent_only_what_is_new(
    api: str, conversation: Conversation
) -> None:
    await conversation.start_work("t1", await conversation.say("m1"))
    await conversation.run_tools("t1", iter(range(20)))
    await conversation.finish_work("t1")
    first = await _read(api, conversation.id, wire=2)
    await conversation.say("m2")
    resumed = await _read(api, conversation.id, wire=2, after=first.head)
    assert [item["id"] for item in _items(resumed.frames[0]["items"])] == ["m2"]
    assert resumed.received < 0.01 * first.received
    first.items.update(resumed.items)
    assert first.items == await conversation.screen()


async def test_a_reconnect_mid_run_is_sent_the_live_work_again_and_the_message_it_answers(
    api: str, conversation: Conversation
) -> None:
    await conversation.start_work("t1", await conversation.say("m1"))
    await conversation.run_tools("t1", iter(range(5)))
    await conversation.finish_work("t1")
    await conversation.start_work("t2", await conversation.say("m2"))
    await conversation.run_tools("t2", iter(range(5, 8)))
    first = await _read(api, conversation.id, wire=2)
    resumed = await _read(api, conversation.id, wire=2, after=first.head)
    assert [item["id"] for item in _items(resumed.frames[0]["items"])] == ["m2", "work:t2"]


async def test_a_reconnect_is_sent_the_newest_user_message_even_when_nothing_changed(
    api: str, conversation: Conversation
) -> None:
    await conversation.say("m1")
    await conversation.start_work("t1", await conversation.say("m2"))
    await conversation.finish_work("t1")
    first = await _read(api, conversation.id, wire=2)
    resumed = await _read(api, conversation.id, wire=2, after=first.head)
    assert resumed.frames[0]["items"] == [first.items["m2"]]


async def test_a_reconnect_is_sent_the_whole_screen_when_an_entry_it_held_was_amended(
    api: str, conversation: Conversation
) -> None:
    await conversation.say("m1")
    first = await _read(api, conversation.id, wire=2)
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    reacted = await log.react_once(
        conversation.id, USER, "m1", Reaction(emoji="👍", by=ReactionBy.JEV)
    )
    assert reacted is not None
    await conversation.ports.frames.publish(
        conversation.id, EntryUpdatedFrame(seq=reacted.seq, entry=reacted.entry)
    )
    resumed = await _read(api, conversation.id, wire=2, after=first.head)
    assert resumed.items == await conversation.screen()
    assert _item(_item(resumed.items["m1"]["message"])["reaction"])["emoji"] == "👍"


async def test_a_reconnect_is_sent_the_whole_screen_once_the_stream_no_longer_holds_its_head(
    api: str, conversation: Conversation, real_redis: Redis
) -> None:
    await conversation.say("m1")
    first = await _read(api, conversation.id, wire=2)
    await real_redis.delete(f"{EVENTS_KEY_PREFIX}{conversation.id}")
    resumed = await _read(api, conversation.id, wire=2, after=first.head)
    assert list(resumed.items) == ["m1"]


async def test_a_client_that_names_no_wire_is_sent_whole_items_with_their_cards(
    api: str, conversation: Conversation
) -> None:
    await conversation.start_work("t1", await conversation.say("m1"))
    async with _following(api, conversation.id) as follow:
        await follow.until(_opened)
        await conversation.run_tools("t1", iter(range(2)))
        live = await follow.until(lambda held: _outputs_held(held, "t1") == 2)
    assert "screen_patch" not in live.kinds()
    assert [
        "output" in _item(card["data"]) for card in _items(live.items["work:t1"]["tool_data"])
    ] == [True, True]


async def test_a_connection_cut_between_two_frames_of_one_entry_resumes_with_the_second(
    api: str, conversation: Conversation
) -> None:
    await conversation.start_work("t1", await conversation.say("m1"))
    expiring = ApprovalRequested(
        id="ask:a1",
        task_id="t1",
        approval_id="a1",
        description=SEND_EMAIL,
        expires_at=datetime.now(UTC) + timedelta(milliseconds=300),
    )
    await record_approval_requested(conversation.id, USER, expiring)
    async with _following(api, conversation.id, wire=2) as follow:
        await follow.until(_opened)
        await asyncio.sleep(0.4)
        # The message shows, and the approval that ran out before it stops being asked: two frames.
        await conversation.say("m2")
        cut = await follow.until(lambda held: held.kinds()[-1] == "screen_patch")
    assert "m2" not in cut.items
    resumed = await _read(api, conversation.id, wire=2, after=cut.head)
    cut.items.update(resumed.items)
    assert cut.items == await conversation.screen()


_KEEPALIVE = b": keepalive\n\n"
_STATE = b'"kind":"state"'


@dataclass
class Logged:
    """The API behind its logging middleware, and the request event each connection leaves."""

    api: str
    logger: MagicMock
    emitted: asyncio.Event

    async def left_after_opening(self, conversation_id: str, **params: int) -> "Left":
        """Read the screen the stream opens on, leave, and wait for the event the server emits."""
        url = f"{self.api}/api/v1/conversations/{conversation_id}/events"
        received = b""
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http,
            http.stream("GET", url, params=params) as response,
        ):
            assert response.status_code == 200, await response.aread()
            async for chunk in response.aiter_bytes():
                received += chunk
                if _STATE in received and received.endswith(b"\n\n"):
                    break
        async with asyncio.timeout(10):
            await self.emitted.wait()
        self.emitted.clear()
        return Left(received, self.logger.bind.call_args.kwargs)


@dataclass(frozen=True)
class Left:
    """What a client that left was sent, and the event its request left behind."""

    received: bytes
    event: dict[str, Any]

    @property
    def frames(self) -> list[bytes]:
        return [line for line in self.received.split(b"\n\n") if line.startswith(b"data: ")]

    @property
    def stream(self) -> dict[str, Any]:
        stream: dict[str, Any] = self.event["conversation"]
        return stream


@pytest.fixture
async def logged(test_app: FastAPI, quick_reads: None) -> AsyncIterator[Logged]:
    emitted = asyncio.Event()

    def bound(**_context: object) -> MagicMock:
        emitted.set()
        return MagicMock()

    with patch("app.api.v1.middleware.logging.request_logger") as logger:
        logger.bind.side_effect = bound
        served = LoggingMiddleware(app=PostHogRequestContextMiddleware(app=test_app))
        async with serve_asgi(served) as base_url:
            yield Logged(base_url, logger, emitted)


async def test_a_client_that_leaves_mid_stream_leaves_an_event_with_the_bytes_it_was_sent(
    logged: Logged, conversation: Conversation
) -> None:
    calls = 3
    await conversation.start_work("t1", await conversation.say("m1"))
    await conversation.run_tools("t1", iter(range(calls)))
    await conversation.finish_work("t1")

    left = await logged.left_after_opening(conversation.id, wire=2)

    # Only keepalives can follow the state frame the client left on.
    unread = left.event["response_size_bytes"] - len(left.received)
    assert len(left.received) > calls * OUTPUT_BYTES
    assert (unread >= 0, unread % len(_KEEPALIVE)) == (True, 0)
    assert (left.event["status_code"], left.stream["wire"]) == (200, 2)
    assert left.stream["resume"] == EventsResume.FRESH
    assert left.stream["opening_frame_bytes"] == len(left.frames[0]) + len(b"\n\n")
    assert left.stream["frames"] == len(left.frames)
    assert left.event["response_duration_ms"] >= left.event["duration_ms"]


async def test_each_reconnect_s_event_says_whether_its_head_was_honoured(
    logged: Logged, conversation: Conversation, real_redis: Redis
) -> None:
    head = await conversation.say("m1")
    await conversation.say("m2")

    plain = await logged.left_after_opening(conversation.id)
    resumed = await logged.left_after_opening(conversation.id, wire=2, after=head)
    await real_redis.delete(f"{EVENTS_KEY_PREFIX}{conversation.id}")
    refused = await logged.left_after_opening(conversation.id, wire=2, after=head)

    assert [(left.stream["wire"], left.stream["resume"]) for left in (plain, resumed, refused)] == [
        (1, EventsResume.FRESH),
        (2, EventsResume.RESUMED),
        (2, EventsResume.FULL_NOT_HELD),
    ]
    assert resumed.stream["opening_frame_bytes"] < refused.stream["opening_frame_bytes"]
