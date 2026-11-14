"""follow_screen: a follow opens on the newest page of the screen, at the log's head."""

import asyncio

import pytest

from app.models.conversation_screen_models import ScreenFrame
from app.services.conversation.event_stream import event_lines, follow_screen
from tests.unit.services.conversation.log_helpers import user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

CONVERSATION = "conv-follow"
USER = "user-1"


async def test_a_follow_opens_on_the_screen_at_the_head_of_the_log() -> None:
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    await runtime.log.append(CONVERSATION, USER, user("u2"))

    frames = follow_screen(runtime.log, CONVERSATION, USER)
    opening = await anext(frames)
    await frames.aclose()

    assert isinstance(opening, ScreenFrame)
    assert opening.head == 2
    assert [item.id for item in opening.items] == ["u1", "u2"]


async def test_an_empty_conversation_opens_on_an_empty_screen_at_head_zero() -> None:
    frames = follow_screen(Runtime().log, CONVERSATION, USER)
    opening = await anext(frames)
    await frames.aclose()

    assert opening == ScreenFrame(items=(), head=0)


async def test_a_client_leaving_mid_wait_closes_the_follow_without_an_aclose_race() -> None:
    """Regression: cancelling the response while a frame was pending raised RuntimeError from aclose."""
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    lines = event_lines(runtime.log, CONVERSATION, USER, _never_disconnected, asyncio.Event())
    assert (await anext(lines)).startswith("data: ")
    pending = asyncio.ensure_future(anext(lines))
    await asyncio.sleep(0)
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending


async def _never_disconnected() -> bool:
    return False
