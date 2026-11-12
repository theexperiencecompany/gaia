"""Unit tests for deliver_message_to_conversation, the run-free proactive-delivery primitive.

Pins the surface-aware routing (bot platform vs web WebSocket), the checkpoint
record that lets a later turn remember what was delivered, and the guards
(blank text, deleted conversation) — the seams both reminders and tracked todos
build on.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException
import pytest

from app.agents.core.background.result_delivery import (
    deliver_message_to_conversation,
    deliver_result,
)
from app.agents.core.background.session import ExecutorRun, RunKind
from app.agents.core.outcome_review import OutcomeReview
from app.agents.prompts.comms_prompts import outcome_delivery_note
from app.constants.agents import OutcomeState
from app.models.chat_models import ConversationSource, ToolDataEntry
from app.models.conversation_log_models import Notice
from app.models.conversation_models import UpdateMessagesResponse
from app.models.user_models import AuthenticatedUser

MODULE = "app.agents.core.background.result_delivery"


@pytest.fixture(autouse=True)
def _installed_runtime() -> Iterator[None]:
    """Stand in for the runtime ports startup installs; each test records the log write itself."""
    with patch(f"{MODULE}.runtime_ports", MagicMock()):
        yield


SEQ = 7


def _saved_at_seq() -> AsyncMock:
    return AsyncMock(
        return_value=UpdateMessagesResponse(
            conversation_id="conv",
            message="Messages updated",
            modified_count=1,
            message_ids=["saved"],
            message_seqs=[SEQ],
        )
    )


async def test_web_source_broadcasts_over_websocket_and_records() -> None:
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.WEB)
    ws = MagicMock()
    ws.broadcast_to_user = AsyncMock()
    with (
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq),
        patch(f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock) as to_platform,
        patch(f"{MODULE}.accept", new_callable=AsyncMock) as record,
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
    assert event["message"]["seq"] == SEQ
    # No narration ran, so the delivery is logged as a Notice naming its origin.
    record.assert_awaited_once()
    _ports, conversation_id, _user, notice = record.await_args.args
    assert conversation_id == "conv-1"
    assert isinstance(notice, Notice)
    assert "reminder (id r1)" in notice.origin


async def test_bot_source_delivers_to_platform_and_records() -> None:
    convo_repo = MagicMock()
    convo_repo.get_source = AsyncMock(return_value=ConversationSource.TELEGRAM)
    ws = MagicMock()
    ws.broadcast_to_user = AsyncMock()
    with (
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq),
        patch(
            f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as to_platform,
        patch(f"{MODULE}.accept", new_callable=AsyncMock) as record,
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq) as save,
        patch(f"{MODULE}.accept", new_callable=AsyncMock) as record,
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
        patch(f"{MODULE}.accept", new_callable=AsyncMock) as record,
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq) as save,
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        patch(f"{MODULE}._log_delivery_verdict") as verdict,
        patch(f"{MODULE}.accept", new_callable=AsyncMock),
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq),
        patch(
            f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as to_platform,
        patch(f"{MODULE}._log_delivery_verdict") as verdict,
        patch(f"{MODULE}.accept", new_callable=AsyncMock),
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq),
        patch(
            f"{MODULE}.deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as to_platform,
        patch(f"{MODULE}.accept", new_callable=AsyncMock),
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq) as save,
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock),
        patch(f"{MODULE}.accept", new_callable=AsyncMock),
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq),
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        patch(f"{MODULE}.accept", new_callable=AsyncMock),
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
        patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq) as save,
        patch(f"{MODULE}._broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        patch(f"{MODULE}.accept", new_callable=AsyncMock),
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


class TestCommsNarratesARunsResultUnderItsOutcomeNote:
    async def _narrated_input(self, review: OutcomeReview | None) -> str:
        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=USER,
            kind=RunKind.QUEUED,
            task_id="task-1",
            user_message_id=None,
        )
        convo_repo = MagicMock(get_source=AsyncMock(return_value=ConversationSource.WEB))
        with (
            patch(
                f"{MODULE}.narrate_executor_result", new_callable=AsyncMock, return_value="ok"
            ) as narrate,
            patch(f"{MODULE}.generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch(f"{MODULE}.update_messages", new_callable=_saved_at_seq),
            patch(f"{MODULE}.conversation_repository", convo_repo),
            patch(f"{MODULE}.websocket_manager", MagicMock(broadcast_to_user=AsyncMock())),
        ):
            if review is None:
                await deliver_result(run, "raw", "final", tool_data=None)
            else:
                await deliver_result(run, "raw", "final", tool_data=None, review=review)
        return str(narrate.await_args.args[0])

    async def test_a_result_with_no_outcome_note_is_narrated_as_it_came(self) -> None:
        assert await self._narrated_input(None) == "raw"

    async def test_the_outcome_note_follows_the_result(self) -> None:
        problem = "done was declared but no work call succeeded"

        narrated = await self._narrated_input(OutcomeReview(OutcomeState.DONE, problem))

        assert narrated == f"raw{outcome_delivery_note(OutcomeState.DONE, problem)}"
        assert narrated != "raw"

    async def test_a_verified_outcome_is_narrated_under_its_own_reply_shape(self) -> None:
        narrated = await self._narrated_input(OutcomeReview(OutcomeState.ASK, None))

        assert narrated == f"raw{outcome_delivery_note(OutcomeState.ASK, None)}"
        assert narrated != "raw"
