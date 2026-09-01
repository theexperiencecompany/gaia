"""Unit tests for the run-free proactive-delivery primitive
(app.agents.core.background.result_delivery.deliver_message_to_conversation).

Pins the surface-aware routing (bot platform vs web WebSocket), the checkpoint
record that lets a later turn remember what was delivered, and the guards
(blank text, deleted conversation) — the seams both reminders and tracked todos
build on.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.agents.core.background.result_delivery import deliver_message_to_conversation
from app.models.chat_models import ConversationSource

MODULE = "app.agents.core.background.result_delivery"


async def test_web_source_broadcasts_over_websocket_and_records() -> None:
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.WEB)
    ws = MagicMock()
    ws.broadcast_to_user = AsyncMock()
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock),
        patch(f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock) as to_platform,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock) as record,
        patch(f"{MODULE}.conversation_repository", convo_repo),
        patch(f"{MODULE}.websocket_manager", ws),
    ):
        source = await deliver_message_to_conversation(
            conversation_id="conv-1",
            user={"user_id": "user-1"},
            text="time to drink water",
            origin="reminder (id r1)",
        )

    assert source == ConversationSource.WEB
    to_platform.assert_not_awaited()  # web goes over the socket, not a bot API
    ws.broadcast_to_user.assert_awaited_once()
    event = ws.broadcast_to_user.await_args.args[1]
    assert event["type"] == "conversation.new_message"
    assert event["conversation_id"] == "conv-1"
    assert event["message"]["response"] == "time to drink water"
    # No narration ran, so the checkpoint is recorded explicitly, framed with origin.
    record.assert_awaited_once()
    assert record.await_args.args[0] == "conv-1"
    assert "reminder (id r1)" in record.await_args.args[1]


async def test_bot_source_delivers_to_platform_and_records() -> None:
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.TELEGRAM)
    ws = MagicMock()
    ws.broadcast_to_user = AsyncMock()
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock),
        patch(
            f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as to_platform,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock) as record,
        patch(f"{MODULE}.conversation_repository", convo_repo),
        patch(f"{MODULE}.websocket_manager", ws),
    ):
        source = await deliver_message_to_conversation(
            conversation_id="conv-2",
            user={"user_id": "user-1"},
            text="ping",
            origin="reminder (id r1)",
        )

    assert source == ConversationSource.TELEGRAM
    to_platform.assert_awaited_once_with(ConversationSource.TELEGRAM, "user-1", "ping")
    ws.broadcast_to_user.assert_not_awaited()  # bots have no socket
    record.assert_awaited_once()


async def test_blank_text_delivers_nothing() -> None:
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock) as record,
    ):
        source = await deliver_message_to_conversation(
            conversation_id="c", user={"user_id": "u"}, text="   ", origin="x"
        )

    assert source is None
    save.assert_not_awaited()
    record.assert_not_awaited()


async def test_deleted_conversation_returns_none_and_skips_record() -> None:
    # A 404 on save means the conversation was deleted — deliver nothing, and do
    # not record a delivery that never happened.
    with (
        patch(
            f"{MODULE}.update_messages",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404),
        ),
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock) as record,
        patch(f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock) as to_platform,
    ):
        source = await deliver_message_to_conversation(
            conversation_id="gone", user={"user_id": "u"}, text="hi", origin="x"
        )

    assert source is None
    record.assert_not_awaited()
    to_platform.assert_not_awaited()
