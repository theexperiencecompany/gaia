"""SendMessageRequest: a reply names one message, whether by id or by the quoted message it carries."""

from pydantic import ValidationError
import pytest

from app.models.conversation_send_models import SendMessageRequest
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
