"""Unit tests for background-executor message delivery.

Two invariants, both owned by ``result_delivery.py``:

* a background result is delivered over EXACTLY ONE transport, chosen by the
  conversation's own source — bot conversations to their platform, everything
  else over WebSocket — and the message is always persisted;
* a HIL-resumed run MERGES onto the original turn's bot message rather than
  appending a rival one, and the merge never duplicates a message, drops cards
  the user already saw, or resurrects an approval they already decided.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi import HTTPException
import pytest

from app.agents.core.background import result_delivery as rd, session as sess
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    create_session,
)
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.chat_models import ConversationSource, MessageModel
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus


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
    bot_message_id: str | None = None,
) -> ExecutorRun:
    """A run context for delivery tests (defaults: live, non-workflow)."""
    return ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user={"user_id": "user-1"},
        kind=kind,
        task_id=task_id,
        user_message_id=None,
        bot_message_id=bot_message_id,
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

    async def test_the_save_is_attributed_to_the_runs_owner(self) -> None:
        """update_messages scopes the write by ``user`` — an unattributed save
        lands on nobody's conversation, so the delivered message is lost."""
        save, _platform, _ws = await _deliver(ConversationSource.WEB)

        assert save.await_args.kwargs["user"] == {"user_id": "user-1"}

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

    async def test_live_run_with_bot_message_id_still_appends_a_fresh_message(self) -> None:
        """Every live turn carries bot_message_id (for a possible HIL pause).
        Its presence alone must not route delivery down the HIL-merge path,
        which races the comms stream's save and drops results on a miss."""
        _session_with_cards("live_s2")
        run = _run(RunKind.LIVE, stream_id="live_s2", task_id="task-10", bot_message_id="ack-msg-1")
        with patch.object(rd, "_merge_resumed_result", new_callable=AsyncMock) as merge:
            save, ws = await self._deliver_with_session(run)

        merge.assert_not_awaited()
        saved = save.await_args.args[0].messages[0]
        assert saved.message_id != "ack-msg-1"
        assert saved.message_id != "task-10"

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


class TestDeliverResultHilResume:
    """A HIL-resumed run (``run.bot_message_id`` set) merges its result onto the
    ORIGINAL live turn's message in place, instead of appending a rival one —
    the same class of trap ``_persist_follow_up_actions`` already guards
    against for follow-ups (see its docstring)."""

    async def _deliver_resumed(self, run: ExecutorRun, *, existing_tool_data=None):
        existing = MessageModel(type="bot", response="old text", date="2026-01-01")
        existing.tool_data = existing_tool_data
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="new voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd.conversation_repository,
                "get_message",
                new_callable=AsyncMock,
                return_value=existing,
            ) as get_msg,
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new_callable=AsyncMock,
                return_value=True,
            ) as set_resp,
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new_callable=AsyncMock,
                return_value=True,
            ) as set_td,
        ):
            result = await rd.deliver_result(run, "raw result", "final")
        return result, save, ws, get_msg, set_resp, set_td

    async def test_merges_onto_original_message_instead_of_appending(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(
            RunKind.QUEUED,
            stream_id="queued_s1",
            task_id="task-resume-1",
            bot_message_id="orig-msg-1",
        )

        (text, message_id), save, ws, get_msg, set_resp, set_td = await self._deliver_resumed(run)

        assert message_id == "orig-msg-1"  # reconciles onto the ORIGINAL message, not task_id
        save.assert_not_awaited()  # never $push's a rival array element

        # Read twice on purpose: once by _approval_outcomes_note to ground the
        # narration in this run's decided gates, once by the merge itself. What
        # matters is that BOTH target the original message, never the task_id.
        assert get_msg.await_count == 2
        assert all(call.args[1] == "orig-msg-1" for call in get_msg.await_args_list)
        assert get_msg.await_args.args == ("conv-1", "orig-msg-1")

        set_resp.assert_awaited_once()
        assert set_resp.await_args.kwargs["message_id"] == "orig-msg-1"
        assert set_resp.await_args.kwargs["response"] == "new voiced"

        set_td.assert_awaited_once()
        assert set_td.await_args.kwargs["message_id"] == "orig-msg-1"

        # A live task_id-keyed placeholder DOES exist for queued-kind runs
        # (real queue pops AND resumes), so task_id must still be emitted —
        # otherwise the frontend's placeholder is orphaned forever.
        ws_message = ws.await_args.args[1]["message"]
        assert ws_message["message_id"] == "orig-msg-1"
        assert ws_message["task_id"] == "task-resume-1"

    async def test_merged_tool_data_carries_original_plus_new_cards(self) -> None:
        _session_with_cards("queued_s1")
        run = _run(
            RunKind.QUEUED,
            stream_id="queued_s1",
            task_id="task-resume-1",
            bot_message_id="orig-msg-1",
        )
        existing_cards = [{"tool_name": "old_tool", "data": {}}]

        (_text, _mid), _save, ws, _get_msg, _set_resp, _set_td = await self._deliver_resumed(
            run, existing_tool_data=existing_cards
        )

        # A WebSocket push replaces the client's stored message wholesale, so
        # dropping either half here would erase real cards from the user's view.
        ws_message = ws.await_args.args[1]["message"]
        tool_names = [c["tool_name"] for c in ws_message["tool_data"]]
        assert "old_tool" in tool_names
        assert "tool_calls_data" in tool_names  # the resumed run's new card

    async def test_missing_original_message_falls_back_to_a_fresh_append(self) -> None:
        """The approved action already RAN — a deleted original bubble must
        not discard its report. The delivery re-keys to a fresh id and takes
        the ordinary append path instead."""
        run = _run(RunKind.QUEUED, task_id="task-resume-1", bot_message_id="orig-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                rd.conversation_repository, "get_message", new_callable=AsyncMock, return_value=None
            ),
            patch.object(rd, "log") as mock_log,
        ):
            text, message_id = await rd.deliver_result(run, "raw", "final")

        assert text == "voiced"
        save.assert_awaited_once()
        saved = save.await_args.args[0].messages[0]
        # A fresh REAL id, NOT the dead original and NOT the task id — nothing
        # on the client reconciles against either for this fallback message.
        assert saved.message_id == message_id
        assert saved.message_id != "orig-msg-1"
        UUID(saved.message_id)
        ws.assert_awaited_once()
        # The fallback is loud, and names the message it could not merge onto.
        # Exact tail, not a substring — a mangled message still CONTAINS the
        # substring, so only equality can catch it.
        warning = next(
            c for c in mock_log.warning.call_args_list if "original_message_id" in c.kwargs
        )
        assert warning.args[0].endswith(
            "original message unavailable, appending a fresh one instead"
        )
        assert warning.kwargs["original_message_id"] == "orig-msg-1"
        assert warning.kwargs["conversation_id"] == run.conversation_id


def _approval_card(approval_id: str, status: str, **extra) -> dict:
    return {
        "tool_name": APPROVAL_REQUEST_TOOL_NAME,
        "data": {"approval_id": approval_id, "status": status, **extra},
    }


def _record(approval_id: str, status: HILApprovalStatus, tool_name: str = "SEND_GMAIL"):
    return HILApprovalRecord(
        approval_id=approval_id,
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        tool_name=tool_name,
        status=status,
        decided_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )


class TestApprovalId:
    """The key every merge decision is made on. Reading it off the wrong kind
    of card silently turns an ordinary tool card into an approval and lets the
    upsert overwrite it."""

    def test_an_approval_card_yields_its_id(self) -> None:
        assert rd._approval_id(_approval_card("a1", "pending")) == "a1"

    def test_an_ordinary_tool_card_is_not_an_approval(self) -> None:
        entry = {"tool_name": "web_search_tool", "data": {"approval_id": "a1"}}
        assert rd._approval_id(entry) is None

    def test_a_non_dict_payload_is_not_an_approval(self) -> None:
        assert rd._approval_id({"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": "a1"}) is None

    def test_a_non_string_id_is_rejected(self) -> None:
        entry = {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": {"approval_id": 17}}
        assert rd._approval_id(entry) is None

    def test_a_card_with_no_id_at_all_is_rejected(self) -> None:
        entry = {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": {}}
        assert rd._approval_id(entry) is None


class TestMergeToolData:
    """The resumed stream replays the gate-time PENDING frame after the decision
    already landed. Appending blindly resurrects a decided card."""

    def test_ordinary_cards_append_after_the_existing_ones(self) -> None:
        existing = [{"tool_name": "old_tool", "data": {}}]
        new = [{"tool_name": "new_tool", "data": {}}]

        merged = rd._merge_tool_data(existing, new)

        assert [e["tool_name"] for e in merged] == ["old_tool", "new_tool"]

    def test_an_unseen_approval_appends(self) -> None:
        merged = rd._merge_tool_data([], [_approval_card("a1", "pending")])

        assert merged == [_approval_card("a1", "pending")]

    def test_a_replayed_pending_never_downgrades_a_settled_decision(self) -> None:
        """The bug this function exists for: the user decided, then the replay
        put the pending card back and re-offered approve/decline."""
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved")], [_approval_card("a1", "pending")]
        )

        assert len(merged) == 1, "the replay duplicated the card instead of upserting"
        assert merged[0]["data"]["status"] == "approved"

    @pytest.mark.parametrize(
        "settled", ["approved", "denied", "timeout", "abandoned", "auto_approved"]
    )
    def test_every_settled_status_survives_a_pending_replay(self, settled: str) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", settled)], [_approval_card("a1", "pending")]
        )

        assert merged[0]["data"]["status"] == settled

    def test_a_settled_decision_overwrites_a_pending_card(self) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", "pending")], [_approval_card("a1", "denied")]
        )

        assert len(merged) == 1
        assert merged[0]["data"]["status"] == "denied"

    def test_a_later_settled_frame_replaces_an_earlier_one(self) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved", note="first")],
            [_approval_card("a1", "approved", note="second")],
        )

        assert len(merged) == 1
        assert merged[0]["data"]["note"] == "second"

    def test_different_approvals_do_not_collide(self) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved")],
            [_approval_card("a2", "pending"), _approval_card("a1", "pending")],
        )

        by_id = {e["data"]["approval_id"]: e["data"]["status"] for e in merged}
        assert by_id == {"a1": "approved", "a2": "pending"}

    def test_an_approval_added_in_this_batch_is_upserted_not_duplicated(self) -> None:
        """The index has to learn about ids appended during the same pass, or a
        card that first appears in the new batch duplicates itself."""
        merged = rd._merge_tool_data(
            [], [_approval_card("a1", "pending"), _approval_card("a1", "approved")]
        )

        assert len(merged) == 1
        assert merged[0]["data"]["status"] == "approved"

    def test_the_existing_list_is_not_mutated(self) -> None:
        existing = [{"tool_name": "old_tool", "data": {}}]

        rd._merge_tool_data(existing, [{"tool_name": "new_tool", "data": {}}])

        assert [e["tool_name"] for e in existing] == ["old_tool"]


class TestReconcileApprovalStatuses:
    """A decision's resolved frame goes to whichever stream the user is watching
    at that moment, so it may never reach the stream this delivery drains. The
    record is the source of truth."""

    async def test_a_stale_status_is_corrected_from_the_record(self) -> None:
        with patch.object(
            rd,
            "get_approval",
            new=AsyncMock(return_value=_record("a1", HILApprovalStatus.APPROVED)),
        ):
            out = await rd._reconcile_approval_statuses([_approval_card("a1", "pending")])

        assert out[0]["data"]["status"] == HILApprovalStatus.APPROVED

    async def test_the_input_entry_is_not_mutated(self) -> None:
        entry = _approval_card("a1", "pending")
        with patch.object(
            rd,
            "get_approval",
            new=AsyncMock(return_value=_record("a1", HILApprovalStatus.DENIED)),
        ):
            await rd._reconcile_approval_statuses([entry])

        assert entry["data"]["status"] == "pending", "reconciling mutated the caller's entry"

    async def test_an_ordinary_card_is_passed_through_untouched(self) -> None:
        entry = {"tool_name": "web_search_tool", "data": {"status": "pending"}}
        with patch.object(rd, "get_approval", new=AsyncMock()) as get:
            out = await rd._reconcile_approval_statuses([entry])

        assert out == [entry]
        get.assert_not_awaited(), "an ordinary card triggered an approvals lookup"

    async def test_a_missing_record_leaves_the_card_alone(self) -> None:
        with patch.object(rd, "get_approval", new=AsyncMock(return_value=None)):
            out = await rd._reconcile_approval_statuses([_approval_card("a1", "pending")])

        assert out[0]["data"]["status"] == "pending"

    async def test_an_already_correct_status_is_left_as_is(self) -> None:
        with patch.object(
            rd,
            "get_approval",
            new=AsyncMock(return_value=_record("a1", HILApprovalStatus.APPROVED)),
        ):
            out = await rd._reconcile_approval_statuses([_approval_card("a1", "approved")])

        assert out[0]["data"]["status"] == "approved"


class TestApprovalOutcomesNote:
    """Ground truth handed to the narrator so it stops telling the user an
    action is still waiting for approval after they decided it."""

    async def test_no_original_message_means_no_note(self) -> None:
        assert await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id=None)) == ""

    async def test_a_message_without_cards_means_no_note(self) -> None:
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        with patch.object(
            rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
        ):
            assert (
                await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))
                == ""
            )

    async def test_a_decided_approval_is_reported_by_its_outcome(self) -> None:
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        message.tool_data = [_approval_card("a1", "pending")]
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
            ),
            patch.object(
                rd,
                "get_approval",
                new=AsyncMock(return_value=_record("a1", HILApprovalStatus.DENIED)),
            ),
        ):
            note = await rd._approval_outcomes_note(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1")
            )

        assert "SEND_GMAIL" in note
        assert "the action did NOT run" in note

    async def test_an_undecided_approval_produces_no_note(self) -> None:
        """A still-pending gate has no outcome to report — saying anything about
        it is what the note exists to prevent."""
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        message.tool_data = [_approval_card("a1", "pending")]
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
            ),
            patch.object(
                rd,
                "get_approval",
                new=AsyncMock(return_value=_record("a1", HILApprovalStatus.PENDING)),
            ),
        ):
            assert (
                await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))
                == ""
            )

    async def test_a_lookup_failure_degrades_to_no_note(self) -> None:
        """The note is an enhancement; losing it must not take the delivery down."""
        with patch.object(
            rd.conversation_repository,
            "get_message",
            new=AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert (
                await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))
                == ""
            )


class TestMergeResumedResultFailurePaths:
    """Every one of these is a write that silently matched nothing. Reporting
    success here loses the user's result or their cards."""

    async def _merge(
        self, *, existing, set_response=True, set_tool_data=True, new_cards=None, calls=None
    ):
        bot_message = MessageModel(type="bot", response="new text", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ) as get_msg,
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=set_response),
            ) as set_resp,
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=set_tool_data),
            ) as set_td,
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            merged = await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"), bot_message, new_cards
            )
        if calls is not None:
            calls.update(get_message=get_msg, set_response=set_resp, set_tool_data=set_td)
        return merged

    async def test_a_missing_original_message_returns_none(self) -> None:
        assert await self._merge(existing=None) is None

    async def test_a_response_write_that_matched_nothing_returns_none(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")

        assert await self._merge(existing=existing, set_response=False) is None

    async def test_a_failed_card_write_keeps_the_cards_the_user_already_saw(self) -> None:
        """Falling back to the merged list would report cards that were never
        stored; falling back to nothing would blank the user's rendered turn."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]

        merged = await self._merge(
            existing=existing,
            set_tool_data=False,
            new_cards=[{"tool_name": "new_tool", "data": {}}],
        )

        assert [e["tool_name"] for e in merged] == ["old_tool"]

    async def test_a_successful_merge_returns_original_plus_new_cards(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]

        merged = await self._merge(
            existing=existing, new_cards=[{"tool_name": "new_tool", "data": {}}]
        )

        assert [e["tool_name"] for e in merged] == ["old_tool", "new_tool"]

    async def _merge_with_follow_ups(self, actions):
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        bot_message = MessageModel(type="bot", response="new text", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        bot_message.follow_up_actions = actions
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                rd.conversation_repository, "set_message_follow_up_actions", new=AsyncMock()
            ) as set_fu,
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"), bot_message, None
            )
        return set_fu

    async def test_follow_up_actions_are_written_onto_the_original_message(self) -> None:
        set_fu = await self._merge_with_follow_ups(["do the next thing"])

        set_fu.assert_awaited_once()
        assert set_fu.await_args.args == ("conv-1",)
        assert set_fu.await_args.kwargs["message_id"] == "orig-msg-1"
        assert set_fu.await_args.kwargs["user_id"] == "user-1"
        assert set_fu.await_args.kwargs["actions"] == ["do the next thing"]

    async def test_no_follow_ups_means_no_write(self) -> None:
        """An unconditional write would blank the follow-ups the original turn
        already had."""
        set_fu = await self._merge_with_follow_ups([])

        set_fu.assert_not_awaited()

    async def test_no_new_cards_skips_the_write_and_keeps_the_originals(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]

        merged = await self._merge(existing=existing, new_cards=None)

        assert [e["tool_name"] for e in merged] == ["old_tool"]

    async def test_every_write_is_scoped_to_this_conversation_message_and_user(self) -> None:
        """These are targeted in-place Mongo updates. An unscoped or wrongly
        scoped one edits somebody else's message — the filter is the only thing
        standing between a merge and another user's conversation."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = []
        calls: dict = {}

        await self._merge(
            existing=existing, new_cards=[{"tool_name": "new_tool", "data": {}}], calls=calls
        )

        read = calls["get_message"].await_args
        assert read.args == ("conv-1", "orig-msg-1")
        assert read.kwargs["user_id"] == "user-1"

        for name in ("set_response", "set_tool_data"):
            write = calls[name].await_args
            assert write.args == ("conv-1",), f"{name} was not scoped to the conversation"
            assert write.kwargs["message_id"] == "orig-msg-1", f"{name} targeted another message"
            assert write.kwargs["user_id"] == "user-1", f"{name} was not scoped to the owner"


class TestApprovalOutcomesNoteContent:
    """The note is the prompt the narrator is grounded on, so its content is a
    contract, not cosmetics: a dropped or mislabelled line is the agent telling
    the user an action is still pending after they denied it."""

    async def _note(self, cards, records):
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        message.tool_data = cards
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
            ) as get_msg,
            patch.object(rd, "get_approval", new=AsyncMock(side_effect=records.get)),
        ):
            note = await rd._approval_outcomes_note(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1")
            )
        return note, get_msg

    async def test_the_lookup_is_scoped_to_the_runs_own_message_and_owner(self) -> None:
        _note, get_msg = await self._note([], {})

        assert get_msg.await_args.args == ("conv-1", "orig-msg-1")
        assert get_msg.await_args.kwargs["user_id"] == "user-1"

    async def test_an_ordinary_card_does_not_stop_the_scan(self) -> None:
        """Cards arrive in stream order, so a plain tool card routinely sits
        before an approval. Stopping at the first non-approval loses it."""
        cards = [{"tool_name": "web_search_tool", "data": {}}, _approval_card("a1", "pending")]
        records = {"a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL")}

        note, _ = await self._note(cards, records)

        assert "SEND_GMAIL" in note

    async def test_every_decided_approval_gets_its_own_line_in_card_order(self) -> None:
        cards = [_approval_card("a1", "pending"), _approval_card("a2", "pending")]
        records = {
            "a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL"),
            "a2": _record("a2", HILApprovalStatus.DENIED, tool_name="SEND_SLACK"),
        }

        note, _ = await self._note(cards, records)

        lines = [line for line in note.splitlines() if line.startswith("- ")]
        assert lines == [
            "- SEND_GMAIL: approved by the user; the action ran",
            "- SEND_SLACK: denied by the user; the action did NOT run",
        ]

    async def test_an_undecided_approval_is_dropped_from_a_mixed_batch(self) -> None:
        cards = [_approval_card("a1", "pending"), _approval_card("a2", "pending")]
        records = {
            "a1": _record("a1", HILApprovalStatus.PENDING, tool_name="SEND_GMAIL"),
            "a2": _record("a2", HILApprovalStatus.DENIED, tool_name="SEND_SLACK"),
        }

        note, _ = await self._note(cards, records)

        assert "SEND_GMAIL" not in note
        assert "SEND_SLACK" in note

    async def test_the_note_leads_with_the_override_instruction(self) -> None:
        """The lines alone are ambiguous — the narrator has the gate-time
        'waiting for approval' text in front of it too. The header is what tells
        it which one wins, so it is part of the contract, not decoration."""
        cards = [_approval_card("a1", "pending")]
        records = {"a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL")}

        note, _ = await self._note(cards, records)

        assert note.startswith("\n\n[APPROVAL OUTCOMES]")
        assert "overrides anything above" in note
        assert "never say it is pending and never re-offer approve/decline" in note

    async def test_the_whole_header_survives_verbatim(self) -> None:
        """Every clause here does a job: it declares the outcomes final, tells
        the model they beat the gate-time text, and forbids re-offering the
        decision. A reworded half is a narrator that starts hedging again."""
        cards = [_approval_card("a1", "pending")]
        records = {"a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL")}

        note, _ = await self._note(cards, records)

        assert note == (
            "\n\n[APPROVAL OUTCOMES] Final, decided by the user; this overrides anything above "
            "that says an action is waiting for approval. Report each action by its outcome; "
            "never say it is pending and never re-offer approve/decline.\n"
            "- SEND_GMAIL: approved by the user; the action ran"
        )


class TestMergeToolDataBookkeeping:
    """The upsert index has to keep pointing at the right slot as the list
    grows, or an approval frame overwrites an unrelated card."""

    def test_an_approval_first_seen_in_the_new_batch_indexes_its_own_slot(self) -> None:
        existing = [{"tool_name": "old_tool", "data": {"keep": "me"}}]

        merged = rd._merge_tool_data(
            existing, [_approval_card("a1", "pending"), _approval_card("a1", "approved")]
        )

        # The replay must land on the approval it appended, not on index 0.
        assert merged[0] == {"tool_name": "old_tool", "data": {"keep": "me"}}
        assert len(merged) == 2
        assert merged[1]["data"]["status"] == "approved"

    def test_skipping_a_pending_replay_does_not_abandon_the_rest_of_the_batch(self) -> None:
        """The replayed frame is rarely last — dropping out of the loop at it
        loses every card the resumed run produced afterwards."""
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved")],
            [_approval_card("a1", "pending"), {"tool_name": "later_tool", "data": {}}],
        )

        assert [e.get("tool_name") for e in merged] == [
            APPROVAL_REQUEST_TOOL_NAME,
            "later_tool",
        ]
        assert merged[0]["data"]["status"] == "approved"


class TestReconcileLooksUpTheRightRecord:
    async def test_the_lookup_uses_the_cards_own_approval_id(self) -> None:
        """Reading a different approval's record stamps someone else's decision
        onto this card."""
        with patch.object(rd, "get_approval", new=AsyncMock(return_value=None)) as get_approval:
            await rd._reconcile_approval_statuses([_approval_card("a-42", "pending")])

        get_approval.assert_awaited_once_with("a-42")


class TestMergeResumedResultFailsClosed:
    async def test_a_run_without_a_user_id_scopes_to_empty_not_none(self) -> None:
        """``user_id=None`` in a Mongo filter matches documents with no owner
        rather than nothing — the scoping has to fail closed."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        bot_message = MessageModel(type="bot", response="new", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        run = ExecutorRun(
            stream_id="queued_s1",
            conversation_id="conv-1",
            user={},
            kind=RunKind.QUEUED,
            task_id="task-1",
            user_message_id=None,
            bot_message_id="orig-msg-1",
        )
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ) as get_msg,
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            await rd._merge_resumed_result(run, bot_message, None)

        assert get_msg.await_args.kwargs["user_id"] == ""


class TestDeliveredMessageIdentity:
    """Which id the delivered message carries decides whether the frontend
    reconciles onto the placeholder it already rendered or strands it."""

    async def _deliver_run(self, run: ExecutorRun, follow_ups: list[str] | None = None):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd,
                "generate_follow_up_actions",
                new_callable=AsyncMock,
                return_value=follow_ups or [],
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd, "_lookup_user_message_content", new_callable=AsyncMock, return_value="asked"
            ),
        ):
            await rd.deliver_result(run, "raw", "final")
        return ws.await_args.args[1]["message"]

    async def test_a_queued_run_is_keyed_on_its_task_id(self) -> None:
        message = await self._deliver_run(_run(RunKind.QUEUED, task_id="task-7"))

        assert message["message_id"] == "task-7"
        assert message["task_id"] == "task-7"

    async def test_a_live_run_mints_a_fresh_id_and_advertises_no_task(self) -> None:
        """A live run never had a task_id-keyed placeholder, so emitting the
        task_id would point the client's replace at a key that never existed."""
        message = await self._deliver_run(_run(RunKind.LIVE, task_id="task-7"))

        # A real UUID, not just "not the task id": every live run falling back
        # to one shared constant would collide every message in the thread.
        UUID(message["message_id"])
        assert "task_id" not in message

    async def test_a_queued_run_quotes_the_message_it_answers(self) -> None:
        run = ExecutorRun(
            stream_id="",
            conversation_id="conv-1",
            user={"user_id": "user-1"},
            kind=RunKind.QUEUED,
            task_id="task-7",
            user_message_id="user-msg-1",
        )

        message = await self._deliver_run(run)

        assert message["replyToMessage"]["id"] == "user-msg-1"

    async def test_a_hil_resume_never_quotes(self) -> None:
        """It merges onto the very message that already sits under the user's
        turn, so a quote would have the turn quoting itself."""
        run = ExecutorRun(
            stream_id="",
            conversation_id="conv-1",
            user={"user_id": "user-1"},
            kind=RunKind.QUEUED,
            task_id="task-7",
            user_message_id="user-msg-1",
            bot_message_id="orig-msg-1",
        )

        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd.conversation_repository,
                "get_message",
                new=AsyncMock(
                    return_value=MessageModel(type="bot", response="old", date="2026-01-01")
                ),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            await rd.deliver_result(run, "raw", "final")

        assert "replyToMessage" not in ws.await_args.args[1]["message"]


class TestDeletedConversationDuringDelivery:
    async def _deliver_with_save_raising(self, exc: Exception):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock, side_effect=exc),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            result = await rd.deliver_result(_run(), "raw", "final")
        return result, ws

    async def test_a_conversation_deleted_mid_run_ends_delivery_quietly(self) -> None:
        """The user deleted the conversation while the executor worked. There is
        nowhere to deliver to, and nothing to push."""
        result, ws = await self._deliver_with_save_raising(HTTPException(status_code=404))

        assert result == (None, None)
        ws.assert_not_awaited()

    async def test_any_other_save_failure_also_stops_delivery(self) -> None:
        """Pushing a message that was never stored leaves the client showing a
        turn that vanishes on reload."""
        result, ws = await self._deliver_with_save_raising(HTTPException(status_code=500))

        assert result == (None, None)
        ws.assert_not_awaited()


class TestMergedCardsAreActuallyWritten:
    async def test_the_merged_list_is_what_reaches_mongo(self) -> None:
        """Returning the merged cards while storing something else is the worst
        shape of this bug: the live push shows them, the reload does not."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]
        bot_message = MessageModel(type="bot", response="new", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=True),
            ) as set_td,
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            merged = await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"),
                bot_message,
                [{"tool_name": "new_tool", "data": {}}],
            )

        assert set_td.await_args.kwargs["entries"] == merged
        assert [e["tool_name"] for e in set_td.await_args.kwargs["entries"]] == [
            "old_tool",
            "new_tool",
        ]

    async def test_the_outcomes_lookup_also_fails_closed_without_a_user_id(self) -> None:
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        run = ExecutorRun(
            stream_id="",
            conversation_id="conv-1",
            user={},
            kind=RunKind.QUEUED,
            task_id="task-1",
            user_message_id=None,
            bot_message_id="orig-msg-1",
        )
        with patch.object(
            rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
        ) as get_msg:
            await rd._approval_outcomes_note(run)

        assert get_msg.await_args.kwargs["user_id"] == ""


class TestDeferredFollowUpPush:
    """Follow-ups are generated AFTER the answer ships, so the spinner clears
    first, and arrive as a second push on the same message id."""

    async def _push(self, *, generated, persisted=True):
        bot_message = MessageModel(type="bot", response="answered", date="2026-01-01")
        bot_message.message_id = "msg-1"
        with (
            patch.object(rd, "_build_follow_up_actions", new=AsyncMock(return_value=generated)),
            patch.object(rd, "_persist_follow_up_actions", new=AsyncMock(return_value=persisted)),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            await rd._generate_and_push_follow_ups(
                run=_run(RunKind.QUEUED, task_id="task-7"),
                bot_message=bot_message,
                result_type="final",
                tool_data=None,
                show_reply_quote=False,
                user_msg_content="asked",
            )
        return ws

    async def test_suggestions_reach_the_client_on_the_same_message(self) -> None:
        ws = await self._push(generated=["ask about X", "try Y"])

        event = ws.await_args.args[1]
        assert event["message"]["message_id"] == "msg-1"
        assert event["message"]["follow_up_actions"] == ["ask about X", "try Y"]

    async def test_nothing_generated_means_no_second_push(self) -> None:
        ws = await self._push(generated=[])

        ws.assert_not_awaited()

    async def test_suggestions_that_failed_to_persist_are_never_shown(self) -> None:
        """Broadcasting unstored suggestions puts them on screen only for them
        to vanish on reload."""
        ws = await self._push(generated=["ask about X"], persisted=False)

        ws.assert_not_awaited()


def _logged(mock, level: str) -> tuple[str, dict]:
    """(message, kwargs) of the last call at ``level``, message asserted real.

    warning/error/critical/exception put BOTH halves on the wide event —
    wide_events._append stores ``{"msg": message, **kwargs}`` — so a blanked or
    dropped message is a real regression in errors[]/warnings[], not prose. The
    wording is deliberately not pinned; that it exists at all is.
    """
    call = getattr(mock, level).call_args
    assert call is not None, f"nothing was logged at {level}"
    assert call.args and isinstance(call.args[0], str) and call.args[0].strip(), (
        f"{level} was emitted with no message — errors[] would carry msg=None"
    )
    return call.args[0], call.kwargs


class TestFailurePathsAreDiagnosable:
    """Every branch here drops a user's result on the floor. The structured
    fields on the log line are the only way to find out which conversation and
    which message it happened to — a blanked id turns an incident into a search
    of the whole collection. Asserting them is a structural assert, the kind
    tests/CLAUDE.md rule 7 asks for; the prose message is deliberately not
    asserted.
    """

    async def _merge_with_log(self, *, existing, set_response=True, set_tool_data=True):
        bot_message = MessageModel(type="bot", response="new", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=set_response),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=set_tool_data),
            ),
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
            patch.object(rd, "log") as log,
        ):
            await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"),
                bot_message,
                [{"tool_name": "new_tool", "data": {}}],
            )
        return log

    async def test_a_missing_original_message_names_what_was_looked_for(self) -> None:
        log = await self._merge_with_log(existing=None)

        _msg, kwargs = _logged(log, "error")
        assert kwargs == {"conversation_id": "conv-1", "message_id": "orig-msg-1"}

    async def test_a_response_write_that_matched_nothing_names_the_message(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")

        log = await self._merge_with_log(existing=existing, set_response=False)

        _msg, kwargs = _logged(log, "error")
        assert kwargs == {"conversation_id": "conv-1", "message_id": "orig-msg-1"}

    async def test_a_dropped_card_write_names_the_message(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")

        log = await self._merge_with_log(existing=existing, set_tool_data=False)

        msg, kwargs = _logged(log, "error")
        assert kwargs == {"conversation_id": "conv-1", "message_id": "orig-msg-1"}
        # The two adjacent literals must still join into one sentence.
        assert msg.endswith("dropping cards")

    async def test_a_failed_outcomes_lookup_reports_the_cause(self) -> None:
        with (
            patch.object(
                rd.conversation_repository,
                "get_message",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch.object(rd, "log") as log,
        ):
            await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))

        _msg, kwargs = _logged(log, "warning")
        assert kwargs == {"error": "mongo down"}


class TestDeletedConversationIsNotAnError:
    """#906 (d70e3ca7b) split these arms on purpose: a conversation the user
    deleted mid-run is expected, and logging it at error put it in errors[] on
    the wide event and on the dashboards that filter by level. Both arms return
    the same thing, so the LEVEL is the entire observable difference — without
    this test nothing stops the split being quietly undone.
    """

    async def _deliver_with_save_raising(self, exc: Exception):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock, side_effect=exc),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
            patch.object(rd, "log") as log,
        ):
            result = await rd.deliver_result(_run(), "raw", "final")
        return result, log

    async def test_a_deleted_conversation_is_reported_at_info_with_its_id(self) -> None:
        result, log = await self._deliver_with_save_raising(HTTPException(status_code=404))

        assert result == (None, None)
        assert log.info.call_args.kwargs == {"conversation_id": "conv-1"}
        assert not log.error.called, "an expected 404 was escalated into errors[]"

    async def test_any_other_http_failure_is_reported_at_error_with_the_cause(self) -> None:
        result, log = await self._deliver_with_save_raising(
            HTTPException(status_code=500, detail="mongo exploded")
        )

        assert result == (None, None)
        _msg, kwargs = _logged(log, "error")
        assert kwargs["error"] == "500: mongo exploded"
        assert not log.info.called, "a real failure was downgraded to info"

    async def test_a_non_http_failure_also_carries_its_cause(self) -> None:
        """The second except arm. Without a case that never becomes an
        HTTPException, its own report goes untested — and a save that dies on a
        driver error is exactly the one you need the cause for."""
        result, log = await self._deliver_with_save_raising(RuntimeError("connection reset"))

        assert result == (None, None)
        _msg, kwargs = _logged(log, "error")
        assert kwargs["error"] == "connection reset"
        assert not log.info.called
