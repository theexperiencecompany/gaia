"""A tool's card leaves the registry as the JSON its published schema names, or not at all."""

from pydantic import ValidationError
import pytest

from app.models.mail_card_models import EmailListItem
from app.models.support_models import SupportRequestType, SupportTicketDraft
from app.models.tool_card_registry import tool_card, tool_card_data


def test_a_card_is_streamed_under_its_tool_name_with_its_fields_under_their_published_keys() -> (
    None
):
    item = EmailListItem(
        sender="Alice <alice@example.com>",
        subject="Lease renewal",
        time="2026-11-27T10:00:00Z",
        thread_id="thread-1",
        id="msg-1",
    )

    assert tool_card("email_fetch_data", [item]) == {
        "email_fetch_data": [
            {
                "from": "Alice <alice@example.com>",
                "subject": "Lease renewal",
                "time": "2026-11-27T10:00:00Z",
                "thread_id": "thread-1",
                "id": "msg-1",
            }
        ]
    }


def test_a_cards_values_are_dumped_as_plain_json() -> None:
    draft = SupportTicketDraft(
        type=SupportRequestType.FEATURE,
        title="Dark mode",
        description="Please",
        user_name="Ada",
        user_email="ada@example.com",
    )

    dumped = tool_card_data("support_ticket_data", [draft])

    assert isinstance(dumped, list)
    (row,) = dumped
    assert isinstance(row, dict)
    assert type(row["type"]) is str
    assert row == {
        "type": "feature",
        "title": "Dark mode",
        "description": "Please",
        "user_name": "Ada",
        "user_email": "ada@example.com",
    }


def test_data_of_another_tools_shape_is_refused() -> None:
    with pytest.raises(ValidationError):
        tool_card_data("email_fetch_data", [{"subject": "no sender"}])


def test_a_tool_with_no_registered_card_is_refused() -> None:
    with pytest.raises(KeyError):
        tool_card("unregistered_data", [])
