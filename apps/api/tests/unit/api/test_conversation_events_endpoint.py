"""GET /conversations/{id}/events: the route follows from the client's head and writes in the client's wire."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
import json
from typing import Any
from unittest.mock import patch

import fakeredis.aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from pydantic import JsonValue
import pytest

from app.api.v1.endpoints import conversations
from app.api.v1.middleware.logging import LoggingMiddleware
from app.constants.chat import ConversationSource
from app.constants.conversation import EVENTS_KEY_PREFIX
from app.models.conversation_frame_models import EntryFrame, EntryUpdatedFrame
from app.models.conversation_log_models import UserMessage, WorkStarted
from app.models.conversation_screen_models import ScreenStreamFrame
from app.services.conversation.event_stream import follow_screen
from app.services.conversation.ports import ConversationLog
from app.services.conversation.runtime import install_runtime_ports
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext, analytics_context
from shared.py.wide_events import ConversationOperation, EventsResume
from tests.conftest import FAKE_USER
from tests.unit.services.conversation.log_helpers import at
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

CONVERSATION = "conv-events"
URL = f"/api/v1/conversations/{CONVERSATION}/events"
_Json = dict[str, JsonValue]


async def _opening_screen_only(
    log: ConversationLog, conversation_id: str, user_id: str, after: int = 0
) -> AsyncGenerator[ScreenStreamFrame | None]:
    """Follow for real, and close after the screen the stream opens on, so the response ends."""
    frames = follow_screen(log, conversation_id, user_id, after)
    yield await anext(frames)
    await frames.aclose()


@pytest.fixture
async def said(
    owned_conversations: set[tuple[str, str]],
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One owned conversation holding two messages, whose frames its stream still holds."""
    owned_conversations.add((CONVERSATION, FAKE_USER.user_id))
    monkeypatch.setattr(conversations, "follow_screen", _opening_screen_only)
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    for seq, message_id in enumerate(("u1", "u2"), start=1):
        message = UserMessage(id=message_id, text="hi", surface=ConversationSource.WEB)
        await runtime.log.append(CONVERSATION, FAKE_USER.user_id, message)
        frame = EntryFrame(seq=seq, at=at(seq), entry=message)
        await fake_redis.xadd(
            f"{EVENTS_KEY_PREFIX}{CONVERSATION}", {"frame": frame.model_dump_json()}
        )


async def _screen(client: AsyncClient, **params: int) -> list[_Json]:
    response = await client.get(URL, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    (line,) = [line for line in response.text.splitlines() if line.startswith("data: ")]
    frame: _Json = json.loads(line.removeprefix("data: "))["frame"]
    assert frame["kind"] == "screen"
    items = frame["items"]
    assert isinstance(items, list)
    return [item for item in items if isinstance(item, dict)]


@pytest.mark.usefixtures("said")
async def test_a_client_that_names_nothing_opens_on_the_whole_screen(client: AsyncClient) -> None:
    assert [item["id"] for item in await _screen(client)] == ["u1", "u2"]


@pytest.mark.usefixtures("said")
async def test_after_opens_on_only_what_the_client_lacks(client: AsyncClient) -> None:
    assert [item["id"] for item in await _screen(client, after=1)] == ["u2"]
    assert await _screen(client, after=2) == []


@pytest.mark.usefixtures("said")
async def test_wire_2_opens_on_items_without_their_unfolded_cards(client: AsyncClient) -> None:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    for entry in (
        UserMessage(id="u1", text="hi", surface=ConversationSource.WEB),
        WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",)),
    ):
        await runtime.log.append(CONVERSATION, FAKE_USER.user_id, entry)

    [_, plain] = await _screen(client)
    [_, lean] = await _screen(client, wire=2)
    assert (plain["tool_data"], "tool_data" in lean) == ([], False)
    assert lean == {key: value for key, value in plain.items() if key != "tool_data"}


@pytest.mark.usefixtures("said")
@pytest.mark.parametrize("params", [{"wire": 3}, {"wire": 0}, {"after": -1}])
async def test_a_wire_or_head_the_route_does_not_know_is_refused(
    client: AsyncClient, params: dict[str, int]
) -> None:
    response = await client.get(URL, params=params)
    assert response.status_code == 422


@dataclass(frozen=True)
class Served:
    """One request through the logging middleware: the bytes it was sent and the event it left."""

    content: bytes
    event: dict[str, Any]

    @property
    def opening_frame(self) -> bytes:
        return self.content[: self.content.index(b"\n\n") + 2]


async def _served(test_app: FastAPI, **params: int) -> Served:
    with patch("app.api.v1.middleware.logging.request_logger") as logger:
        transport = ASGITransport(app=LoggingMiddleware(app=test_app))
        async with AsyncClient(transport=transport, base_url="http://test") as http:  # NOSONAR
            response = await http.get(URL, params=params)
    assert response.status_code == 200, response.text
    logger.bind.assert_called_once()
    return Served(response.content, logger.bind.call_args.kwargs)


@pytest.mark.usefixtures("said")
@pytest.mark.parametrize(
    ("params", "wire", "resume"),
    [
        ({}, 1, EventsResume.FRESH),
        ({"wire": 2}, 2, EventsResume.FRESH),
        ({"wire": 2, "after": 1}, 2, EventsResume.RESUMED),
        ({"wire": 2, "after": 9}, 2, EventsResume.FULL_NOT_HELD),
    ],
    ids=["wire 1", "wire 2 fresh", "wire 2 resumed", "wire 2 refused"],
)
async def test_a_stream_s_request_event_says_what_it_served(
    test_app: FastAPI, params: dict[str, int], wire: int, resume: EventsResume
) -> None:
    served = await _served(test_app, **params)

    stream = served.event["conversation"]
    assert served.event["response_size_bytes"] == len(served.content) > 0
    assert (stream["operation"], stream["id"]) == (ConversationOperation.EVENTS, CONVERSATION)
    assert (stream["wire"], stream["resume"]) == (wire, resume)
    assert stream["opening_frame_bytes"] == len(served.opening_frame) > len(b"data: \n\n")
    assert stream["frames"] == served.content.count(b"data: ") == 1


@pytest.mark.usefixtures("said")
async def test_a_head_amended_since_is_answered_with_the_whole_screen_and_says_so(
    test_app: FastAPI, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    amended = EntryUpdatedFrame(
        seq=1, entry=UserMessage(id="u1", text="hi", surface=ConversationSource.WEB)
    )
    await fake_redis.xadd(
        f"{EVENTS_KEY_PREFIX}{CONVERSATION}", {"frame": amended.model_dump_json()}
    )

    served = await _served(test_app, wire=2, after=2)

    assert served.event["conversation"]["resume"] == EventsResume.FULL_AMENDED


@pytest.mark.usefixtures("said")
async def test_a_head_behind_an_unreadable_frame_is_answered_with_the_whole_screen_and_says_so(
    test_app: FastAPI, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    await fake_redis.xadd(f"{EVENTS_KEY_PREFIX}{CONVERSATION}", {"frame": "not json"})

    served = await _served(test_app, wire=2, after=2)

    assert served.event["conversation"]["resume"] == EventsResume.FULL_UNREADABLE


def _metered(sample: str, wire: int, surface: EntrySurface) -> float:
    labels = {"wire": str(wire), "surface": surface.value}
    return REGISTRY.get_sample_value(f"gaia_conversation_events_{sample}", labels) or 0.0


@pytest.mark.usefixtures("said")
@pytest.mark.parametrize("wire", [1, 2])
async def test_a_stream_s_bytes_and_opening_frame_are_metered_by_wire_and_surface(
    test_app: FastAPI, wire: int
) -> None:
    samples = ("stream_bytes_total", "opening_frame_bytes_sum", "opening_frame_bytes_count")
    bot = AnalyticsContext(
        attribution=Attribution(
            actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.BOT
        )
    )
    before = [_metered(sample, wire, EntrySurface.BOT) for sample in samples]
    elsewhere = [_metered(sample, wire, EntrySurface.WEB) for sample in samples]

    with analytics_context(bot):
        served = await _served(test_app, wire=wire)

    after = [_metered(sample, wire, EntrySurface.BOT) for sample in samples]
    assert [now - was for now, was in zip(after, before, strict=True)] == [
        len(served.content),
        len(served.opening_frame),
        1,
    ]
    assert [_metered(sample, wire, EntrySurface.WEB) for sample in samples] == elsewhere
