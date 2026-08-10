"""Unit tests for background-executor message delivery routing.

The key invariant: a background result is delivered over EXACTLY ONE transport,
chosen by the conversation's own source — bot conversations to their platform,
everything else over WebSocket — and the message is always persisted.
"""

from datetime import datetime
from unittest.mock import AsyncMock, call, patch
import uuid

from fastapi import HTTPException
import pytest

from app.agents.core.background import result_delivery as rd, session as sess
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    create_session,
)
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource, MessageModel
from app.models.message_models import ReplyToMessageData
from app.services.workflow import notifications as wf_notifications


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
    user_message_id: str | None = None,
    workflow_id: str | None = None,
    workflow_title: str = "",
    workflow_notify_on_completion: bool = True,
    user: dict | None = None,
) -> ExecutorRun:
    """A run context for delivery tests (defaults: live, non-workflow)."""
    return ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user=user if user is not None else {"user_id": "user-1"},
        kind=kind,
        task_id=task_id,
        user_message_id=user_message_id,
        workflow_id=workflow_id,
        workflow_title=workflow_title,
        workflow_notify_on_completion=workflow_notify_on_completion,
    )


def _session_with_cards(stream_id: str) -> None:
    """Register a session holding one drainable executor tool card."""
    session = create_session(stream_id, RunKind.QUEUED)
    session.tool_events.append(
        {"tool_data": {"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}}
    )


def _bot_message(response: str = "resp", message_id: str | None = "m-1") -> MessageModel:
    bm = MessageModel(type="bot", response=response, date="2026-01-01T00:00:00+00:00")
    bm.message_id = message_id
    return bm



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


class TestGetConversationSource:
    """The authoritative routing key: the conversation's persisted source.

    Coercion of a stored string into the enum now lives in the repository's
    ``get_source`` (covered by the repository contract tests); here we assert the
    delivery wrapper passes it through, scopes by owner, and fails soft.
    """

    async def test_returns_source_from_repository(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = ConversationSource.WHATSAPP
            src = await rd._get_conversation_source("conv-1", "user-1")
        assert src is ConversationSource.WHATSAPP

    async def test_query_is_scoped_to_conversation_and_owner(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = ConversationSource.WEB
            await rd._get_conversation_source("conv-1", "user-1")
        # must be scoped by BOTH conversation_id and user_id (no cross-user read)
        assert get.await_args.args[0] == "conv-1"
        assert get.await_args.kwargs["user_id"] == "user-1"

    async def test_missing_conversation_returns_none(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = None
            assert await rd._get_conversation_source("conv-1", "user-1") is None

    async def test_db_error_returns_none(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.side_effect = RuntimeError("mongo down")
            assert await rd._get_conversation_source("conv-1", "user-1") is None


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

        # _get_conversation_source is now called before update_messages to
        # determine the delivery path; it IS called even when save fails.
        source.assert_awaited_once()
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


class TestDeliverResultContract:
    """deliver_result's return contract, drain ownership, and best-effort failure.

    The function must hand back the narrated text + saved message id (voice mode
    speaks/bubbles by that id), must drain tool_data ONLY for self-owning runs,
    and must never propagate an internal failure.
    """

    async def test_returns_narrated_text_and_saved_message_id(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            text, message_id = await rd.deliver_result(run, "raw result", "final")

        saved = save.await_args.args[0].messages[0]
        assert text == "voiced"
        assert message_id == saved.message_id
        assert message_id == broadcast.await_args.kwargs["bot_message"].message_id
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_queued_run_returns_task_keyed_message_id(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            _text, message_id = await rd.deliver_result(run, "raw", "final")

        assert message_id == "task-9"
        assert save.await_args.args[0].messages[0].message_id == "task-9"
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_drains_tool_data_only_for_self_owning_runs(self) -> None:
        tool_data = [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}]
        queued = _run(RunKind.QUEUED, stream_id="q1", task_id="task-9")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(rd, "drain_executor_tool_data", return_value=tool_data) as drain,
        ):
            await rd.deliver_result(queued, "raw", "final")

        drain.assert_called_once_with("q1")
        assert broadcast.await_args.kwargs["tool_data"] == tool_data

        live = _run(stream_id="live_s1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(rd, "drain_executor_tool_data", return_value=tool_data) as drain,
        ):
            await rd.deliver_result(live, "raw", "final")

        drain.assert_not_called()
        assert broadcast.await_args.kwargs["tool_data"] is None
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_internal_failure_returns_none_none_and_logs(self) -> None:
        run = _run()
        with (
            patch.object(
                rd,
                "narrate_executor_result",
                new_callable=AsyncMock,
                side_effect=RuntimeError("comms down"),
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "log") as log_mock,
        ):
            result = await rd.deliver_result(run, "raw", "final")

        assert result == (None, None)
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} Background notification delivery failed", error="comms down"
        )

    async def test_comms_receives_exact_context_including_default_returned_note(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ) as narrate,
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            # returned_note deliberately omitted: the default must arrive as "".
            await rd.deliver_result(run, "raw result", "final")

        narrate.assert_awaited_once_with(
            "raw result",
            "final",
            "conv-1",
            run.user,
            returned_note="",
            workflow_id=None,
        )
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_user_without_id_still_delivers_with_empty_user_id(self) -> None:
        run = _run(user={"email": "user@example.com"})
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ) as source,
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
        ):
            await rd.deliver_result(run, "raw", "final")

        source.assert_awaited_once_with("conv-1", "")
        platform.assert_awaited_once_with(ConversationSource.WHATSAPP, "", "voiced")


class TestPersistCancelledRunShape:
    """Exact message shape, id fallback, save args, and every error branch."""

    async def test_saved_message_is_bot_shaped_with_aware_timestamp(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "log") as log_mock,
        ):
            await rd.persist_cancelled_run(run)

        saved = save.await_args.args[0].messages[0]
        assert saved.type == "bot"
        assert saved.response == ""
        assert datetime.fromisoformat(saved.date).utcoffset() is not None
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} Persisted cancelled executor cards",
            message_id="task-9",
            task_id="task-9",
            stream_id="queued_s1",
            tool_card_count=1,
        )

    async def test_save_is_scoped_to_run_conversation_and_user(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run)

        request = save.await_args.args[0]
        assert request.conversation_id == "conv-1"
        assert request.messages[0].message_id == "task-9"
        assert save.await_args.kwargs["user"] == run.user

    async def test_missing_task_id_falls_back_to_fresh_uuid(self) -> None:
        _session_with_cards("queued_s2")
        run = _run(RunKind.QUEUED, stream_id="queued_s2", task_id=None)

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run)

        saved = save.await_args.args[0].messages[0]
        assert saved.message_id is not None
        assert saved.message_id != "None"
        assert uuid.UUID(saved.message_id)

    async def test_no_cards_logs_and_writes_nothing(self) -> None:
        create_session("queued_s1", RunKind.QUEUED)
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "log") as log_mock,
        ):
            await rd.persist_cancelled_run(run)

        save.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} Cancelled executor produced no cards to persist",
            task_id="task-9",
            stream_id="queued_s1",
        )

    async def test_deleted_conversation_404_is_expected(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(
                rd,
                "update_messages",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=404, detail="gone"),
            ),
            patch.object(rd, "log") as log_mock,
        ):
            await rd.persist_cancelled_run(run)  # must not raise

        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} conversation deleted, skipping cancelled card save",
            conversation_id="conv-1",
        )

    async def test_non_404_http_error_is_swallowed_and_logged(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(
                rd,
                "update_messages",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=500, detail="boom"),
            ),
            patch.object(rd, "log") as log_mock,
        ):
            await rd.persist_cancelled_run(run)  # must not raise

        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} Failed to save cancelled executor cards", error="500: boom"
        )


    async def test_save_error_is_swallowed_and_logged(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(
                rd, "update_messages", new_callable=AsyncMock, side_effect=RuntimeError("mongo down")
            ),
            patch.object(rd, "log") as log_mock,
        ):
            await rd.persist_cancelled_run(run)  # must not raise

        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} Failed to save cancelled executor cards", error="mongo down"
        )


class TestNarrateAndDeliverExactCalls:
    """The exact seam calls _narrate_and_deliver makes: narration context, the
    saved message, the transport, and the deferred follow-up spawn."""

    async def test_saved_message_shape_and_save_scope(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            await rd.deliver_result(run, "raw", "final")

        request = save.await_args.args[0]
        saved = request.messages[0]
        assert request.conversation_id == "conv-1"
        assert save.await_args.kwargs["user"] == run.user
        assert saved.type == "bot"
        assert saved.response == "voiced"
        assert saved.message_id != "None"
        assert uuid.UUID(saved.message_id)
        assert datetime.fromisoformat(saved.date).utcoffset() is not None
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_bot_path_forwards_exact_transport_args(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ),
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "log") as log_mock,
        ):
            await rd.deliver_result(run, "raw", "final")

        platform.assert_awaited_once_with(ConversationSource.WHATSAPP, "user-1", "voiced")
        ws.assert_not_awaited()
        saved = save.await_args.args[0].messages[0]
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: delivered message",
            message_id=saved.message_id,
            task_id=None,
            conversation_id="conv-1",
            conversation_source="whatsapp",
            transport="platform",
            delivered=True,
        )

    async def test_ws_path_forwards_exact_broadcast_and_spawn_kwargs(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "_generate_and_push_follow_ups", new_callable=AsyncMock) as gen,
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        broadcast.assert_awaited_once_with(
            user_id="user-1",
            conversation_id="conv-1",
            bot_message=saved,
            notification_text="voiced",
            tool_data=None,
            follow_up_actions=[],
            task_id=None,
            show_reply_quote=False,
            user_message_id=None,
            user_msg_content="",
        )
        gen.assert_called_once_with(
            run=run,
            bot_message=saved,
            result_type="final",
            tool_data=None,
            show_reply_quote=False,
            user_msg_content="",
        )
        spawn.assert_called_once()
        spawn.call_args.args[0].close()

    async def test_delivered_log_reports_websocket_transport(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(rd, "log") as log_mock,
        ):
            await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: delivered message",
            message_id=saved.message_id,
            task_id=None,
            conversation_id="conv-1",
            conversation_source=None,
            transport="websocket",
            delivered=True,
        )
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_queued_ws_run_forwards_cards_and_keyed_task_id(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "_generate_and_push_follow_ups", new_callable=AsyncMock) as gen,
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(rd, "log") as log_mock,
        ):
            _text, message_id = await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        assert message_id == "task-9"
        # the drained cards ride into the deferred follow-up task
        gen.assert_called_once_with(
            run=run,
            bot_message=saved,
            result_type="final",
            tool_data=saved.tool_data,
            show_reply_quote=False,
            user_msg_content="",
        )
        spawn.assert_called_once()
        spawn.call_args.args[0].close()
        # the delivered log carries the task key so ops can correlate
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: delivered message",
            message_id="task-9",
            task_id="task-9",
            conversation_id="conv-1",
            conversation_source=None,
            transport="websocket",
            delivered=True,
        )

    async def test_deleted_conversation_404_returns_none_without_transport(self) -> None:
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
                side_effect=HTTPException(status_code=404, detail="gone"),
            ),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "log") as log_mock,
        ):
            result = await rd.deliver_result(run, "raw", "final")

        assert result == (None, None)
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} conversation deleted, skipping message save",
            conversation_id="conv-1",
        )

    async def test_save_error_returns_none_without_transport(self) -> None:
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
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "log") as log_mock,
        ):
            result = await rd.deliver_result(run, "raw", "final")

        assert result == (None, None)
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: failed to save message", error="mongo down"
        )

    async def test_http_save_error_returns_none_without_transport(self) -> None:
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
                side_effect=HTTPException(status_code=500, detail="boom"),
            ),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "log") as log_mock,
        ):
            result = await rd.deliver_result(run, "raw", "final")

        assert result == (None, None)
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: failed to save message", error="500: boom"
        )


class TestQueuedReplyQuote:
    """Queued runs quoting their triggering user message: the lookup seam, the
    saved replyToMessage, and the WebSocket copy."""

    async def test_queued_run_with_user_message_quotes_it(self) -> None:
        run = _run(
            RunKind.QUEUED,
            stream_id="queued_s1",
            task_id="task-9",
            user_message_id="um-1",
        )
        _session_with_cards("queued_s1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(
                rd.conversation_repository,
                "get_message",
                new_callable=AsyncMock,
                return_value=MessageModel(type="user", response="original ask", date="2026-01-01"),
            ) as get_message,
        ):
            text, message_id = await rd.deliver_result(run, "raw", "final")

        get_message.assert_awaited_once_with("conv-1", "um-1", user_id="user-1")
        saved = save.await_args.args[0].messages[0]
        assert saved.replyToMessage == ReplyToMessageData(
            id="um-1", content="original ask", role="user"
        )
        assert text == "voiced"
        assert message_id == "task-9"
        broadcast_kwargs = broadcast.await_args.kwargs
        assert broadcast_kwargs["show_reply_quote"] is True
        assert broadcast_kwargs["user_message_id"] == "um-1"
        assert broadcast_kwargs["user_msg_content"] == "original ask"
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_queued_run_without_user_message_does_not_quote(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9", user_message_id=None)
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(
                rd.conversation_repository, "get_message", new_callable=AsyncMock
            ) as get_message,
        ):
            await rd.deliver_result(run, "raw", "final")

        get_message.assert_not_awaited()
        saved = save.await_args.args[0].messages[0]
        assert saved.replyToMessage is None
        assert broadcast.await_args.kwargs["show_reply_quote"] is False
        coro = spawn.call_args.args[0]
        coro.close()

    async def test_live_run_never_quotes_even_with_user_message_id(self) -> None:
        run = _run(RunKind.LIVE, user_message_id="um-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(
                rd.conversation_repository, "get_message", new_callable=AsyncMock
            ) as get_message,
        ):
            await rd.deliver_result(run, "raw", "final")

        get_message.assert_not_awaited()
        saved = save.await_args.args[0].messages[0]
        assert saved.replyToMessage is None
        assert broadcast.await_args.kwargs["show_reply_quote"] is False
        coro = spawn.call_args.args[0]
        coro.close()


class TestInlineFollowUps:
    """Single-send paths (bot + workflow) attach suggestions inline; the
    WebSocket path defers them to the background task instead."""

    async def test_bot_path_attaches_inline_follow_ups(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=["q1", "q2"]
            ) as gen,
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ),
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        assert saved.follow_up_actions == ["q1", "q2"]
        gen.assert_awaited_once_with(
            "voiced", "user-1", {"configurable": {"user_id": "user-1"}}
        )
        ws.assert_not_awaited()
        spawn.assert_not_called()

    async def test_bot_path_quoted_context_reaches_suggestion_generation(self) -> None:
        """Queued bot runs carry the quoted user message into the follow-up
        context — the single-send path is inline, so the quote must arrive."""
        run = _run(RunKind.QUEUED, task_id="task-9", user_message_id="um-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
            ) as gen,
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ),
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "spawn_background_task") as spawn,
            patch.object(
                rd.conversation_repository,
                "get_message",
                new_callable=AsyncMock,
                return_value=MessageModel(type="user", response="question", date="2026-01-01"),
            ),
        ):
            await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        assert saved.follow_up_actions == ["q1"]
        gen.assert_awaited_once_with(
            "User request: question\n\nAssistant response: voiced",
            "user-1",
            {"configurable": {"user_id": "user-1"}},
        )
        spawn.assert_not_called()

    async def test_bot_path_follow_up_failure_logs_with_message_context(self) -> None:
        """A failed suggestion LLM call on the single-send path must not abort
        delivery — it logs with the message id and ships without suggestions."""
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd,
                "generate_follow_up_actions",
                new_callable=AsyncMock,
                side_effect=RuntimeError("llm down"),
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ),
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "log") as log_mock,
        ):
            text, message_id = await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        assert text == "voiced"
        assert message_id == saved.message_id
        assert saved.follow_up_actions is None
        platform.assert_awaited_once()  # the answer still ships
        ws.assert_not_awaited()
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: failed to generate follow-up actions",
            error="llm down",
            conversation_id="conv-1",
            message_id=saved.message_id,
        )

    async def test_ws_path_defers_follow_ups_instead_of_attaching(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
            ) as gen,
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(rd, "spawn_background_task") as spawn,
        ):
            await rd.deliver_result(run, "raw", "final")

        saved = save.await_args.args[0].messages[0]
        assert saved.follow_up_actions is None  # never attached inline on the ws path
        gen.assert_not_awaited()
        spawn.assert_called_once()
        spawn.call_args.args[0].close()


class TestWorkflowDelivery:
    """Workflow runs: platform delivery + the proactive notification, gated on
    result type and the workflow's notify_on_completion setting."""

    async def _deliver_workflow(
        self,
        run: ExecutorRun,
        *,
        result_type: str = "final",
        result_text: str = "raw",
        follow_ups: list[str] | None = None,
    ):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="wf done"
            ) as narrate,
            patch.object(
                rd,
                "generate_follow_up_actions",
                new_callable=AsyncMock,
                return_value=follow_ups if follow_ups is not None else [],
            ) as gen,
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd, "deliver_workflow_result_to_platforms", new_callable=AsyncMock
            ) as platforms,
            patch.object(
                wf_notifications, "send_workflow_completion_notification", new_callable=AsyncMock
            ) as completion,
            patch.object(
                wf_notifications, "send_workflow_failure_notification", new_callable=AsyncMock
            ) as failure,
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "log") as log_mock,
        ):
            result = await rd.deliver_result(run, result_text, result_type)
        return result, save, gen, platforms, completion, failure, platform, ws, log_mock, narrate

    async def test_successful_workflow_delivers_to_platforms_and_notifies(self) -> None:
        run = _run(
            RunKind.LIVE,
            workflow_id="wf-1",
            workflow_title="Weekly Report",
            workflow_notify_on_completion=True,
        )
        result, save, _gen, platforms, completion, failure, platform, ws, log_mock, narrate = (
            await self._deliver_workflow(run, follow_ups=["next"])
        )

        text, message_id = result
        saved = save.await_args.args[0].messages[0]
        assert text == "wf done"
        assert message_id == saved.message_id
        # comms is told about the workflow so it voices the result appropriately
        narrate.assert_awaited_once_with(
            "raw",
            "final",
            "conv-1",
            run.user,
            returned_note="",
            workflow_id="wf-1",
        )
        # inline follow-ups on the workflow's single-send path
        assert saved.follow_up_actions == ["next"]
        platforms.assert_awaited_once_with(
            user=run.user, user_id="user-1", notification_text="wf done"
        )
        completion.assert_awaited_once_with(
            workflow_id="wf-1",
            workflow_title="Weekly Report",
            conversation_id="conv-1",
            user_id="user-1",
        )
        failure.assert_not_awaited()
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: workflow notification dispatched",
            workflow_id="wf-1",
            message_id=message_id,
        )

    async def test_failed_workflow_sends_failure_notification_only(self) -> None:
        run = _run(RunKind.LIVE, workflow_id="wf-1", workflow_title="Weekly Report")
        result, save, gen, platforms, completion, failure, _platform, _ws, _log, _narrate = (
            await self._deliver_workflow(run, result_type="error")
        )

        assert result == ("wf done", save.await_args.args[0].messages[0].message_id)
        gen.assert_not_awaited()  # error results never get suggestions
        platforms.assert_not_awaited()  # errors are not re-voiced to platforms
        failure.assert_awaited_once_with(
            workflow_id="wf-1", workflow_title="Weekly Report", user_id="user-1"
        )
        completion.assert_not_awaited()

    async def test_silent_workflow_skips_platforms_and_notification(self) -> None:
        run = _run(
            RunKind.LIVE,
            workflow_id="wf-1",
            workflow_title="Weekly Report",
            workflow_notify_on_completion=False,
        )
        result, _save, _gen, platforms, completion, failure, _platform, _ws, log_mock, _narrate = (
            await self._deliver_workflow(run)
        )

        assert result[0] == "wf done"
        assert result[1] is not None
        platforms.assert_not_awaited()
        completion.assert_not_awaited()
        failure.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: completion notification skipped (workflow is silent)",
            workflow_id="wf-1",
            message_id=result[1],
        )


class TestDispatchWorkflowNotification:
    """The notification dispatch matrix: failures always notify, successes
    respect notify_on_completion, and the dispatch is logged."""

    async def test_error_dispatches_failure_notification(self) -> None:
        with (
            patch.object(
                wf_notifications, "send_workflow_failure_notification", new_callable=AsyncMock
            ) as failure,
            patch.object(
                wf_notifications, "send_workflow_completion_notification", new_callable=AsyncMock
            ) as completion,
            patch.object(rd, "log") as log_mock,
        ):
            await rd._dispatch_workflow_notification(
                msg_type="error",
                workflow_id="wf-1",
                workflow_title="T",
                conversation_id="c",
                user_id="u",
                message_id="m",
            )

        failure.assert_awaited_once_with(workflow_id="wf-1", workflow_title="T", user_id="u")
        completion.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: workflow notification dispatched",
            workflow_id="wf-1",
            message_id="m",
        )

    async def test_success_dispatches_completion_notification(self) -> None:
        with (
            patch.object(
                wf_notifications, "send_workflow_failure_notification", new_callable=AsyncMock
            ) as failure,
            patch.object(
                wf_notifications, "send_workflow_completion_notification", new_callable=AsyncMock
            ) as completion,
            patch.object(rd, "log") as log_mock,
        ):
            # notify_on_completion omitted: the default True must notify.
            await rd._dispatch_workflow_notification(
                msg_type="final",
                workflow_id="wf-1",
                workflow_title="T",
                conversation_id="c",
                user_id="u",
                message_id="m",
            )

        completion.assert_awaited_once_with(
            workflow_id="wf-1", workflow_title="T", conversation_id="c", user_id="u"
        )
        failure.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: workflow notification dispatched",
            workflow_id="wf-1",
            message_id="m",
        )

    async def test_silent_success_skips_both_senders(self) -> None:
        with (
            patch.object(
                wf_notifications, "send_workflow_failure_notification", new_callable=AsyncMock
            ) as failure,
            patch.object(
                wf_notifications, "send_workflow_completion_notification", new_callable=AsyncMock
            ) as completion,
            patch.object(rd, "log") as log_mock,
        ):
            await rd._dispatch_workflow_notification(
                msg_type="final",
                workflow_id="wf-1",
                workflow_title="T",
                conversation_id="c",
                user_id="u",
                message_id="m",
                notify_on_completion=False,
            )

        failure.assert_not_awaited()
        completion.assert_not_awaited()
        log_mock.info.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: completion notification skipped (workflow is silent)",
            workflow_id="wf-1",
            message_id="m",
        )


class TestSafeInlineFollowUps:
    """Best-effort suggestion generation for the single-send path."""

    async def test_forwards_exact_kwargs_and_returns_actions(self) -> None:
        with patch.object(
            rd, "_build_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
        ) as build:
            out = await rd._safe_inline_follow_ups(
                result_type="final",
                notification_text="voiced",
                user_msg_content="question",
                user_id="user-1",
                conversation_id="conv-1",
                message_id="m-1",
            )

        assert out == ["q1"]
        build.assert_awaited_once_with(
            msg_type="final",
            notification_text="voiced",
            user_msg_content="question",
            user_id="user-1",
        )

    async def test_failure_returns_empty_and_logs_exactly(self) -> None:
        with (
            patch.object(
                rd,
                "_build_follow_up_actions",
                new_callable=AsyncMock,
                side_effect=RuntimeError("llm down"),
            ),
            patch.object(rd, "log") as log_mock,
        ):
            out = await rd._safe_inline_follow_ups(
                result_type="final",
                notification_text="voiced",
                user_msg_content="question",
                user_id="user-1",
                conversation_id="conv-1",
                message_id="m-1",
            )

        assert out == []
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: failed to generate follow-up actions",
            error="llm down",
            conversation_id="conv-1",
            message_id="m-1",
        )


class TestBuildFollowUpActions:
    """Only 'final' results get suggestions, composed on the real answer."""

    async def test_non_final_type_gets_no_actions(self) -> None:
        with patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock) as gen:
            out = await rd._build_follow_up_actions(
                msg_type="error",
                notification_text="it broke",
                user_msg_content="",
                user_id="user-1",
            )

        assert out == []
        gen.assert_not_awaited()

    async def test_final_with_user_context_composes_both_parts(self) -> None:
        with patch.object(
            rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
        ) as gen:
            out = await rd._build_follow_up_actions(
                msg_type="final",
                notification_text="answer",
                user_msg_content="question",
                user_id="user-1",
            )

        assert out == ["q1"]
        gen.assert_awaited_once_with(
            "User request: question\n\nAssistant response: answer",
            "user-1",
            {"configurable": {"user_id": "user-1"}},
        )

    async def test_final_without_user_context_uses_response_only(self) -> None:
        with patch.object(
            rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]
        ) as gen:
            out = await rd._build_follow_up_actions(
                msg_type="final",
                notification_text="answer",
                user_msg_content="",
                user_id="user-1",
            )

        assert out == []
        gen.assert_awaited_once_with(
            "answer", "user-1", {"configurable": {"user_id": "user-1"}}
        )


class TestSpawnDeferredFollowUps:
    """The deferred path is spawned with the exact run context — run the
    spawned coroutine to completion to prove the bound kwargs flow through."""

    async def test_spawns_generate_task_with_exact_context(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9", user_message_id="um-1")
        bm = _bot_message("voiced", message_id="task-9")
        tool_data = [{"tool_name": "tool_calls_data", "data": {}}]
        captured: dict[str, object] = {}

        def _capture(coro):
            captured["coro"] = coro
            return coro

        with (
            patch.object(rd, "spawn_background_task", side_effect=_capture) as spawn,
            patch.object(
                rd, "_build_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
            ) as build,
            patch.object(
                rd.conversation_repository,
                "set_message_follow_up_actions",
                new_callable=AsyncMock,
                return_value=True,
            ) as persist,
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
        ):
            rd._spawn_deferred_follow_ups(
                run=run,
                bot_message=bm,
                result_type="final",
                tool_data=tool_data,
                show_reply_quote=True,
                user_msg_content="question",
            )
            await captured["coro"]  # type: ignore[arg-type]

        spawn.assert_called_once()
        build.assert_awaited_once_with(
            msg_type="final",
            notification_text="voiced",
            user_msg_content="question",
            user_id="user-1",
        )
        persist.assert_awaited_once_with(
            "conv-1", user_id="user-1", message_id="task-9", actions=["q1"]
        )
        broadcast.assert_awaited_once_with(
            user_id="user-1",
            conversation_id="conv-1",
            bot_message=bm,
            notification_text="voiced",
            tool_data=tool_data,
            follow_up_actions=["q1"],
            task_id="task-9",
            show_reply_quote=True,
            user_message_id="um-1",
            user_msg_content="question",
        )


class TestGenerateAndPushFollowUps:
    """The deferred background task: persists suggestions in place on the SAME
    message, broadcasts only what will survive a reload, and never crashes."""

    async def _push(
        self,
        run: ExecutorRun,
        *,
        follow_up_actions: list[str],
        persisted: bool = True,
        build_error: Exception | None = None,
    ):
        bm = _bot_message("voiced", message_id="task-9")
        with (
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(
                rd.conversation_repository,
                "set_message_follow_up_actions",
                new_callable=AsyncMock,
                return_value=persisted,
            ) as persist,
        ):
            with patch.object(
                rd,
                "_build_follow_up_actions",
                new_callable=AsyncMock,
                side_effect=build_error
                if build_error is not None
                else None,
                return_value=follow_up_actions,
            ) as build:
                await rd._generate_and_push_follow_ups(
                    run=run,
                    bot_message=bm,
                    result_type="final",
                    tool_data=None,
                    show_reply_quote=False,
                    user_msg_content="",
                )
        return bm, build, persist, broadcast

    async def test_empty_suggestions_skip_persist_and_broadcast(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        bm, _build, persist, broadcast = await self._push(run, follow_up_actions=[])

        assert bm.follow_up_actions is None
        persist.assert_not_awaited()
        broadcast.assert_not_awaited()

    async def test_unpersisted_suggestions_are_never_broadcast(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        bm, _build, persist, broadcast = await self._push(run, follow_up_actions=["q1"], persisted=False)

        assert bm.follow_up_actions == ["q1"]  # staged on the message
        persist.assert_awaited_once_with(
            "conv-1", user_id="user-1", message_id="task-9", actions=["q1"]
        )
        broadcast.assert_not_awaited()

    async def test_persisted_suggestions_broadcast_with_exact_context(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        bm, build, persist, broadcast = await self._push(run, follow_up_actions=["q1"], persisted=True)

        assert bm.follow_up_actions == ["q1"]
        build.assert_awaited_once_with(
            msg_type="final",
            notification_text="voiced",
            user_msg_content="",
            user_id="user-1",
        )
        persist.assert_awaited_once_with(
            "conv-1", user_id="user-1", message_id="task-9", actions=["q1"]
        )
        broadcast.assert_awaited_once_with(
            user_id="user-1",
            conversation_id="conv-1",
            bot_message=bm,
            notification_text="voiced",
            tool_data=None,
            follow_up_actions=["q1"],
            task_id="task-9",
            show_reply_quote=False,
            user_message_id=None,
            user_msg_content="",
        )

    async def test_build_failure_is_swallowed(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        with (
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock) as broadcast,
            patch.object(
                rd.conversation_repository, "set_message_follow_up_actions", new_callable=AsyncMock
            ) as persist,
            patch.object(
                rd,
                "_build_follow_up_actions",
                new_callable=AsyncMock,
                side_effect=RuntimeError("llm down"),
            ),
            patch.object(rd, "log") as log_mock,
        ):
            await rd._generate_and_push_follow_ups(
                run=run,
                bot_message=_bot_message("voiced", message_id="task-9"),
                result_type="final",
                tool_data=None,
                show_reply_quote=False,
                user_msg_content="",
            )

        persist.assert_not_awaited()
        broadcast.assert_not_awaited()
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: deferred follow-up actions failed", error="llm down"
        )

    async def test_broadcast_failure_is_swallowed(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        with (
            patch.object(
                rd,
                "_broadcast_bot_message",
                new_callable=AsyncMock,
                side_effect=RuntimeError("ws down"),
            ) as broadcast,
            patch.object(
                rd.conversation_repository,
                "set_message_follow_up_actions",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(
                rd, "_build_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
            ),
            patch.object(rd, "log") as log_mock,
        ):
            await rd._generate_and_push_follow_ups(
                run=run,
                bot_message=_bot_message("voiced", message_id="task-9"),
                result_type="final",
                tool_data=None,
                show_reply_quote=False,
                user_msg_content="",
            )

        broadcast.assert_awaited_once()
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} deliver_result: deferred follow-up actions failed", error="ws down"
        )

    async def test_log_context_carries_trace_and_run_identity(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9")
        with (
            patch.object(rd, "get_trace_id", return_value="trace-1"),
            patch.object(rd, "log_context") as ctx,
            patch.object(
                rd, "_build_follow_up_actions", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(
                rd.conversation_repository, "set_message_follow_up_actions", new_callable=AsyncMock
            ),
        ):
            await rd._generate_and_push_follow_ups(
                run=run,
                bot_message=_bot_message("voiced", message_id="task-9"),
                result_type="final",
                tool_data=None,
                show_reply_quote=False,
                user_msg_content="",
            )

        ctx.assert_called_once_with(
            "follow_up_generation",
            trace_id="trace-1",
            conversation_id="conv-1",
            task_id="task-9",
        )

    async def test_user_without_id_persists_with_empty_user_id(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-9", user={"email": "user@example.com"})
        with (
            patch.object(
                rd, "_build_follow_up_actions", new_callable=AsyncMock, return_value=["q1"]
            ),
            patch.object(rd, "_broadcast_bot_message", new_callable=AsyncMock),
            patch.object(
                rd.conversation_repository,
                "set_message_follow_up_actions",
                new_callable=AsyncMock,
                return_value=True,
            ) as persist,
        ):
            await rd._generate_and_push_follow_ups(
                run=run,
                bot_message=_bot_message("voiced", message_id="task-9"),
                result_type="final",
                tool_data=None,
                show_reply_quote=False,
                user_msg_content="",
            )

        persist.assert_awaited_once_with(
            "conv-1", user_id="", message_id="task-9", actions=["q1"]
        )


class TestPersistFollowUpActions:
    """The in-place update must return True only when a message actually
    matched — unpersisted suggestions must never be broadcast."""

    async def test_missing_message_id_drops_suggestions(self) -> None:
        with (
            patch.object(
                rd.conversation_repository, "set_message_follow_up_actions", new_callable=AsyncMock
            ) as persist,
            patch.object(rd, "log") as log_mock,
        ):
            ok = await rd._persist_follow_up_actions(
                user_id="user-1", conversation_id="conv-1", message_id=None, follow_up_actions=["q1"]
            )

        assert ok is False
        persist.assert_not_awaited()
        log_mock.warning.assert_called_once_with(
            f"{LogTag.AGENT} _persist_follow_up_actions: missing message_id, dropping follow-ups",
            conversation_id="conv-1",
        )

    async def test_no_matching_message_drops_suggestions(self) -> None:
        with (
            patch.object(
                rd.conversation_repository,
                "set_message_follow_up_actions",
                new_callable=AsyncMock,
                return_value=False,
            ) as persist,
            patch.object(rd, "log") as log_mock,
        ):
            ok = await rd._persist_follow_up_actions(
                user_id="user-1", conversation_id="conv-1", message_id="m-1", follow_up_actions=["q1"]
            )

        assert ok is False
        persist.assert_awaited_once_with("conv-1", user_id="user-1", message_id="m-1", actions=["q1"])
        log_mock.error.assert_called_once_with(
            f"{LogTag.AGENT} _persist_follow_up_actions: no message matched, dropping follow-ups",
            conversation_id="conv-1",
            message_id="m-1",
        )

    async def test_matched_message_returns_true(self) -> None:
        with patch.object(
            rd.conversation_repository,
            "set_message_follow_up_actions",
            new_callable=AsyncMock,
            return_value=True,
        ) as persist:
            ok = await rd._persist_follow_up_actions(
                user_id="user-1", conversation_id="conv-1", message_id="m-1", follow_up_actions=["q1"]
            )

        assert ok is True
        persist.assert_awaited_once_with("conv-1", user_id="user-1", message_id="m-1", actions=["q1"])


class TestBroadcastBotMessage:
    """The exact WebSocket payload contract: keys, conditional fields, and the
    task_id emission rule (only when the saved message is keyed on it)."""

    async def _broadcast(
        self,
        *,
        notification_text: str = "resp",
        tool_data: list | None = None,
        follow_up_actions: list[str] | None = None,
        task_id: str | None = None,
        message_id: str = "m-1",
        show_reply_quote: bool = False,
        user_message_id: str | None = None,
        user_msg_content: str = "",
    ) -> AsyncMock:
        bm = _bot_message("resp", message_id=message_id)
        with patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws:
            await rd._broadcast_bot_message(
                user_id="user-1",
                conversation_id="conv-1",
                bot_message=bm,
                notification_text=notification_text,
                tool_data=tool_data,
                follow_up_actions=follow_up_actions or [],
                task_id=task_id,
                show_reply_quote=show_reply_quote,
                user_message_id=user_message_id,
                user_msg_content=user_msg_content,
            )
        return ws

    async def test_base_payload_is_exact(self) -> None:
        ws = await self._broadcast()

        ws.assert_awaited_once_with(
            "user-1",
            {
                "type": "conversation.new_message",
                "conversation_id": "conv-1",
                "message": {
                    "type": "bot",
                    "response": "resp",
                    "message_id": "m-1",
                    "date": "2026-01-01T00:00:00+00:00",
                },
            },
        )

    async def test_tool_data_and_follow_up_actions_ride_along(self) -> None:
        tool_data = [{"tool_name": "tool_calls_data", "data": {}}]
        ws = await self._broadcast(tool_data=tool_data, follow_up_actions=["q1"])

        payload = ws.await_args.args[1]["message"]
        assert payload["tool_data"] == tool_data
        assert payload["follow_up_actions"] == ["q1"]

    async def test_task_id_only_when_message_is_keyed_on_it(self) -> None:
        # queued run: message_id == task_id → advertised for replaceMessage(task_id)
        queued_ws = await self._broadcast(task_id="task-9", message_id="task-9")
        assert queued_ws.await_args.args[1]["message"]["task_id"] == "task-9"

        # live run: fresh message_id ≠ task_id → must NOT emit the wrong key
        live_ws = await self._broadcast(task_id="task-9", message_id="m-1")
        assert "task_id" not in live_ws.await_args.args[1]["message"]

    async def test_reply_quote_payload_is_exact(self) -> None:
        ws = await self._broadcast(
            show_reply_quote=True, user_message_id="um-1", user_msg_content="original ask"
        )

        assert ws.await_args.args[1]["message"]["replyToMessage"] == {
            "id": "um-1",
            "content": "original ask",
            "role": "user",
        }


class TestLookupUserMessageContent:
    """Reply-preview lookup: exact repository call, 150-char truncation, soft
    failure."""

    async def test_returns_first_150_chars_of_user_message(self) -> None:
        long_text = "x" * 200
        with patch.object(
            rd.conversation_repository,
            "get_message",
            new_callable=AsyncMock,
            return_value=MessageModel(type="user", response=long_text, date="2026-01-01"),
        ) as get_message:
            content = await rd._lookup_user_message_content("conv-1", "um-1", "user-1")

        assert content == "x" * 150
        get_message.assert_awaited_once_with("conv-1", "um-1", user_id="user-1")

    async def test_no_message_id_returns_empty(self) -> None:
        with patch.object(
            rd.conversation_repository, "get_message", new_callable=AsyncMock
        ) as get_message:
            content = await rd._lookup_user_message_content("conv-1", None, "user-1")

        assert content == ""
        get_message.assert_not_awaited()

    async def test_empty_response_falls_back_to_empty_preview(self) -> None:
        with patch.object(
            rd.conversation_repository,
            "get_message",
            new_callable=AsyncMock,
            return_value=MessageModel(type="user", response="", date="2026-01-01"),
        ):
            content = await rd._lookup_user_message_content("conv-1", "um-1", "user-1")

        assert content == ""

    async def test_missing_message_returns_empty(self) -> None:
        with patch.object(
            rd.conversation_repository,
            "get_message",
            new_callable=AsyncMock,
            return_value=None,
        ):
            content = await rd._lookup_user_message_content("conv-1", "um-1", "user-1")

        assert content == ""

    async def test_lookup_error_returns_empty_and_warns(self) -> None:
        with (
            patch.object(
                rd.conversation_repository,
                "get_message",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch.object(rd, "log") as log_mock,
        ):
            content = await rd._lookup_user_message_content("conv-1", "um-1", "user-1")

        assert content == ""
        log_mock.warning.assert_called_once_with(
            f"{LogTag.AGENT} _lookup_user_message_content: failed", error="mongo down"
        )


class TestGetConversationSourceLogging:
    async def test_lookup_failure_warns_exactly(self) -> None:
        with (
            patch.object(
                rd.conversation_repository,
                "get_source",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch.object(rd, "log") as log_mock,
        ):
            src = await rd._get_conversation_source("conv-1", "user-1")

        assert src is None
        log_mock.warning.assert_called_once_with(
            f"{LogTag.AGENT} _get_conversation_source: lookup failed", error="mongo down"
        )


class TestBroadcastMessageRetry:
    """The WebSocket fan-out is best-effort with exactly one retry."""

    async def test_first_failure_retries_once_then_succeeds(self) -> None:
        with (
            patch.object(
                rd.websocket_manager,
                "broadcast_to_user",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("socket closed"), None],
            ) as broadcast,
            patch.object(rd.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            await rd._broadcast_message("user-1", {"type": "conversation.new_message"})

        assert broadcast.await_count == 2
        assert broadcast.await_args.args == ("user-1", {"type": "conversation.new_message"})
        sleep.assert_awaited_once_with(0.5)

    async def test_success_on_first_attempt_never_sleeps(self) -> None:
        with (
            patch.object(
                rd.websocket_manager, "broadcast_to_user", new_callable=AsyncMock
            ) as broadcast,
            patch.object(rd.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            await rd._broadcast_message("user-1", {"type": "conversation.new_message"})

        broadcast.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_double_failure_gives_up_without_raising(self) -> None:
        with (
            patch.object(
                rd.websocket_manager,
                "broadcast_to_user",
                new_callable=AsyncMock,
                side_effect=RuntimeError("socket closed"),
            ) as broadcast,
            patch.object(rd.asyncio, "sleep", new_callable=AsyncMock) as sleep,
            patch.object(rd, "log") as log_mock,
        ):
            await rd._broadcast_message("user-1", {"type": "conversation.new_message"})

        assert broadcast.await_count == 2
        sleep.assert_awaited_once_with(0.5)  # backoff only between the two attempts
        log_mock.warning.assert_has_calls(
            [
                call(
                    f"{LogTag.AGENT} _broadcast_message: broadcast attempt failed",
                    attempt=1,
                    user_id="user-1",
                    error="socket closed",
                ),
                call(
                    f"{LogTag.AGENT} _broadcast_message: broadcast attempt failed",
                    attempt=2,
                    user_id="user-1",
                    error="socket closed",
                ),
            ]
        )
