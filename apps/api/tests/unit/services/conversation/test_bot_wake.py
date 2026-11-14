"""BotWakingFrames: publish every frame, and wake the conversation's bot for what it renders."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.models.bot_models import BotSessionDocument
from app.models.conversation_frame_models import EntryFrame, EntryUpdatedFrame
from app.models.conversation_log_models import Entry
from app.services.conversation.bot_wake import BotWakingFrames
from tests.unit.services.conversation.log_helpers import (
    asked,
    at,
    notice,
    opened,
    started,
    user,
)
from tests.unit.services.conversation.runtime_doubles import CONVERSATION, RecordingFrames

MODULE = "app.services.conversation.bot_wake"

SESSION = BotSessionDocument(
    session_key="telegram:42:42",
    conversation_id=CONVERSATION,
    platform="telegram",
    platform_user_id="42",
)


def _frame(seq: int, entry: Entry) -> EntryFrame:
    return EntryFrame(seq=seq, at=at(seq), entry=entry)


@pytest.fixture
def session_lookup() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.bot_session_repository") as sessions:
        sessions.get_by_conversation_id = AsyncMock(return_value=SESSION)
        yield sessions.get_by_conversation_id


@pytest.fixture
def wake() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.publish_conversation_wake", new_callable=AsyncMock) as wake:
        yield wake


async def test_it_wakes_the_bot_from_just_before_the_first_rendered_entry(
    session_lookup: AsyncMock, wake: AsyncMock
) -> None:
    inner = RecordingFrames()
    frames = (
        _frame(4, user("u1")),
        _frame(7, asked("e7", "t1", "ap1")),
        _frame(5, opened("e5")),
        _frame(9, notice("e9")),
    )

    await BotWakingFrames(inner).publish(CONVERSATION, *frames)

    assert inner.conversations == [CONVERSATION]
    assert inner.published == list(frames)
    session_lookup.assert_awaited_once_with(CONVERSATION)
    wake.assert_awaited_once_with(SESSION, after_seq=4)


async def test_frames_a_bot_never_renders_wake_nothing(
    session_lookup: AsyncMock, wake: AsyncMock
) -> None:
    inner = RecordingFrames()
    frames = (
        _frame(3, user("u1")),
        _frame(4, started("e4", "t1", 3)),
        EntryUpdatedFrame(seq=5, entry=opened("e5")),
    )

    await BotWakingFrames(inner).publish(CONVERSATION, *frames)

    assert inner.published == list(frames)
    session_lookup.assert_not_awaited()
    wake.assert_not_awaited()


async def test_a_conversation_with_no_bot_session_wakes_nothing(
    session_lookup: AsyncMock, wake: AsyncMock
) -> None:
    session_lookup.return_value = None
    inner = RecordingFrames()

    await BotWakingFrames(inner).publish(CONVERSATION, _frame(2, notice("e2")))

    assert len(inner.published) == 1
    wake.assert_not_awaited()
