"""BotWakingFrames: the conversation's bot is owed and woken for exactly the entries it renders."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.bot_models import MessageReaction
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import EntryFrame, EntryUpdatedFrame
from app.models.conversation_log_models import Entry, Reaction
from app.services.conversation.bot_wake import BotWakingFrames
from tests.unit.services.conversation.log_helpers import notice, user
from tests.unit.services.conversation.runtime_doubles import RecordingFrames

pytestmark = pytest.mark.unit

WAKE = "app.services.conversation.bot_wake"
AT = datetime(2026, 11, 14, tzinfo=UTC)


def _frame(seq: int, entry: Entry) -> EntryFrame:
    return EntryFrame(seq=seq, at=AT, entry=entry)


async def test_the_bot_is_owed_the_rendered_entries_and_woken_from_its_cursor() -> None:
    session = MagicMock()
    frames = RecordingFrames()
    with (
        patch(
            f"{WAKE}.bot_session_repository.owe_delivery", new=AsyncMock(return_value=session)
        ) as owe,
        patch(f"{WAKE}.publish_conversation_wake", new=AsyncMock()) as wake,
    ):
        await BotWakingFrames(frames).publish(
            "conv-1", _frame(4, user("u1")), _frame(5, notice("n1")), _frame(7, notice("n2"))
        )

    assert (len(frames.published), frames.conversations) == (3, ["conv-1"])
    owe.assert_awaited_once_with("conv-1", first_seq=5, last_seq=7)
    wake.assert_awaited_once_with(session)


async def test_a_conversation_with_no_bot_session_wakes_nothing() -> None:
    with (
        patch(f"{WAKE}.bot_session_repository.owe_delivery", new=AsyncMock(return_value=None)),
        patch(f"{WAKE}.publish_conversation_wake", new=AsyncMock()) as wake,
    ):
        await BotWakingFrames(RecordingFrames()).publish("conv-1", _frame(5, notice("n1")))

    wake.assert_not_awaited()


async def test_frames_a_bot_does_not_render_owe_it_nothing() -> None:
    with patch(f"{WAKE}.bot_session_repository.owe_delivery", new=AsyncMock()) as owe:
        await BotWakingFrames(RecordingFrames()).publish("conv-1", _frame(4, user("u1")))

    owe.assert_not_awaited()


async def test_a_reaction_is_owed_to_the_bot_before_its_frame_goes_out_and_wakes_it() -> None:
    session = MagicMock()
    frames = RecordingFrames()
    published_when_owed: list[int] = []

    async def owe(*_args: object, **_kwargs: object) -> MagicMock:
        published_when_owed.append(len(frames.published))
        return session

    reacted = user("u1").model_copy(
        update={"reaction": Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)}
    )
    with (
        patch(
            f"{WAKE}.bot_session_repository.owe_reaction", new=AsyncMock(side_effect=owe)
        ) as owed,
        patch(f"{WAKE}.bot_session_repository.owe_delivery", new=AsyncMock()) as delivery,
        patch(f"{WAKE}.publish_conversation_wake", new=AsyncMock()) as wake,
    ):
        await BotWakingFrames(frames).publish("conv-1", EntryUpdatedFrame(seq=4, entry=reacted))

    owed.assert_awaited_once_with(
        "conv-1", seq=4, reaction=MessageReaction(message_id="u1", emoji="👍")
    )
    assert (published_when_owed, len(frames.published)) == ([0], 1)
    delivery.assert_not_awaited()
    wake.assert_awaited_once_with(session)


async def test_a_message_amended_without_a_reaction_owes_nothing() -> None:
    with patch(f"{WAKE}.bot_session_repository.owe_reaction", new=AsyncMock()) as owed:
        await BotWakingFrames(RecordingFrames()).publish(
            "conv-1", EntryUpdatedFrame(seq=4, entry=user("u1"))
        )

    owed.assert_not_awaited()
