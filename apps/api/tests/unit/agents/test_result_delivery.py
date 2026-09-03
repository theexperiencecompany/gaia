"""Unit tests for the run-free proactive-delivery primitive
(app.agents.core.background.result_delivery.deliver_message_to_conversation).

Pins the surface-aware routing (bot platform vs web WebSocket), the checkpoint
record that lets a later turn remember what was delivered, and the guards
(blank text, deleted conversation) — the seams both reminders and tracked todos
build on.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

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
    to_platform.assert_awaited_once_with(
        ConversationSource.TELEGRAM, "user-1", "ping", conversation_id="conv-2"
    )
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


async def test_websocket_path_builds_exact_target_message_and_verdict() -> None:
    # Pin the argument contract deliver_message_to_conversation hands to its
    # collaborators on the web path: the saved MessageModel, the delivery target
    # (all the client-keying fields it must leave off for a proactive message),
    # and the verdict it logs. Spying the seams catches value drift the rendered
    # WebSocket event can't — a target flag behind a skipped branch still differs.
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.WEB)
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        patch(f"{MODULE}._log_delivery_verdict") as verdict,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock) as to_platform,
        patch(f"{MODULE}.conversation_repository", convo_repo),
    ):
        source = await deliver_message_to_conversation(
            conversation_id="conv-1",
            user={"user_id": "user-1"},
            text="drink water",
            origin="reminder (id r1)",
        )

    assert source == ConversationSource.WEB
    to_platform.assert_not_awaited()

    # Source is looked up for THIS conversation and user — not swapped or dropped.
    convo_repo.get_source.assert_awaited_once_with("conv-1", user_id="user-1")

    # The saved bot message carries a real UTC-stamped, uuid-keyed record, saved
    # for the calling user (not a None user).
    saved = save.await_args.args[0].messages[0]
    assert saved.type == "bot"
    assert saved.response == "drink water"
    assert saved.date is not None and saved.date.endswith("+00:00")
    UUID(saved.message_id)  # raises for None / "None"
    assert save.await_args.kwargs["user"] == {"user_id": "user-1"}

    # The delivery target: owner + conversation set, every client-keying field off
    # because a proactive message has no placeholder to replace and no reply quote.
    target = broadcast.await_args.kwargs["target"]
    assert target.user_id == "user-1"
    assert target.conversation_id == "conv-1"
    assert target.task_id is None
    assert target.emit_task_id is False
    assert target.show_reply_quote is False
    assert target.user_message_id is None
    assert target.user_msg_content == ""
    assert broadcast.await_args.kwargs["notification_text"] == "drink water"
    assert broadcast.await_args.kwargs["tool_data"] is None
    assert broadcast.await_args.kwargs["follow_up_actions"] == []

    # The verdict logged for the run: delivered over the websocket, on this source.
    assert verdict.call_args.kwargs["transport"] == "websocket"
    assert verdict.call_args.kwargs["delivered"] is True
    assert verdict.call_args.kwargs["conversation_source"] == ConversationSource.WEB
    assert verdict.call_args.kwargs["message_id"] == saved.message_id


async def test_platform_path_logs_platform_transport_and_delivery() -> None:
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.TELEGRAM)
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock),
        patch(
            f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as to_platform,
        patch(f"{MODULE}._log_delivery_verdict") as verdict,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.conversation_repository", convo_repo),
    ):
        source = await deliver_message_to_conversation(
            conversation_id="conv-2",
            user={"user_id": "user-1"},
            text="ping",
            origin="reminder (id r1)",
        )

    assert source == ConversationSource.TELEGRAM
    to_platform.assert_awaited_once_with(
        ConversationSource.TELEGRAM, "user-1", "ping", conversation_id="conv-2"
    )
    assert verdict.call_args.kwargs["transport"] == "platform"
    assert verdict.call_args.kwargs["delivered"] is True
    assert verdict.call_args.kwargs["conversation_source"] == ConversationSource.TELEGRAM


async def test_missing_user_id_defaults_to_empty_string() -> None:
    # user carries no user_id: the tool falls back to "" (never None or a
    # sentinel) so the platform call still receives a concrete recipient key.
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.TELEGRAM)
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock),
        patch(
            f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as to_platform,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.conversation_repository", convo_repo),
    ):
        await deliver_message_to_conversation(
            conversation_id="conv-3", user={}, text="ping", origin="x"
        )

    to_platform.assert_awaited_once_with(
        ConversationSource.TELEGRAM, "", "ping", conversation_id="conv-3"
    )
    convo_repo.get_source.assert_awaited_once_with("conv-3", user_id="")
