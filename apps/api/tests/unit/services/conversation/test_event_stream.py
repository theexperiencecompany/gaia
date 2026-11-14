"""follow_screen: a follow opens on the newest page of the screen, at the log's head."""

import pytest

from app.models.conversation_screen_models import ScreenFrame
from app.services.conversation.event_stream import follow_screen
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
