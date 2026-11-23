"""The bot route a restarted bot reads to follow its live conversations again."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import pytest

from app.api.v1.endpoints.bot_conversations import list_active_conversations
from app.constants.chat import ConversationSource
from app.models.conversation_send_models import ActiveBotConversation

MODULE = "app.api.v1.endpoints.bot_conversations"
LIVE = ActiveBotConversation(
    conversation_id="c1", platform_user_id="pu1", channel_id=None, is_dm=True, after_seq=7
)


def _request(*, key_valid: bool) -> MagicMock:
    return MagicMock(state=SimpleNamespace(bot_api_key_valid=key_valid))


async def test_a_bot_gets_its_platforms_live_conversations_and_the_count_is_logged() -> None:
    listed = AsyncMock(return_value=[LIVE])
    with patch(f"{MODULE}.list_active_bot_conversations", listed), patch(f"{MODULE}.log") as log:
        active = await list_active_conversations(
            _request(key_valid=True), ConversationSource.TELEGRAM
        )

    assert active == [LIVE]
    listed.assert_awaited_once_with("telegram")
    log.set.assert_called_once_with(
        operation="list_active_bot_conversations", platform="telegram", active=1
    )


async def test_a_caller_without_the_bot_key_is_refused_before_anything_is_read() -> None:
    listed = AsyncMock(return_value=[LIVE])
    with (
        patch(f"{MODULE}.list_active_bot_conversations", listed),
        pytest.raises(HTTPException) as refused,
    ):
        await list_active_conversations(_request(key_valid=False), ConversationSource.TELEGRAM)

    assert refused.value.status_code == 401
    listed.assert_not_awaited()
