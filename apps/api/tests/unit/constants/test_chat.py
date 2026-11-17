"""Unit tests for the conversation-source vocabulary."""

import pytest

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory


class TestConversationSourceParse:
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
        assert ConversationSource(raw) is expected

    @pytest.mark.parametrize("raw", ["", "  ", "myspace", "WEB"])
    def test_an_unrecognised_value_raises_instead_of_reading_as_a_default(self, raw: str) -> None:
        with pytest.raises(ValueError, match="is not a valid ConversationSource"):
            ConversationSource(raw)


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
        "source", [ConversationSource.WORKFLOW_SYSTEM, ConversationSource.BACKGROUND]
    )
    def test_a_background_or_workflow_run_is_bg(self, source: ConversationSource) -> None:
        assert SourceCategory.from_source(source) is SourceCategory.BG
