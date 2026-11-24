"""GET /conversations/{id}/events over real HTTP, Mongo and Redis: what wire 2 and after send, in bytes."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
import json
from uuid import uuid4

from fastapi import FastAPI
import httpx
from pydantic import JsonValue, TypeAdapter
import pytest
from redis.asyncio import Redis

from app.constants.chat import ConversationSource
from app.constants.conversation import EVENTS_KEY_PREFIX
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import EntryUpdatedFrame
from app.models.conversation_log_models import (
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
from app.services.conversation.work_log import WorkReport, record_work_finished
from app.utils.artifact_utils import FILE_LINKS
from shared.py.conversation_wire import ItemChange
from tests.conftest import FAKE_USER
from tests.helpers import serve_asgi
from tests.unit.services.conversation.change_helpers import with_changes
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
    async with serve_asgi(test_app) as base_url:
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


def _output(index: int) -> dict[str, object]:
    return {"tool_call_id": f"call_{index}", "output": chr(97 + index % 26) * OUTPUT_BYTES}


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

    async def run_tools(self, task_id: str, calls: Iterator[int]) -> None:
        """Publish each call's card, then its output, as the executor's stream writer does."""
        deltas = WorkDeltas(self.id, task_id)
        for index in calls:
            deltas({"tool_data": _call(index)})
            deltas({"tool_output": _output(index)})
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


async def test_a_reconnect_mid_run_is_sent_the_live_work_again_and_nothing_older(
    api: str, conversation: Conversation
) -> None:
    await conversation.start_work("t1", await conversation.say("m1"))
    await conversation.run_tools("t1", iter(range(5)))
    await conversation.finish_work("t1")
    await conversation.start_work("t2", await conversation.say("m2"))
    await conversation.run_tools("t2", iter(range(5, 8)))
    first = await _read(api, conversation.id, wire=2)
    resumed = await _read(api, conversation.id, wire=2, after=first.head)
    assert [item["id"] for item in _items(resumed.frames[0]["items"])] == ["work:t2"]


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
