"""Picking the ONE chat platform a proactive message lands on."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.notifications import (
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_TELEGRAM,
    DEFAULT_CHAT_CHANNEL_PRIORITY,
)
from app.models.chat_models import ConversationSource
from app.models.user_models import UserDocument
from app.services.delivery import chat_channel
from app.services.delivery.chat_channel import (
    ChatChannel,
    pick_chat_channel,
    resolve_channel_priority,
    resolve_chat_channel,
)

USER_ID = "6acc0dac0cc0a00000000001"
LINKED = {
    CHANNEL_TYPE_TELEGRAM: {"platform": "telegram", "platformUserId": "tg-1"},
    CHANNEL_TYPE_SLACK: {"platform": "slack", "platformUserId": "sl-1"},
}


def _two_linked_user() -> UserDocument:
    """Telegram and Slack both linked and enabled, Slack first in the stored order."""
    return UserDocument.model_validate(
        {
            "id": USER_ID,
            "chat_channel_priority": [CHANNEL_TYPE_SLACK, CHANNEL_TYPE_TELEGRAM],
            "platform_links": {
                "telegram": {"id": "tg-1", "username": "a", "display_name": "A"},
                "slack": {"id": "sl-1", "username": "b", "display_name": "B"},
            },
            "notification_channel_prefs": {},
        }
    )


class TestResolveChannelPriority:
    def test_unset_falls_back_to_the_default_order(self) -> None:
        assert resolve_channel_priority(None) == list(DEFAULT_CHAT_CHANNEL_PRIORITY)

    def test_a_stored_order_is_honoured(self) -> None:
        assert resolve_channel_priority([CHANNEL_TYPE_SLACK, CHANNEL_TYPE_TELEGRAM]) == [
            CHANNEL_TYPE_SLACK,
            CHANNEL_TYPE_TELEGRAM,
        ]

    def test_unknown_platforms_are_dropped(self) -> None:
        # A hand-edited or legacy document must never route a message to a
        # channel the outbound queues do not have.
        assert resolve_channel_priority(["carrier_pigeon", CHANNEL_TYPE_SLACK]) == [
            CHANNEL_TYPE_SLACK
        ]

    def test_an_all_unknown_list_falls_back_rather_than_silencing_the_user(self) -> None:
        assert resolve_channel_priority(["carrier_pigeon"]) == list(DEFAULT_CHAT_CHANNEL_PRIORITY)

    def test_a_non_list_falls_back(self) -> None:
        assert resolve_channel_priority("telegram") == list(  # type: ignore[arg-type] -- a legacy doc really can hold a bare string, and it must not crash a send
            DEFAULT_CHAT_CHANNEL_PRIORITY
        )


class TestPickChatChannel:
    def test_the_first_linked_platform_in_the_order_wins(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_SLACK, CHANNEL_TYPE_TELEGRAM], LINKED, {}, active=None
        )

        assert picked == ChatChannel(source=ConversationSource.SLACK, platform_user_id="sl-1")

    def test_an_unlinked_platform_at_the_top_falls_through(self) -> None:
        picked = pick_chat_channel(
            list(DEFAULT_CHAT_CHANNEL_PRIORITY),
            {CHANNEL_TYPE_SLACK: LINKED[CHANNEL_TYPE_SLACK]},
            {},
            active=None,
        )

        assert picked is not None
        assert picked.source is ConversationSource.SLACK

    def test_a_platform_switched_off_in_notification_settings_falls_through(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_TELEGRAM, CHANNEL_TYPE_SLACK],
            LINKED,
            {CHANNEL_TYPE_TELEGRAM: False},
            active=None,
        )

        assert picked is not None
        assert picked.source is ConversationSource.SLACK

    def test_a_missing_preference_counts_as_enabled(self) -> None:
        picked = pick_chat_channel([CHANNEL_TYPE_TELEGRAM], LINKED, {}, active=None)

        assert picked is not None
        assert picked.source is ConversationSource.TELEGRAM

    def test_a_link_without_an_account_id_falls_through(self) -> None:
        linked = {
            CHANNEL_TYPE_TELEGRAM: {"platform": "telegram", "platformUserId": ""},
            CHANNEL_TYPE_SLACK: LINKED[CHANNEL_TYPE_SLACK],
        }
        picked = pick_chat_channel(
            [CHANNEL_TYPE_TELEGRAM, CHANNEL_TYPE_SLACK], linked, {}, active=None
        )

        assert picked is not None
        assert picked.source is ConversationSource.SLACK

    def test_a_legacy_integer_account_id_is_carried_as_text(self) -> None:
        linked = {CHANNEL_TYPE_TELEGRAM: {"platform": "telegram", "platformUserId": 6222050155}}

        assert pick_chat_channel([CHANNEL_TYPE_TELEGRAM], linked, {}, active=None) == ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="6222050155"
        )

    def test_nothing_usable_is_none_never_every_platform(self) -> None:
        assert pick_chat_channel(list(DEFAULT_CHAT_CHANNEL_PRIORITY), {}, {}, active=None) is None
        assert (
            pick_chat_channel(
                [CHANNEL_TYPE_DISCORD],
                {CHANNEL_TYPE_DISCORD: {"platformUserId": "d"}},
                {CHANNEL_TYPE_DISCORD: False},
                active=None,
            )
            is None
        )


class TestPickChatChannelFollowsTheActivePlatform:
    def test_the_platform_the_user_is_chatting_on_outranks_the_order(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_SLACK, CHANNEL_TYPE_TELEGRAM],
            LINKED,
            {},
            active=ConversationSource.TELEGRAM,
        )

        assert picked == ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1")

    def test_an_active_platform_outside_the_stored_order_still_wins(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_SLACK], LINKED, {}, active=ConversationSource.TELEGRAM
        )

        assert picked is not None
        assert picked.source is ConversationSource.TELEGRAM

    def test_an_active_platform_switched_off_falls_through_to_the_order(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_TELEGRAM, CHANNEL_TYPE_SLACK],
            LINKED,
            {CHANNEL_TYPE_TELEGRAM: False},
            active=ConversationSource.TELEGRAM,
        )

        assert picked is not None
        assert picked.source is ConversationSource.SLACK

    def test_an_active_platform_that_is_not_linked_falls_through_to_the_order(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_TELEGRAM, CHANNEL_TYPE_SLACK],
            LINKED,
            {},
            active=ConversationSource.DISCORD,
        )

        assert picked is not None
        assert picked.source is ConversationSource.TELEGRAM

    def test_no_active_platform_keeps_the_order(self) -> None:
        picked = pick_chat_channel(
            [CHANNEL_TYPE_SLACK, CHANNEL_TYPE_TELEGRAM], LINKED, {}, active=None
        )

        assert picked is not None
        assert picked.source is ConversationSource.SLACK


class TestPickChatChannelRefusesNonBotSources:
    def test_a_linked_platform_that_is_not_a_bot_is_skipped(self) -> None:
        """The web is a conversation source but never a delivery channel."""
        assert pick_chat_channel(["web"], {"web": {"platformUserId": "1"}}, {}, active=None) is None

    def test_an_unknown_platform_with_an_account_id_is_skipped(self) -> None:
        assert (
            pick_chat_channel(["pager"], {"pager": {"platformUserId": "1"}}, {}, active=None)
            is None
        )


class TestResolveChatChannel:
    @pytest.fixture(autouse=True)
    def no_recent_activity(self) -> Iterator[AsyncMock]:
        with patch.object(
            chat_channel, "most_recent_bot_platform", AsyncMock(return_value=None)
        ) as presence:
            yield presence

    async def test_the_platform_the_user_last_wrote_on_outranks_the_stored_order(
        self, no_recent_activity: AsyncMock
    ) -> None:
        no_recent_activity.return_value = ConversationSource.TELEGRAM
        with patch.object(
            chat_channel.user_repository, "get", AsyncMock(return_value=_two_linked_user())
        ):
            picked = await resolve_chat_channel(USER_ID)

        no_recent_activity.assert_awaited_once_with(USER_ID)
        assert picked == ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1")

    async def test_an_unreadable_presence_signal_falls_back_to_the_stored_order(
        self, no_recent_activity: AsyncMock
    ) -> None:
        no_recent_activity.side_effect = ConnectionError("redis down")
        with (
            patch.object(
                chat_channel.user_repository, "get", AsyncMock(return_value=_two_linked_user())
            ),
            patch.object(chat_channel.log, "warning") as warning,
        ):
            picked = await resolve_chat_channel(USER_ID)

        assert picked == ChatChannel(source=ConversationSource.SLACK, platform_user_id="sl-1")
        warning.assert_called_once()
        assert warning.call_args.kwargs["error_type"] == "ConnectionError"

    async def test_reads_order_links_and_preferences_off_one_document(self) -> None:
        user = UserDocument.model_validate(
            {
                "id": USER_ID,
                "chat_channel_priority": [CHANNEL_TYPE_SLACK, CHANNEL_TYPE_TELEGRAM],
                "platform_links": {
                    "telegram": {"id": "tg-1", "username": "a", "display_name": "A"},
                    "slack": {"id": "sl-1", "username": "b", "display_name": "B"},
                },
                "notification_channel_prefs": {"slack": False},
            }
        )
        with patch.object(
            chat_channel.user_repository, "get", AsyncMock(return_value=user)
        ) as read:
            picked = await resolve_chat_channel(USER_ID)

        read.assert_awaited_once_with(USER_ID)
        assert picked == ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1")

    async def test_the_users_stored_order_overrides_the_default_order(self) -> None:
        # Both platforms are linked and enabled, so only the stored order can
        # decide: reading the default instead would silently land the message
        # on telegram (the first default entry).
        with patch.object(
            chat_channel.user_repository, "get", AsyncMock(return_value=_two_linked_user())
        ):
            picked = await resolve_chat_channel(USER_ID)

        assert picked == ChatChannel(source=ConversationSource.SLACK, platform_user_id="sl-1")

    async def test_an_unknown_user_has_no_channel(self) -> None:
        with patch.object(chat_channel.user_repository, "get", AsyncMock(return_value=None)):
            assert await resolve_chat_channel(USER_ID) is None
