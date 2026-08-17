"""Unit tests for the Composio Slack tools schemas (slack_tools.py)."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.slack_tools import (
    SlackChannel,
    SlackListAllChannelsData,
    SlackListAllChannelsInput,
)


class TestSlackListAllChannelsInput:
    def test_defaults(self):
        m = SlackListAllChannelsInput()
        assert m.limit == 1
        assert m.channel_name is None
        assert m.cursor is None
        assert m.exclude_archived is None
        assert m.types is None

    def test_valid_full(self):
        m = SlackListAllChannelsInput(
            channel_name="general",
            cursor="xyz",
            exclude_archived=True,
            limit=100,
            types="public_channel",
        )
        assert m.limit == 100
        assert m.types == "public_channel"

    def test_wrong_type_limit(self):
        with pytest.raises(ValidationError):
            SlackListAllChannelsInput(limit="one")


class TestSlackChannel:
    def test_valid_minimal(self):
        m = SlackChannel()
        assert m.id is None
        assert m.name is None

    def test_valid_full(self):
        m = SlackChannel(
            id="C123",
            name="general",
            created=1234567890,
            creator="U123",
            is_archived=False,
            is_channel=True,
            is_general=True,
            is_private=False,
            is_im=False,
            is_mpim=False,
            num_members=42,
        )
        assert m.name == "general"
        assert m.is_general is True
        assert m.num_members == 42

    def test_extra_fields_ignored(self):
        m = SlackChannel(id="C123", topic="ignored")
        assert not hasattr(m, "topic")

    def test_wrong_type_created(self):
        with pytest.raises(ValidationError):
            SlackChannel(created="not-a-timestamp")


class TestSlackListAllChannelsData:
    def test_defaults(self):
        m = SlackListAllChannelsData()
        assert m.channels == []
        assert m.response_metadata is None
        assert m.get_channels() == []
        assert m.next_cursor is None

    def test_get_channels_returns_typed_models(self):
        m = SlackListAllChannelsData(channels=[{"id": "C1"}, {"id": "C2"}])
        channels = m.get_channels()
        assert isinstance(channels[0], SlackChannel)
        assert [c.id for c in channels] == ["C1", "C2"]

    def test_get_channels_skips_non_dicts(self):
        # `channels` is list[dict], so non-dicts can only exist via
        # model_construct (bypasses validation); get_channels must still
        # filter them out.
        m = SlackListAllChannelsData.model_construct(channels=[{"id": "C1"}, "junk", None])
        channels = m.get_channels()
        assert [c.id for c in channels] == ["C1"]

    def test_extra_fields_ignored(self):
        m = SlackListAllChannelsData(channels=[], extra="dropped")
        assert not hasattr(m, "extra")

    def test_next_cursor_present(self):
        m = SlackListAllChannelsData(response_metadata={"next_cursor": "cursor-123"})
        assert m.next_cursor == "cursor-123"

    def test_next_cursor_absent(self):
        m = SlackListAllChannelsData(response_metadata={"no_cursor": "x"})
        assert m.next_cursor is None

    def test_next_cursor_empty_string(self):
        m = SlackListAllChannelsData(response_metadata={"next_cursor": ""})
        assert m.next_cursor == ""

    def test_next_cursor_non_string(self):
        m = SlackListAllChannelsData(response_metadata={"next_cursor": 123})
        assert m.next_cursor is None

    def test_next_cursor_no_metadata(self):
        m = SlackListAllChannelsData()
        assert m.next_cursor is None
