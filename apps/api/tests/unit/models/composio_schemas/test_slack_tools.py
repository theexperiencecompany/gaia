"""Unit tests for the Composio Slack tools schemas (slack_tools.py)."""

from app.models.composio_schemas.slack_tools import SlackChannel, SlackListAllChannelsData


class TestSlackListAllChannelsData:
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
