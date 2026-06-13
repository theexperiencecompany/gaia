"""Unit tests for the bot-platform message dispatcher.

Verifies the routing guarantee: a conversation source is published to the
correct platform's outbound queue, and non-bot sources are never delivered.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    SourceCategory,
)
from app.services import platform_message_service as pms
from app.services.outbound_delivery import OutboundResult


@pytest.mark.unit
class TestIsBotPlatform:
    @pytest.mark.parametrize(
        "source",
        ["whatsapp", "telegram", "discord", "slack", ConversationSource.WHATSAPP],
    )
    def test_bot_sources_are_true(self, source: str | ConversationSource) -> None:
        assert pms.is_bot_platform(source) is True

    @pytest.mark.parametrize(
        "source",
        ["web", "mobile", "workflow_system", "background", "nonsense", None],
    )
    def test_non_bot_sources_are_false(self, source: str | None) -> None:
        assert pms.is_bot_platform(source) is False


@pytest.mark.unit
class TestDeliverMessageToPlatform:
    @pytest.mark.parametrize("source", sorted(BOT_CONVERSATION_SOURCES, key=lambda s: s.value))
    async def test_publishes_to_resolved_platform(self, source: ConversationSource) -> None:
        """Each bot source is published with the coerced enum, user id, and text."""
        with patch.object(
            pms,
            "publish_outbound_message",
            new_callable=AsyncMock,
            return_value=OutboundResult.PUBLISHED,
        ) as pub:
            ok = await pms.deliver_message_to_platform(source, "user-1", "hello")
        assert ok is True
        pub.assert_awaited_once_with(source, "user-1", ["hello"])

    @pytest.mark.parametrize("result", [OutboundResult.SKIPPED, OutboundResult.FAILED])
    async def test_non_published_result_returns_false(self, result: OutboundResult) -> None:
        with patch.object(
            pms, "publish_outbound_message", new_callable=AsyncMock, return_value=result
        ):
            ok = await pms.deliver_message_to_platform("whatsapp", "user-1", "hello")
        assert ok is False

    @pytest.mark.parametrize("source", ["web", "mobile", "workflow_system", None])
    async def test_non_bot_source_publishes_nothing(self, source: str | None) -> None:
        with patch.object(pms, "publish_outbound_message", new_callable=AsyncMock) as pub:
            ok = await pms.deliver_message_to_platform(source, "user-1", "hello")
        assert ok is False
        pub.assert_not_awaited()

    async def test_blank_text_is_not_published(self) -> None:
        with patch.object(pms, "publish_outbound_message", new_callable=AsyncMock) as pub:
            ok = await pms.deliver_message_to_platform("whatsapp", "user-1", "   ")
        assert ok is False
        pub.assert_not_awaited()


@pytest.mark.unit
class TestBotPlatformConsistency:
    """Every bot source must be routable by is_bot_platform and categorised as
    a BOT by SourceCategory."""

    @pytest.mark.parametrize("source", sorted(BOT_CONVERSATION_SOURCES, key=lambda s: s.value))
    def test_every_bot_source_is_routable_and_categorised(self, source) -> None:
        assert pms.is_bot_platform(source) is True
        assert SourceCategory.from_source(source) is SourceCategory.BOT
