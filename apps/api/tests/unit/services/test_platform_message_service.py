"""Unit tests for the bot-platform message dispatcher.

Verifies the routing guarantee: a conversation source is published to the
correct platform's outbound queue, and non-bot sources are never delivered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    SourceCategory,
)
from app.services import platform_message_service as pms
from app.services.outbound_delivery import OutboundResult


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
        # No conversation_id → DM: no destination override, not a channel send.
        pub.assert_awaited_once_with(
            source, "user-1", ["hello"], destination_override=None, is_channel=False
        )

    async def test_group_conversation_delivers_to_its_channel(self) -> None:
        """A group conversation's bot session carries a channel_id, so the message
        is delivered back to that channel — not the user's DM."""
        session = SimpleNamespace(channel_id="C-group-1")
        with (
            patch.object(
                pms.bot_session_repository,
                "get_by_conversation_id",
                new_callable=AsyncMock,
                return_value=session,
            ) as get_session,
            patch.object(
                pms,
                "publish_outbound_message",
                new_callable=AsyncMock,
                return_value=OutboundResult.PUBLISHED,
            ) as pub,
        ):
            ok = await pms.deliver_message_to_platform(
                ConversationSource.TELEGRAM, "user-1", "hi", conversation_id="conv-g"
            )
        assert ok is True
        # The channel is resolved for THIS conversation, not some other id.
        get_session.assert_awaited_once_with("conv-g")
        pub.assert_awaited_once_with(
            ConversationSource.TELEGRAM,
            "user-1",
            ["hi"],
            destination_override="C-group-1",
            is_channel=True,
        )

    async def test_no_conversation_id_never_looks_up_a_session(self) -> None:
        """Without a conversation_id the DM path is taken directly — the bot-session
        lookup is skipped entirely (guards the falsy-conversation_id short-circuit)."""
        with (
            patch.object(
                pms.bot_session_repository, "get_by_conversation_id", new_callable=AsyncMock
            ) as get_session,
            patch.object(
                pms,
                "publish_outbound_message",
                new_callable=AsyncMock,
                return_value=OutboundResult.PUBLISHED,
            ) as pub,
        ):
            await pms.deliver_message_to_platform(ConversationSource.TELEGRAM, "user-1", "hi")
        get_session.assert_not_awaited()
        pub.assert_awaited_once_with(
            ConversationSource.TELEGRAM,
            "user-1",
            ["hi"],
            destination_override=None,
            is_channel=False,
        )

    @pytest.mark.parametrize("session", [SimpleNamespace(channel_id=None), None])
    async def test_dm_or_missing_session_falls_back_to_dm(self, session: object) -> None:
        """A DM conversation (channel_id=None) and a non-bot conversation (no
        session) both fall back to the DM: no override, not a channel send."""
        with (
            patch.object(
                pms.bot_session_repository,
                "get_by_conversation_id",
                new_callable=AsyncMock,
                return_value=session,
            ),
            patch.object(
                pms,
                "publish_outbound_message",
                new_callable=AsyncMock,
                return_value=OutboundResult.PUBLISHED,
            ) as pub,
        ):
            await pms.deliver_message_to_platform(
                ConversationSource.TELEGRAM, "user-1", "hi", conversation_id="conv-dm"
            )
        pub.assert_awaited_once_with(
            ConversationSource.TELEGRAM,
            "user-1",
            ["hi"],
            destination_override=None,
            is_channel=False,
        )

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


class TestBotPlatformConsistency:
    """Every bot source must be routable by is_bot_platform and categorised as
    a BOT by SourceCategory."""

    @pytest.mark.parametrize("source", sorted(BOT_CONVERSATION_SOURCES, key=lambda s: s.value))
    def test_every_bot_source_is_routable_and_categorised(self, source) -> None:
        assert pms.is_bot_platform(source) is True
        assert SourceCategory.from_source(source) is SourceCategory.BOT
