"""A reply's link placeholders stay in the log and resolve only on the way to a client."""

import asyncio
from collections.abc import Iterator
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories.short_links import short_link_repository
from app.models.conversation_frame_models import RetractFrame
from app.models.conversation_log_models import Reply
from app.models.conversation_screen_models import ScreenInsertFrame, ScreenUpdateFrame
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.services.conversation.event_stream import event_lines
from app.services.conversation.shown_links import shown_frame
from app.services.links.placeholders import link_placeholder
from app.services.links.urls import build_url
from shared.py.conversation_wire import BubbleTextDelta, ReplyDeltaFrame, ReplyItem
from tests.factories import make_reply_item
from tests.unit.services.conversation.log_helpers import settled, user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

CONVERSATION = "conv-links"
USER = "user-1"
TARGET = RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="art_1")
PLACEHOLDER = link_placeholder(TARGET)
URL = build_url("ab12cd")


@pytest.fixture
def live_link() -> Iterator[AsyncMock]:
    live = AsyncMock(return_value=ShortLink(slug="ab12cd", user_id=USER, target=TARGET))
    with patch.object(short_link_repository, "get_live_for_target", live):
        yield live


async def _never_disconnected() -> bool:
    return False


async def test_a_client_is_sent_the_reply_with_its_link_while_the_log_keeps_the_placeholder(
    live_link: AsyncMock,
) -> None:
    """Regression: the runtime merge stored the resolved URL, which later turns fed the model."""
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    text = f"Here it is: [the plan]({PLACEHOLDER})"
    await runtime.log.append(
        CONVERSATION, USER, Reply(id="e2", reply_id="r1", attempt_id="a1", text=text)
    )
    await runtime.log.append(CONVERSATION, USER, settled("s3", ["u1"], 2))

    lines = event_lines(runtime.log, CONVERSATION, USER, _never_disconnected, asyncio.Event())
    first = await anext(lines)
    await lines.aclose()

    screen = json.loads(first.removeprefix("data: "))["frame"]
    [reply] = [item for item in screen["items"] if item["kind"] == "reply"]
    assert reply["bubbles"] == [f"Here it is: [the plan]({URL})"]
    stored = await runtime.log.read_after(CONVERSATION, USER, 0)
    assert [logged.entry.text for logged in stored if isinstance(logged.entry, Reply)] == [text]
    assert live_link.await_args.args[0] == USER


async def test_a_streamed_bubble_delta_reaches_the_client_with_its_link(
    live_link: AsyncMock,
) -> None:
    delta = ReplyDeltaFrame(
        attempt_id="a1",
        reply_id="r1",
        index=0,
        payload=BubbleTextDelta(bubble=0, text=f"Open {PLACEHOLDER} now"),
    )

    shown = await shown_frame(USER, delta)

    assert isinstance(shown, ReplyDeltaFrame)
    assert shown.payload == BubbleTextDelta(bubble=0, text=f"Open {URL} now")
    assert isinstance(delta.payload, BubbleTextDelta)
    assert delta.payload.text == f"Open {PLACEHOLDER} now"


async def test_a_placeholder_with_no_live_link_keeps_only_its_label(live_link: AsyncMock) -> None:
    live_link.return_value = None
    delta = ReplyDeltaFrame(
        attempt_id="a1",
        reply_id="r1",
        index=0,
        payload=BubbleTextDelta(bubble=0, text=f"See [the plan]({PLACEHOLDER})"),
    )

    shown = await shown_frame(USER, delta)

    assert isinstance(shown, ReplyDeltaFrame)
    assert shown.payload == BubbleTextDelta(bubble=0, text="See the plan")


@pytest.mark.parametrize("patch_frame", [ScreenInsertFrame, ScreenUpdateFrame])
async def test_a_patched_reply_reaches_the_client_with_its_link(
    live_link: AsyncMock, patch_frame: type[ScreenInsertFrame] | type[ScreenUpdateFrame]
) -> None:
    frame = patch_frame(item=make_reply_item(f"Open {PLACEHOLDER}"), head=3)

    shown = await shown_frame(USER, frame)

    assert isinstance(shown, ScreenInsertFrame | ScreenUpdateFrame)
    assert type(shown) is patch_frame
    assert isinstance(shown.item, ReplyItem)
    assert shown.item.bubbles == (f"Open {URL}",)
    assert shown.head == 3
    assert live_link.await_args.args[0] == USER


async def test_a_frame_with_no_text_passes_through_as_it_is(live_link: AsyncMock) -> None:
    retract = RetractFrame(attempt_id="a1")

    assert await shown_frame(USER, retract) is retract
    live_link.assert_not_awaited()
