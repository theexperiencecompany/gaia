"""Unit tests for background-executor message delivery routing.

The key invariant: a background result is delivered over EXACTLY ONE transport,
chosen by the conversation's own source — bot conversations to their platform,
everything else over WebSocket — and the message is always persisted.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import result_delivery as rd, session as sess
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    create_session,
)
from app.models.chat_models import ConversationSource


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _run(
    kind: RunKind = RunKind.LIVE,
    *,
    stream_id: str = "",
    task_id: str | None = None,
) -> ExecutorRun:
    """A run context for delivery tests (defaults: live, non-workflow)."""
    return ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user={"user_id": "user-1"},
        kind=kind,
        task_id=task_id,
        user_message_id=None,
    )


def _session_with_cards(stream_id: str) -> None:
    """Register a session holding one drainable executor tool card."""
    session = create_session(stream_id, RunKind.QUEUED)
    session.tool_events.append(
        {"tool_data": {"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}}
    )


async def _deliver(conv_source, *, comms_text="result text", result_text="raw"):
    """Run deliver_result with all I/O boundaries mocked.

    Returns (save_mock, platform_mock, ws_mock) for assertions. The real
    is_bot_platform routing logic runs unmocked against ``conv_source``.
    """
    with (
        patch.object(
            rd, "narrate_executor_result", new_callable=AsyncMock, return_value=comms_text
        ),
        patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
        patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
        patch.object(
            rd, "_get_conversation_source", new_callable=AsyncMock, return_value=conv_source
        ),
        patch.object(
            rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as platform,
        patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
    ):
        await rd.deliver_result(
            _run(),
            result_text=result_text,
            result_type="final",
        )
    return save, platform, ws


@pytest.mark.unit
class TestDeliverResultRouting:
    @pytest.mark.parametrize(
        "src",
        [
            ConversationSource.WHATSAPP,
            ConversationSource.SLACK,
            ConversationSource.DISCORD,
            ConversationSource.TELEGRAM,
        ],
    )
    async def test_bot_conversation_delivers_to_platform_only(self, src) -> None:
        save, platform, ws = await _deliver(src)

        platform.assert_awaited_once()
        assert platform.await_args.args[0] == src  # routed to the conversation's platform
        assert platform.await_args.args[2] == "result text"  # the comms-generated text
        ws.assert_not_awaited()  # exclusive: no WebSocket fan-out for bots
        save.assert_awaited_once()  # always persisted to history

    @pytest.mark.parametrize("src", [ConversationSource.WEB, ConversationSource.MOBILE, None])
    async def test_non_bot_conversation_broadcasts_over_websocket_only(self, src) -> None:
        save, platform, ws = await _deliver(src)

        ws.assert_awaited_once()
        platform.assert_not_awaited()  # exclusive: no platform send for web/mobile/system
        save.assert_awaited_once()

    async def test_websocket_payload_carries_conversation_and_message(self) -> None:
        _save, _platform, ws = await _deliver(ConversationSource.WEB)
        event = ws.await_args.args[1]
        assert event["type"] == "conversation.new_message"
        assert event["conversation_id"] == "conv-1"
        assert event["message"]["response"] == "result text"

    async def test_falls_back_to_raw_executor_text_when_comms_unavailable(self) -> None:
        # comms returns "" → the raw executor text must still be delivered.
        _save, platform, _ws = await _deliver(
            ConversationSource.WHATSAPP, comms_text="", result_text="raw executor output"
        )
        assert platform.await_args.args[2] == "raw executor output"


@pytest.mark.unit
class TestGetConversationSource:
    """The authoritative routing key: the conversation's persisted source."""

    async def test_returns_coerced_enum_from_stored_string(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value={"source": "whatsapp"})
            src = await rd._get_conversation_source("conv-1", "user-1")
        assert src is ConversationSource.WHATSAPP  # coerced to the enum, not a raw str

    async def test_query_is_scoped_to_conversation_and_owner(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value={"source": "web"})
            await rd._get_conversation_source("conv-1", "user-1")
        # must be scoped by BOTH conversation_id and user_id (no cross-user read)
        assert col.find_one.await_args.args[0] == {
            "conversation_id": "conv-1",
            "user_id": "user-1",
        }

    async def test_missing_conversation_returns_none(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value=None)
            assert await rd._get_conversation_source("conv-1", "user-1") is None

    async def test_unknown_stored_value_coerces_to_none(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value={"source": "legacy_garbage"})
            assert await rd._get_conversation_source("conv-1", "user-1") is None

    async def test_db_error_returns_none(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(side_effect=RuntimeError("mongo down"))
            assert await rd._get_conversation_source("conv-1", "user-1") is None


@pytest.mark.unit
class TestPersistCancelledRun:
    """Cancelled self-owning runs: cards-only persist, no narration, no re-push.

    These pin the "stop the stream → cards survive" fix. The cards were already
    streamed live, so the persisted copy must reconcile with the frontend
    placeholder by message_id == task_id and must NOT go out over the
    WebSocket again.
    """

    async def test_persists_cards_only_message_keyed_by_task_id(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock) as narrate,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            await rd.persist_cancelled_run(run)

        save.assert_awaited_once()
        saved = save.await_args.args[0].messages[0]
        assert saved.message_id == "task-9"  # reconciles with the placeholder by id
        assert saved.response == ""  # cards-only: comms never narrated this turn
        assert saved.tool_data and saved.tool_data[0]["tool_name"] == "tool_calls_data"
        narrate.assert_not_awaited()  # the run was stopped — no re-voicing
        ws.assert_not_awaited()  # no re-broadcast of already-streamed data

    async def test_no_cards_writes_nothing(self) -> None:
        create_session("queued_s1", RunKind.QUEUED)  # session exists, zero events
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run)

        save.assert_not_awaited()

    async def test_save_failure_is_swallowed(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(
            rd, "update_messages", new_callable=AsyncMock, side_effect=RuntimeError("mongo down")
        ):
            await rd.persist_cancelled_run(run)  # must not raise


@pytest.mark.unit
class TestDeliverResultToolDataOwnership:
    """deliver_result attaches drained cards only for self-owning runs, and
    keys queued messages on task_id so sync dedups against the placeholder."""

    async def _deliver_with_session(self, run: ExecutorRun):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd, "_lookup_user_message_content", new_callable=AsyncMock, return_value=""
            ),
        ):
            await rd.deliver_result(run, "raw result", "final")
        return save, ws

    async def test_queued_run_attaches_cards_and_uses_task_id(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        save, ws = await self._deliver_with_session(run)

        saved = save.await_args.args[0].messages[0]
        assert saved.message_id == "task-9"
        assert saved.tool_data and saved.tool_data[0]["tool_name"] == "tool_calls_data"
        ws_message = ws.await_args.args[1]["message"]
        assert ws_message["tool_data"] == saved.tool_data
        assert ws_message["task_id"] == "task-9"

    async def test_live_run_never_self_attaches_cards(self) -> None:
        """The comms stream owns a live run's cards — attaching here too would
        render every card twice on the happy path."""
        _session_with_cards("live_s1")
        run = _run(RunKind.LIVE, stream_id="live_s1", task_id="task-9")

        save, ws = await self._deliver_with_session(run)

        saved = save.await_args.args[0].messages[0]
        assert not saved.tool_data
        assert saved.message_id != "task-9"  # no placeholder to reconcile with
        assert "tool_data" not in ws.await_args.args[1]["message"]

    async def test_save_failure_prevents_any_transport_push(self) -> None:
        """MongoDB is the source of truth — a message that failed to persist
        must never be pushed (it would vanish on the next sync)."""
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(
                rd,
                "update_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock) as source,
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            await rd.deliver_result(run, "raw", "final")

        source.assert_not_awaited()
        platform.assert_not_awaited()
        ws.assert_not_awaited()

    async def test_error_results_get_no_follow_up_suggestions(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="it broke"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock) as follow_ups,
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
        ):
            await rd.deliver_result(run, "traceback...", "error")

        follow_ups.assert_not_awaited()
