"""Unit tests for the conversation-source vocabulary."""

import pytest

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory


class TestConversationSourceCoerce:
    def test_an_enum_member_is_returned_unchanged(self) -> None:
        assert ConversationSource.coerce(ConversationSource.SLACK) is ConversationSource.SLACK

    def test_none_stays_none(self) -> None:
        assert ConversationSource.coerce(None) is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("web", ConversationSource.WEB),
            ("telegram", ConversationSource.TELEGRAM),
            ("workflow_system", ConversationSource.WORKFLOW_SYSTEM),
        ],
    )
    def test_a_stored_string_parses_to_its_member(
        self, raw: str, expected: ConversationSource
    ) -> None:
        assert ConversationSource.coerce(raw) is expected

    @pytest.mark.parametrize("raw", ["", "  ", "myspace", "WEB"])
    def test_an_unrecognised_value_is_none_rather_than_raising(self, raw: str) -> None:
        """Callers compare on members, so a bad value must not blow up the read."""
        assert ConversationSource.coerce(raw) is None


class TestSourceCategoryFromSource:
    @pytest.mark.parametrize(
        "source",
        [ConversationSource.WEB, ConversationSource.MOBILE, ConversationSource.DESKTOP],
    )
    def test_a_first_party_client_is_ui(self, source: ConversationSource) -> None:
        assert SourceCategory.from_source(source) is SourceCategory.UI

    @pytest.mark.parametrize("source", sorted(BOT_CONVERSATION_SOURCES, key=str))
    def test_every_messaging_platform_is_bot(self, source: ConversationSource) -> None:
        assert SourceCategory.from_source(source) is SourceCategory.BOT

    @pytest.mark.parametrize(
        "source",
        [None, "", "myspace", ConversationSource.WORKFLOW_SYSTEM, ConversationSource.BACKGROUND],
    )
    def test_anything_else_falls_back_to_bg(self, source: ConversationSource | str | None) -> None:
        assert SourceCategory.from_source(source) is SourceCategory.BG

    def test_a_raw_string_is_categorised_like_its_member(self) -> None:
        assert SourceCategory.from_source("slack") is SourceCategory.BOT
