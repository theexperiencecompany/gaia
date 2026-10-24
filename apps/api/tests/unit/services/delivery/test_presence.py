"""Which bot platform the user is chatting on right now, read off their inbound stamps."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.notifications import PRESENCE_ACTIVE_WINDOW_SECONDS
from app.models.chat_models import ConversationSource
from app.services.delivery import presence
from app.services.delivery.presence import (
    most_recent_bot_platform,
    pick_recent_bot_platform,
    record_inbound_activity,
)

USER_ID = "6acc0dac0cc0a00000000001"
NOW = 1_800_000_000
WINDOW = 3 * 60 * 60


def _client(stored: dict[str, str] | None = None) -> MagicMock:
    client = MagicMock()
    client.hset = AsyncMock(return_value=1)
    client.expire = AsyncMock(return_value=True)
    client.hgetall = AsyncMock(return_value=stored or {})
    return client


class TestPresenceStore:
    async def test_an_inbound_turn_stamps_its_platform_and_refreshes_the_window(self) -> None:
        client = _client()
        before = int(datetime.now(UTC).timestamp())
        with patch.object(type(presence.redis_cache), "client", property(lambda _: client)):
            await record_inbound_activity(USER_ID, ConversationSource.TELEGRAM)

        client.hset.assert_awaited_once()
        assert client.hset.await_args.args == (f"user_presence:{USER_ID}",)
        stamp = int(client.hset.await_args.kwargs["mapping"]["telegram"])
        assert before <= stamp <= int(datetime.now(UTC).timestamp())
        assert client.hset.await_args.kwargs["mapping"].keys() == {"telegram"}
        client.expire.assert_awaited_once_with(
            f"user_presence:{USER_ID}", PRESENCE_ACTIVE_WINDOW_SECONDS
        )

    async def test_the_read_picks_from_the_users_own_stamps(self) -> None:
        client = _client({"telegram": str(NOW - 60), "whatsapp": str(NOW - 30)})
        with patch.object(type(presence.redis_cache), "client", property(lambda _: client)):
            picked = await most_recent_bot_platform(
                USER_ID, now=datetime.fromtimestamp(NOW, tz=UTC)
            )

        client.hgetall.assert_awaited_once_with(f"user_presence:{USER_ID}")
        assert picked is ConversationSource.WHATSAPP


class TestPickRecentBotPlatform:
    def test_the_newest_platform_inside_the_window_wins(self) -> None:
        entries = {
            ConversationSource.WHATSAPP.value: str(NOW - 600),
            ConversationSource.TELEGRAM.value: str(NOW - 60),
        }

        assert pick_recent_bot_platform(entries, NOW, WINDOW) is ConversationSource.TELEGRAM

    def test_a_platform_last_used_outside_the_window_is_ignored(self) -> None:
        entries = {
            ConversationSource.TELEGRAM.value: str(NOW - WINDOW - 1),
            ConversationSource.SLACK.value: str(NOW - WINDOW),
        }

        assert pick_recent_bot_platform(entries, NOW, WINDOW) is ConversationSource.SLACK

    def test_everything_stale_is_none(self) -> None:
        entries = {ConversationSource.TELEGRAM.value: str(NOW - WINDOW - 1)}

        assert pick_recent_bot_platform(entries, NOW, WINDOW) is None

    def test_web_only_activity_names_no_bot_platform(self) -> None:
        entries = {
            ConversationSource.WEB.value: str(NOW),
            ConversationSource.DESKTOP.value: str(NOW),
        }

        assert pick_recent_bot_platform(entries, NOW, WINDOW) is None

    def test_a_newer_web_turn_does_not_hide_the_bot_platform(self) -> None:
        entries = {
            ConversationSource.WEB.value: str(NOW),
            ConversationSource.WHATSAPP.value: str(NOW - 120),
        }

        assert pick_recent_bot_platform(entries, NOW, WINDOW) is ConversationSource.WHATSAPP

    def test_unknown_field_names_are_ignored(self) -> None:
        entries = {
            "carrier_pigeon": str(NOW),
            ConversationSource.BACKGROUND.value: str(NOW),
            ConversationSource.DISCORD.value: str(NOW - 30),
        }

        assert pick_recent_bot_platform(entries, NOW, WINDOW) is ConversationSource.DISCORD

    def test_no_entries_is_none(self) -> None:
        assert pick_recent_bot_platform({}, NOW, WINDOW) is None
