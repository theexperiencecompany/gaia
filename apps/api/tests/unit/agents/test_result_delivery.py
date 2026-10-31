"""Unit tests for deliver_message_to_conversation, the run-free proactive-delivery primitive.

Pins the surface-aware routing (bot platform vs web WebSocket), the checkpoint
record that lets a later turn remember what was delivered, and the guards
(blank text, deleted conversation) — the seams both reminders and tracked todos
build on.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException

from app.agents.core.background.result_delivery import (
    deliver_message_to_conversation,
    deliver_result,
    record_todo_run_wake,
)
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.constants.todos import TODO_CONVERSATION_MAX_MESSAGES, TodoWakeKind
from app.models.chat_models import ConversationSource, ToolDataEntry
from app.models.message_models import TodoRunWake
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType

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
            user=AuthenticatedUser(user_id="user-1"),
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
            user=AuthenticatedUser(user_id="user-1"),
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
            conversation_id="c", user=AuthenticatedUser(user_id="u"), text="   ", origin="x"
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
            conversation_id="gone", user=AuthenticatedUser(user_id="u"), text="hi", origin="x"
        )

    assert source is None
    record.assert_not_awaited()
    to_platform.assert_not_awaited()


async def test_websocket_path_builds_exact_target_message_and_verdict() -> None:
    # Pins the saved MessageModel, the delivery target (client-keying fields left
    # off for a proactive message), and the logged verdict.
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
            user=AuthenticatedUser(user_id="user-1"),
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
    assert save.await_args.kwargs["user"] == AuthenticatedUser(user_id="user-1")

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
    assert "follow_up_actions" not in broadcast.await_args.kwargs

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
            user=AuthenticatedUser(user_id="user-1"),
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
            conversation_id="conv-3", user=AuthenticatedUser(user_id=""), text="ping", origin="x"
        )

    to_platform.assert_awaited_once_with(
        ConversationSource.TELEGRAM, "", "ping", conversation_id="conv-3"
    )
    convo_repo.get_source.assert_awaited_once_with("conv-3", user_id="")


CARDS: list[ToolDataEntry] = [
    {"tool_name": "browser_task_data", "data": {"kind": "result", "summary": "Booked."}}
]


async def test_delivered_cards_are_saved_on_the_message() -> None:
    # A detached run's cards only exist in the job's feed: unsaved here, the
    # follow-up message renders as bare text and the run's screenshots are lost.
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.WEB)
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock),
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.conversation_repository", convo_repo),
    ):
        await deliver_message_to_conversation(
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            text="Booked the table.",
            origin="browser task (job job-1)",
            tool_data=CARDS,
        )

    assert save.await_args.args[0].messages[0].tool_data == CARDS


async def test_delivered_cards_reach_the_live_client_too() -> None:
    # The client that is already looking at the conversation renders from the
    # broadcast, not from a refetch.
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.WEB)
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock),
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.conversation_repository", convo_repo),
    ):
        await deliver_message_to_conversation(
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            text="Booked the table.",
            origin="browser task (job job-1)",
            tool_data=CARDS,
        )

    assert broadcast.await_args.kwargs["tool_data"] == CARDS


async def test_an_empty_card_feed_delivers_text_only() -> None:
    # An empty list is "no cards", not a card set: persisting it would write an
    # empty tool_data array onto every reminder and proactive message.
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.WEB)
    with (
        patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        patch(f"{MODULE}.record_platform_delivery", new_callable=AsyncMock),
        patch(f"{MODULE}.conversation_repository", convo_repo),
    ):
        await deliver_message_to_conversation(
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            text="Nothing to show.",
            origin="browser task (job job-1)",
            tool_data=[],
        )

    assert save.await_args.args[0].messages[0].tool_data is None
    assert broadcast.await_args.kwargs["tool_data"] is None


USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011")
TODO_CHAT = "todo-chat-1"
WAKE = TodoRunWake(kind=TodoWakeKind.TRIGGER, trigger_names=["github_push"], approval_summary=None)


def _todo_run(**fields: object) -> ExecutorRun:
    return ExecutorRun(
        stream_id="stream-1",
        conversation_id=TODO_CHAT,
        user=USER,
        kind=RunKind.QUEUED,
        task_id="task-1",
        user_message_id=None,
        bot_message_id="placeholder-1",
        todo_run=TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO),
        **fields,
    )


def _is_utc_iso(value: str | None) -> bool:
    return value is not None and datetime.fromisoformat(value).utcoffset() == timedelta(0)


class TestATrackedTodosRunReportIsKeptInItsChat:
    """The executor's own report is the record of the run, saved and pushed under its placeholder."""

    async def _deliver(
        self, result_text: str, result_type: str, tool_data: list[ToolDataEntry] | None
    ) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        ws = MagicMock(broadcast_to_user=AsyncMock())
        with (
            patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
            patch(f"{MODULE}.websocket_manager", ws),
            patch(f"{MODULE}.deliver_todo_run_result", new_callable=AsyncMock) as todo_delivery,
        ):
            assert await deliver_result(
                _todo_run(), result_text, result_type, tool_data=tool_data
            ) == (None, None)
        return save, ws.broadcast_to_user, todo_delivery

    async def test_the_report_and_its_cards_are_saved_and_pushed_to_the_open_chat(self) -> None:
        save, broadcast, todo_delivery = await self._deliver("Deploy is green.", "final", CARDS)

        request = save.await_args.args[0]
        (saved,) = request.messages
        assert request.conversation_id == TODO_CHAT
        assert save.await_args.kwargs == {
            "user": USER,
            "max_messages": TODO_CONVERSATION_MAX_MESSAGES,
        }
        assert (saved.type, saved.response, saved.error, saved.message_id, saved.tool_data) == (
            "bot",
            "Deploy is green.",
            None,
            "placeholder-1",
            CARDS,
        )
        assert _is_utc_iso(saved.date)
        broadcast.assert_awaited_once_with(
            USER.user_id,
            {
                "type": "conversation.new_message",
                "conversation_id": TODO_CHAT,
                "message": {
                    "type": "bot",
                    "response": "Deploy is green.",
                    "message_id": "placeholder-1",
                    "date": saved.date,
                    "kind": saved.kind.value,
                    "tool_data": CARDS,
                    "task_id": "task-1",
                },
            },
        )
        todo_delivery.assert_awaited_once()

    async def test_a_failed_run_is_kept_and_pushed_as_its_error_with_no_empty_cards(self) -> None:
        save, broadcast, _ = await self._deliver("The calendar API was down.", "error", [])

        (saved,) = save.await_args.args[0].messages
        assert (saved.response, saved.error, saved.tool_data) == (
            "",
            "The calendar API was down.",
            None,
        )
        message = broadcast.await_args.args[1]["message"]
        assert (message["response"], message["error"]) == ("", "The calendar API was down.")
        assert "tool_data" not in message

    async def test_a_report_the_chat_could_not_keep_is_not_pushed(self) -> None:
        ws = MagicMock(broadcast_to_user=AsyncMock())
        with (
            patch(
                f"{MODULE}.update_messages",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404),
            ),
            patch(f"{MODULE}.websocket_manager", ws),
            patch(f"{MODULE}.deliver_todo_run_result", new_callable=AsyncMock) as todo_delivery,
        ):
            await deliver_result(_todo_run(), "Deploy is green.", "final", tool_data=None)

        ws.broadcast_to_user.assert_not_awaited()
        # The record and the user's message are independent.
        todo_delivery.assert_awaited_once()


class TestARunsWakeLeadsItInItsChat:
    """What woke a run is a user-side message, saved in the todo's chat and pushed to an open one."""

    async def test_the_wake_is_saved_and_pushed_as_json(self) -> None:
        ws = MagicMock(broadcast_to_user=AsyncMock())
        with (
            patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
            patch(f"{MODULE}.websocket_manager", ws),
        ):
            await record_todo_run_wake(TODO_CHAT, USER, WAKE)

        request = save.await_args.args[0]
        (saved,) = request.messages
        assert request.conversation_id == TODO_CHAT
        assert save.await_args.kwargs == {
            "user": USER,
            "max_messages": TODO_CONVERSATION_MAX_MESSAGES,
        }
        assert (saved.type, saved.response, saved.todo_run_wake) == ("user", "", WAKE)
        assert str(UUID(saved.message_id)) == saved.message_id
        assert _is_utc_iso(saved.date)
        ws.broadcast_to_user.assert_awaited_once_with(
            USER.user_id,
            {
                "type": "conversation.new_message",
                "conversation_id": TODO_CHAT,
                "message": {
                    "type": "user",
                    "response": "",
                    "message_id": saved.message_id,
                    "date": saved.date,
                    "todo_run_wake": {
                        "kind": "trigger",
                        "trigger_names": ["github_push"],
                        "approval_summary": None,
                    },
                },
            },
        )
        # JSON-native, not the enum: the socket payload is serialized as is.
        wake = ws.broadcast_to_user.await_args.args[1]["message"]["todo_run_wake"]
        assert type(wake["kind"]) is str

    async def test_a_wake_the_chat_could_not_keep_is_not_pushed(self) -> None:
        ws = MagicMock(broadcast_to_user=AsyncMock())
        with (
            patch(
                f"{MODULE}.update_messages",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404),
            ),
            patch(f"{MODULE}.websocket_manager", ws),
        ):
            await record_todo_run_wake(TODO_CHAT, USER, WAKE)

        ws.broadcast_to_user.assert_not_awaited()
