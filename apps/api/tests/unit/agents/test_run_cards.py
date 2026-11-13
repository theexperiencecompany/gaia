"""Unit tests for run_cards: a tracked todo's own record of its run, and what woke it.

The words that tell the user of a run go through the outbox; the cards and the todo chat's
record of the run stay here.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException

from app.agents.core.background.run_cards import (
    persist_run_cards,
    record_todo_run_report,
    record_todo_run_wake,
)
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.todos import TODO_CONVERSATION_MAX_MESSAGES, TodoWakeKind
from app.models.chat_models import MessageModel, ToolDataEntry
from app.models.message_models import TodoRunWake
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType

MODULE = "app.agents.core.background.run_cards"

CARDS: list[ToolDataEntry] = [
    {"tool_name": "browser_task_data", "data": {"kind": "result", "summary": "Booked."}}
]

USER = AuthenticatedUser(user_id="507f1f77bcf86cd799439011")
TODO_CHAT = "todo-chat-1"
WAKE = TodoRunWake(kind=TodoWakeKind.TRIGGER, trigger_names=["github_push"], approval_summary=None)


def _todo_run() -> ExecutorRun:
    return ExecutorRun(
        stream_id="stream-1",
        conversation_id=TODO_CHAT,
        user=USER,
        kind=RunKind.QUEUED,
        task_id="task-1",
        user_message_id=None,
        bot_message_id="placeholder-1",
        todo_run=TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO, runs_once=True),
    )


def _is_utc_iso(value: str | None) -> bool:
    return value is not None and datetime.fromisoformat(value).utcoffset() == timedelta(0)


class TestATrackedTodosRunReportIsKeptInItsChat:
    """The executor's own report is the record of the run, saved and pushed under its placeholder."""

    async def _deliver(
        self, result_text: str, result_type: str, tool_data: list[ToolDataEntry] | None
    ) -> tuple[AsyncMock, AsyncMock]:
        ws = MagicMock(broadcast_to_user=AsyncMock())
        with (
            patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
            patch("app.services.outbox.transport.ws_speech.websocket_manager", ws),
        ):
            await record_todo_run_report(_todo_run(), result_text, result_type, tool_data)
        return save, ws.broadcast_to_user

    async def test_the_report_and_its_cards_are_saved_and_pushed_to_the_open_chat(self) -> None:
        save, broadcast = await self._deliver("Deploy is green.", "final", CARDS)

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
                "type": "outbox.message",
                "kind": "conversation_message",
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

    async def test_a_failed_run_is_kept_and_pushed_as_its_error_with_no_empty_cards(self) -> None:
        save, broadcast = await self._deliver("The calendar API was down.", "error", [])

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
            patch("app.services.outbox.transport.ws_speech.websocket_manager", ws),
        ):
            await record_todo_run_report(_todo_run(), "Deploy is green.", "final", None)

        ws.broadcast_to_user.assert_not_awaited()


class TestARunsWakeLeadsItInItsChat:
    """What woke a run is a user-side message, saved in the todo's chat and pushed to an open one."""

    async def test_the_wake_is_saved_and_pushed_as_json(self) -> None:
        ws = MagicMock(broadcast_to_user=AsyncMock())
        with (
            patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
            patch("app.services.outbox.transport.ws_speech.websocket_manager", ws),
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
                "type": "outbox.message",
                "kind": "conversation_message",
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
            patch("app.services.outbox.transport.ws_speech.websocket_manager", ws),
        ):
            await record_todo_run_wake(TODO_CHAT, USER, WAKE)

        ws.broadcast_to_user.assert_not_awaited()


def _run(kind: RunKind = RunKind.QUEUED, **fields: Any) -> ExecutorRun:
    return ExecutorRun(
        stream_id="stream-1",
        conversation_id="conv-1",
        user=USER,
        kind=kind,
        task_id="task-1",
        user_message_id=None,
        **fields,
    )


def _approval_card(approval_id: str, status: str) -> ToolDataEntry:
    return {
        "tool_name": APPROVAL_REQUEST_TOOL_NAME,
        "data": {"approval_id": approval_id, "status": status},
    }


class TestAFinishedRunsCardsAreKeptWhereTheyRendered:
    """The words that tell the result come through the outbox; the cards the run streamed stay here."""

    async def _persist(
        self, run: ExecutorRun, cards: list[ToolDataEntry]
    ) -> tuple[AsyncMock, AsyncMock]:
        publish = AsyncMock()
        with (
            patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
            patch(f"{MODULE}.publish_conversation_message", publish),
        ):
            await persist_run_cards(run, cards)
        return save, publish

    async def test_a_detached_runs_cards_replace_the_placeholder_it_streamed_into(self) -> None:
        save, publish = await self._persist(_run(RunKind.QUEUED), CARDS)

        (saved,) = save.await_args.args[0].messages
        assert (saved.message_id, saved.response, saved.tool_data) == ("task-1", "", CARDS)
        pushed = publish.await_args.args[2]
        assert (pushed["message_id"], pushed["task_id"], pushed["tool_data"]) == (
            "task-1",
            "task-1",
            CARDS,
        )

    async def test_a_scheduled_workflows_cards_have_no_placeholder_to_replace(self) -> None:
        save, publish = await self._persist(_run(RunKind.LIVE, workflow_id="wf-1"), CARDS)

        (saved,) = save.await_args.args[0].messages
        assert saved.message_id != "task-1"
        assert str(UUID(saved.message_id)) == saved.message_id
        assert "task_id" not in publish.await_args.args[2]

    async def test_a_run_with_no_cards_writes_and_pushes_nothing(self) -> None:
        save, publish = await self._persist(_run(), [])

        save.assert_not_awaited()
        publish.assert_not_awaited()

    async def test_cards_the_conversation_could_not_keep_are_not_pushed(self) -> None:
        publish = AsyncMock()
        with (
            patch(
                f"{MODULE}.update_messages",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404),
            ),
            patch(f"{MODULE}.publish_conversation_message", publish),
        ):
            await persist_run_cards(_run(), CARDS)

        publish.assert_not_awaited()


class TestARunResumedAfterAnApprovalMergesOntoTheMessageItContinues:
    ORIGINAL = "live-message-1"

    def _resumed(self) -> ExecutorRun:
        return _run(RunKind.QUEUED, bot_message_id=self.ORIGINAL)

    def _existing(self, cards: list[ToolDataEntry]) -> MessageModel:
        return MessageModel(
            type="bot",
            response="I asked for your OK.",
            date="2026-11-10T09:00:00+00:00",
            message_id=self.ORIGINAL,
            tool_data=cards,
        )

    async def _persist(
        self, existing: MessageModel | None, cards: list[ToolDataEntry], *, attached: bool = True
    ) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        repo = MagicMock()
        repo.get_message = AsyncMock(return_value=existing)
        repo.set_message_tool_data = AsyncMock(return_value=attached)
        publish = AsyncMock()
        with (
            patch(f"{MODULE}.conversation_repository", repo),
            patch(f"{MODULE}.update_messages", new_callable=AsyncMock) as save,
            patch(f"{MODULE}.publish_conversation_message", publish),
            patch(f"{MODULE}.get_approval", AsyncMock(return_value=None)),
        ):
            await persist_run_cards(self._resumed(), cards)
        return save, repo.set_message_tool_data, publish

    async def test_its_cards_are_added_to_the_original_message_not_appended_as_a_rival(
        self,
    ) -> None:
        seen = _approval_card("a1", "approved")

        save, attach, publish = await self._persist(self._existing([seen]), CARDS)

        save.assert_not_awaited()
        assert attach.await_args.kwargs["entries"] == [seen, *CARDS]
        pushed = publish.await_args.args[2]
        # The client replaces the message wholesale, so the full set goes out under the original id.
        assert (pushed["message_id"], pushed["tool_data"]) == (self.ORIGINAL, [seen, *CARDS])
        assert pushed["response"] == "I asked for your OK."

    async def test_a_replayed_pending_card_never_resurrects_a_decision_the_user_made(self) -> None:
        decided = _approval_card("a1", "approved")

        _, attach, _ = await self._persist(
            self._existing([decided]), [_approval_card("a1", "pending")]
        )

        assert attach.await_count == 0

    async def test_a_message_deleted_meanwhile_gets_the_cards_as_a_new_one(self) -> None:
        save, _, publish = await self._persist(None, CARDS)

        (saved,) = save.await_args.args[0].messages
        assert saved.message_id != self.ORIGINAL
        assert saved.tool_data == CARDS
        publish.assert_awaited_once()

    async def test_cards_the_original_message_would_not_take_are_saved_as_a_new_message(
        self,
    ) -> None:
        save, _, _ = await self._persist(self._existing([]), CARDS, attached=False)

        (saved,) = save.await_args.args[0].messages
        assert saved.message_id != self.ORIGINAL
