"""ActiveBotConversation.of: the follow a bot resumes from, read off its session and delivery cursor."""

import pytest

from app.models.bot_models import BotDelivery, BotSessionDocument, PartialReply
from app.models.conversation_send_models import ActiveBotConversation


@pytest.mark.parametrize(("channel_id", "is_dm"), [(None, True), ("ch-9", False)])
def test_a_follow_starts_after_the_sessions_delivered_cursor_in_its_dm_or_channel(
    channel_id: str | None, is_dm: bool
) -> None:
    session = BotSessionDocument(
        session_key="telegram:42",
        conversation_id="c-1",
        platform="telegram",
        platform_user_id="42",
        channel_id=channel_id,
    )
    partial = PartialReply(reply_id="r7", bubbles=2)
    delivery = BotDelivery(delivered_seq=6, partial_reply=partial, owed_seq=9)

    assert ActiveBotConversation.of(session, delivery) == ActiveBotConversation(
        conversation_id="c-1",
        platform_user_id="42",
        channel_id=channel_id,
        is_dm=is_dm,
        after_seq=6,
        partial_reply=partial,
    )
