"""Unit tests for app/models/composio_schemas/slack.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.slack import (
    SlackChannelCreatedPayload,
    SlackReceiveMessagePayload,
)


class TestSlackReceiveMessagePayload:
    def test_valid_minimal(self):
        m = SlackReceiveMessagePayload()
        assert m.text is None
        assert m.attachments is None

    def test_valid_full(self):
        m = SlackReceiveMessagePayload(
            attachments=[{"id": 1}],
            bot_id="B123",
            channel="C123",
            channel_type="channel",
            team_id="T123",
            text="hello",
            ts="1234567890.123456",
            user="U123",
        )
        assert m.text == "hello"
        assert m.channel == "C123"
        assert m.attachments == [{"id": 1}]
        assert m.ts == "1234567890.123456"

    def test_wrong_type_attachments(self):
        with pytest.raises(ValidationError):
            SlackReceiveMessagePayload(attachments=["not", "a", "dict"])


class TestSlackChannelCreatedPayload:
    def test_valid_minimal(self):
        m = SlackChannelCreatedPayload()
        assert m.created is None
        assert m.name is None

    def test_valid_full(self):
        m = SlackChannelCreatedPayload(
            created=1234567890,
            creator="U123",
            id="C123",
            name="general",
        )
        assert m.created == 1234567890
        assert m.id == "C123"
        assert m.name == "general"

    def test_wrong_type_created(self):
        with pytest.raises(ValidationError):
            SlackChannelCreatedPayload(created="not-a-timestamp")


# ---------------------------------------------------------------------------
