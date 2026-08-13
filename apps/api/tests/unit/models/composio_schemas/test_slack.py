"""Unit tests for ``app.models.composio_schemas.slack`` trigger payloads."""

from app.models.composio_schemas.slack import (
    SlackChannelCreatedPayload,
    SlackReceiveMessagePayload,
)


def test_receive_message_parses_full_payload() -> None:
    payload = SlackReceiveMessagePayload.model_validate(
        {
            "attachments": [{"text": "see attached"}],
            "bot_id": "B1",
            "channel": "C1",
            "channel_type": "channel",
            "team_id": "T1",
            "text": "hello",
            "ts": "1700000000.000100",
            "user": "U1",
        }
    )
    assert payload.text == "hello"
    assert payload.channel == "C1"
    assert payload.user == "U1"
    assert payload.attachments == [{"text": "see attached"}]


def test_receive_message_defaults_to_none() -> None:
    payload = SlackReceiveMessagePayload.model_validate({})
    assert payload.text is None
    assert payload.attachments is None
    assert payload.ts is None


def test_receive_message_attachments_hold_mixed_values() -> None:
    payload = SlackReceiveMessagePayload.model_validate(
        {"attachments": [{"id": 1, "fallback": "txt", "color": "36a64f"}]}
    )
    assert payload.attachments == [{"id": 1, "fallback": "txt", "color": "36a64f"}]


def test_channel_created_parses_with_numeric_timestamp() -> None:
    payload = SlackChannelCreatedPayload.model_validate(
        {"created": 1700000000, "creator": "U1", "id": "C1", "name": "general"}
    )
    assert payload.created == 1700000000
    assert payload.creator == "U1"
    assert payload.name == "general"


def test_channel_created_defaults_to_none() -> None:
    payload = SlackChannelCreatedPayload.model_validate({})
    assert payload.created is None
    assert payload.id is None
