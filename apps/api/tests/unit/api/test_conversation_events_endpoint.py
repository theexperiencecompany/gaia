"""GET /conversations/{id}/events: the route follows from the client's head and writes in the client's wire."""

from collections.abc import AsyncGenerator
import json

import fakeredis.aioredis
from httpx import AsyncClient
from pydantic import JsonValue
import pytest

from app.api.v1.endpoints import conversations
from app.constants.chat import ConversationSource
from app.constants.conversation import EVENTS_KEY_PREFIX
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import UserMessage, WorkStarted
from app.models.conversation_screen_models import ScreenStreamFrame
from app.services.conversation.event_stream import follow_screen
from app.services.conversation.ports import ConversationLog
from app.services.conversation.runtime import install_runtime_ports
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
