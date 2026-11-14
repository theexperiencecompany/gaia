"""deliver_message_to_conversation: one Notice is the record, sent to a bot platform first.

The real-Mongo read path (one entry, no legacy message) is pinned in
tests/integration/real/test_conversation_runtime_real.py.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background.result_delivery import deliver_message_to_conversation
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice
from app.utils.errors import ConversationNotFoundError
from shared.py.conversation_wire import ToolDataEntry

MODULE = "app.agents.core.background.result_delivery"
USER_ID = "507f1f77bcf86cd799439011"
CARD: ToolDataEntry = {"tool_name": "reminder", "data": {"id": "r1"}}


@pytest.fixture(autouse=True)
def _installed_runtime() -> Iterator[None]:
    with patch(f"{MODULE}.runtime_ports", MagicMock()):
        yield


def _source(source: ConversationSource) -> MagicMock:
    repo = MagicMock()
    repo.get_source = AsyncMock(return_value=source)
    return repo


async def _deliver(
    source: ConversationSource, *, sent: bool = True, text: str = "stretch"
) -> tuple[bool, AsyncMock, AsyncMock]:
    with (
        patch(f"{MODULE}.conversation_repository", _source(source)),
        patch(f"{MODULE}.deliver_message_to_platform", AsyncMock(return_value=sent)) as platform,
        patch(f"{MODULE}.accept", new_callable=AsyncMock) as logged,
    ):
        result = await deliver_message_to_conversation(
            conversation_id="conv-1",
            user_id=USER_ID,
            notification_id="n-1",
            text=text,
            origin="reminder",
            tool_data=[CARD],
        )
    return result, platform, logged


def _notice(logged: AsyncMock) -> Notice:
    (call,) = logged.await_args_list
    notice = call.args[3]
    assert isinstance(notice, Notice)
    return notice


async def test_a_web_conversation_gets_one_notice_with_its_cards() -> None:
    result, platform, logged = await _deliver(ConversationSource.WEB)

    assert result is True
    platform.assert_not_awaited()
    notice = _notice(logged)
    assert (notice.id, notice.text, notice.origin, notice.tool_data) == (
        "notice:n-1",
        "stretch",
        "reminder",
        (CARD,),
    )


async def test_a_bot_conversation_is_sent_on_its_platform_then_logged() -> None:
    result, platform, logged = await _deliver(ConversationSource.TELEGRAM)

    assert result is True
    platform.assert_awaited_once()
    assert _notice(logged).text == "stretch"


async def test_a_failed_platform_send_logs_nothing() -> None:
    result, _, logged = await _deliver(ConversationSource.TELEGRAM, sent=False)

    assert result is False
    logged.assert_not_awaited()


async def test_blank_text_delivers_nothing() -> None:
    result, platform, logged = await _deliver(ConversationSource.WEB, text="  ")

    assert result is False
    platform.assert_not_awaited()
    logged.assert_not_awaited()


async def test_a_deleted_conversation_delivers_nothing() -> None:
    with (
        patch(f"{MODULE}.conversation_repository", _source(ConversationSource.WEB)),
        patch(
            f"{MODULE}.accept",
            AsyncMock(side_effect=ConversationNotFoundError(message="gone")),
        ),
    ):
        result = await deliver_message_to_conversation(
            conversation_id="conv-1",
            user_id=USER_ID,
            notification_id="n-1",
            text="stretch",
            origin="reminder",
        )

    assert result is False
