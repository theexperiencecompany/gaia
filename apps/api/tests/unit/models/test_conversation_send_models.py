"""SendMessageRequest's reply naming, and ActiveBotConversation.of's follow cursor."""

from pydantic import ValidationError
import pytest

from app.models.bot_models import BotDelivery, BotSessionDocument, PartialReply
from app.models.conversation_send_models import ActiveBotConversation, SendMessageRequest
from shared.py.conversation_wire import ReplyToMessageData

QUOTED = ReplyToMessageData(id="m-1", content="the plan", role="assistant")


@pytest.mark.parametrize("reply_to", [None, "m-1"])
def test_a_reply_naming_its_quote_or_nothing_else_is_accepted(reply_to: str | None) -> None:
    body = SendMessageRequest(
        message_id="u1", text="yes", reply_to=reply_to, reply_to_message=QUOTED
    )

    assert body.reply_to_message == QUOTED


def test_a_reply_naming_two_different_messages_is_refused_saying_so() -> None:
    with pytest.raises(ValidationError) as refused:
        SendMessageRequest(message_id="u1", text="yes", reply_to="m-2", reply_to_message=QUOTED)

    [error] = refused.value.errors()
    assert error["msg"] == "Value error, reply_to and reply_to_message.id name different messages"


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


def test_a_reply_cut_off_mid_bubble_keeps_the_open_message_for_the_restart() -> None:
    partial = PartialReply(reply_id="r7", bubbles=0, open_message_ids=["2459"])

    assert partial.open_message_ids == ["2459"]


def test_a_send_recorded_before_it_went_out_is_kept_as_an_unconfirmed_last_message() -> None:
    partial = PartialReply(reply_id="r7", bubbles=1, open_message_ids=["2459", None])

    assert partial.open_message_ids == ["2459", None]


def test_an_unconfirmed_send_before_a_confirmed_one_is_refused() -> None:
    with pytest.raises(ValidationError) as refused:
        PartialReply(reply_id="r7", bubbles=1, open_message_ids=[None, "2459"])

    [error] = refused.value.errors()
    assert error["msg"] == ("Value error, only the last open message can be a send never confirmed")


def test_a_partial_reply_with_nothing_on_the_platform_is_refused() -> None:
    with pytest.raises(ValidationError) as refused:
        PartialReply(reply_id="r7", bubbles=0)

    [error] = refused.value.errors()
    assert error["msg"] == "Value error, a partial reply has a final bubble or an open message"
