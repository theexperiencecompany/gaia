"""The user's bot-chat replies as the next brief reads them back."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.conversation_models import BotReplyRow
from app.services.briefing import chat_sync

_USER = "user-1"
_SINCE = datetime(2026, 10, 13, 8, tzinfo=UTC)


@pytest.fixture
def replies(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(chat_sync.conversation_repository, "list_bot_replies_since", listing)
    return listing


class TestFormatRepliesBlock:
    async def test_no_replies_says_so(self, replies: AsyncMock) -> None:
        assert await chat_sync.format_replies_block(_USER, _SINCE) == (
            "No replies since the last brief."
        )

    async def test_only_the_newest_handful_since_the_cutoff_is_read(
        self, replies: AsyncMock
    ) -> None:
        await chat_sync.format_replies_block(_USER, _SINCE)

        replies.assert_awaited_once_with(_USER, _SINCE, limit=chat_sync.MAX_REPLY_LINES)
        assert chat_sync.MAX_REPLY_LINES == 10

    async def test_replies_read_oldest_first_tagged_by_platform_on_one_line_each(
        self, replies: AsyncMock
    ) -> None:
        replies.return_value = [
            BotReplyRow(source="telegram", text="sounds   good,\nship it"),
            BotReplyRow(source="slack", text=None),
            BotReplyRow(source="discord", text="morning"),
        ]

        block = await chat_sync.format_replies_block(_USER, _SINCE)

        assert block == "- [discord] morning\n- [slack] \n- [telegram] sounds good, ship it"

    async def test_a_long_reply_is_cut_at_the_limit(self, replies: AsyncMock) -> None:
        at_limit = "a" * chat_sync.MAX_REPLY_CHARS
        replies.return_value = [
            BotReplyRow(source="telegram", text=at_limit + "b"),
            BotReplyRow(source="slack", text=at_limit),
        ]

        block = await chat_sync.format_replies_block(_USER, _SINCE)

        assert block.splitlines() == [f"- [slack] {at_limit}", f"- [telegram] {at_limit}..."]
        assert chat_sync.MAX_REPLY_CHARS == 200
