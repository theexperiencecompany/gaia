"""Unit tests for the bot-platform message dispatcher.

These verify the routing guarantee: a conversation source is dispatched to the
correct platform adapter (and only that one), and non-bot sources are never
delivered to any platform.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    SourceCategory,
)
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationStatus,
)
from app.services import platform_message_service as pms
from app.utils.notification.channels.discord import DiscordChannelAdapter
from app.utils.notification.channels.slack import SlackChannelAdapter
from app.utils.notification.channels.telegram import TelegramChannelAdapter
from app.utils.notification.channels.whatsapp import WhatsAppChannelAdapter

# Maps each bot source to the adapter class that must handle it.
_EXPECTED_ADAPTER = {
    ConversationSource.WHATSAPP: WhatsAppChannelAdapter,
    ConversationSource.TELEGRAM: TelegramChannelAdapter,
    ConversationSource.DISCORD: DiscordChannelAdapter,
    ConversationSource.SLACK: SlackChannelAdapter,
}


def _delivered() -> ChannelDeliveryStatus:
    return ChannelDeliveryStatus(channel_type="x", status=NotificationStatus.DELIVERED)


@pytest.mark.unit
class TestIsBotPlatform:
    @pytest.mark.parametrize(
        "source",
        ["whatsapp", "telegram", "discord", "slack", ConversationSource.WHATSAPP],
    )
    def test_bot_sources_are_true(self, source) -> None:
        assert pms.is_bot_platform(source) is True

    @pytest.mark.parametrize(
        "source",
        ["web", "mobile", "workflow_system", "background", "nonsense", None],
    )
    def test_non_bot_sources_are_false(self, source) -> None:
        assert pms.is_bot_platform(source) is False


@pytest.mark.unit
class TestDeliverMessageToPlatform:
    @pytest.mark.parametrize("source", list(_EXPECTED_ADAPTER))
    async def test_routes_to_correct_adapter_only(self, source) -> None:
        """Each bot source reaches its own adapter's deliver_text — and no other."""
        with (
            patch.object(WhatsAppChannelAdapter, "deliver_text", new_callable=AsyncMock) as wa,
            patch.object(TelegramChannelAdapter, "deliver_text", new_callable=AsyncMock) as tg,
            patch.object(DiscordChannelAdapter, "deliver_text", new_callable=AsyncMock) as dc,
            patch.object(SlackChannelAdapter, "deliver_text", new_callable=AsyncMock) as sl,
        ):
            mocks = {
                ConversationSource.WHATSAPP: wa,
                ConversationSource.TELEGRAM: tg,
                ConversationSource.DISCORD: dc,
                ConversationSource.SLACK: sl,
            }
            for m in mocks.values():
                m.return_value = _delivered()

            ok = await pms.deliver_message_to_platform(source, "user-1", "hello")

            assert ok is True
            mocks[source].assert_awaited_once_with("hello", "user-1")
            for other, m in mocks.items():
                if other != source:
                    m.assert_not_awaited()

    @pytest.mark.parametrize("source", ["web", "mobile", "workflow_system", None])
    async def test_non_bot_source_delivers_nothing(self, source) -> None:
        with patch.object(WhatsAppChannelAdapter, "deliver_text", new_callable=AsyncMock) as wa:
            ok = await pms.deliver_message_to_platform(source, "user-1", "hello")
        assert ok is False
        wa.assert_not_awaited()

    async def test_blank_text_is_not_delivered(self) -> None:
        with patch.object(WhatsAppChannelAdapter, "deliver_text", new_callable=AsyncMock) as wa:
            ok = await pms.deliver_message_to_platform("whatsapp", "user-1", "   ")
        assert ok is False
        wa.assert_not_awaited()

    async def test_skipped_status_returns_false(self) -> None:
        skipped = ChannelDeliveryStatus(
            channel_type="whatsapp", status=NotificationStatus.FAILED, skipped=True
        )
        with patch.object(
            WhatsAppChannelAdapter, "deliver_text", new_callable=AsyncMock, return_value=skipped
        ):
            ok = await pms.deliver_message_to_platform("whatsapp", "user-1", "hello")
        assert ok is False

    async def test_adapter_exception_is_swallowed_and_returns_false(self) -> None:
        with patch.object(
            WhatsAppChannelAdapter,
            "deliver_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            ok = await pms.deliver_message_to_platform("whatsapp", "user-1", "hello")
        assert ok is False


@pytest.mark.unit
class TestAdapterRegistryConsistency:
    """Guard against wiring drift: the dispatcher, the domain bot-source set,
    is_bot_platform, and SourceCategory must all agree on the same platforms."""

    def test_registry_matches_domain_bot_sources(self) -> None:
        # If someone adds a bot ConversationSource without an adapter (or vice
        # versa), this fails — a bot user would otherwise silently get nothing.
        assert set(pms._PLATFORM_ADAPTERS) == BOT_CONVERSATION_SOURCES

    @pytest.mark.parametrize("source", sorted(BOT_CONVERSATION_SOURCES, key=lambda s: s.value))
    def test_every_bot_source_is_routable_and_categorised(self, source) -> None:
        assert pms.is_bot_platform(source) is True
        assert SourceCategory.from_source(source) is SourceCategory.BOT


def _aiohttp_session_cm(session: MagicMock) -> MagicMock:
    """Build an `async with aiohttp.ClientSession(...)` mock yielding `session`."""
    cls = MagicMock()
    cls.return_value.__aenter__ = AsyncMock(return_value=session)
    cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return cls


@pytest.mark.unit
class TestDeliverMessageEndToEnd:
    """Full chain through the REAL adapters (only platform-link + HTTP mocked)."""

    @pytest.mark.parametrize("source", list(_EXPECTED_ADAPTER))
    async def test_unlinked_user_returns_false(self, source) -> None:
        # dispatcher -> real adapter -> _get_platform_context -> PlatformLinkService
        with patch("app.utils.notification.channels.external.PlatformLinkService") as svc:
            svc.get_linked_platforms = AsyncMock(return_value={})
            ok = await pms.deliver_message_to_platform(source, "user-1", "hello")
        assert ok is False

    async def test_whatsapp_linked_delivers_via_kapso(self) -> None:
        resp = AsyncMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="")
        post_cm = AsyncMock()
        post_cm.__aenter__ = AsyncMock(return_value=resp)
        post_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = post_cm

        with (
            patch("app.utils.notification.channels.external.PlatformLinkService") as svc,
            patch("app.utils.notification.channels.whatsapp.settings") as wa_settings,
            patch(
                "app.utils.notification.channels.external.aiohttp.ClientSession",
                _aiohttp_session_cm(session),
            ),
        ):
            svc.get_linked_platforms = AsyncMock(
                return_value={"whatsapp": {"platformUserId": "15551234567"}}
            )
            wa_settings.KAPSO_API_KEY = "kapso-key"
            wa_settings.KAPSO_PHONE_NUMBER_ID = "PNID"

            ok = await pms.deliver_message_to_platform("whatsapp", "user-1", "**hi**")

        assert ok is True
        url = session.post.call_args.args[0]
        payload = session.post.call_args.kwargs["json"]
        assert "/messages" in url
        assert payload["to"] == "+15551234567"  # delivered to the linked number
        assert payload["text"]["body"] == "*hi*"  # markdown converted for WhatsApp
