"""Unit tests for what a background executor run leaves behind: its cards, and its lifecycle.

run_cards owns the cards a self-owning run streamed: a cancelled run's are persisted as they
rendered, and a run resumed after an approval merges its cards onto the live message without
duplicating it, dropping cards the user saw, or resurrecting an approval they decided.
"""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import executor_runner as er, run_cards as rd
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    TodoRun,
)
from app.constants.chat import CONVERSATION_MAX_MESSAGES
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.todos import TODO_CONVERSATION_MAX_MESSAGES
from app.models.chat_models import MessageModel, ToolDataEntry
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.outbox.router import InApp
from shared.py.analytics import UserId
from shared.py.analytics.catalog.agents import AgentRunCompleted, AgentRunFailed, AgentRunStarted
from shared.py.wide_events import log

# A run says it lives in Redis while it runs: give it a per-test Redis, never the ambient one.
pytestmark = pytest.mark.usefixtures("fake_redis")

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
NO_CHAT_APP = InApp(reason="no_chat_app")


def _approval_card(approval_id: str, status: str, **extra: str) -> ToolDataEntry:
    return {
        "tool_name": APPROVAL_REQUEST_TOOL_NAME,
        "data": {"approval_id": approval_id, "status": status, **extra},
    }


def _record(
    approval_id: str, status: HILApprovalStatus, tool_name: str = "SEND_GMAIL"
) -> HILApprovalRecord:
    return HILApprovalRecord(
        approval_id=approval_id,
        user_id=USER_ID,
        conversation_id="conv-1",
        stream_id="stream-1",
        tool_name=tool_name,
        status=status,
        decided_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )


def _run(
    kind: RunKind = RunKind.LIVE,
    *,
    stream_id: str = "",
    task_id: str | None = None,
    bot_message_id: str | None = None,
    workflow: bool = False,
) -> ExecutorRun:
    """Build a run context for delivery tests (defaults: live, non-workflow)."""
    run = ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user=AuthenticatedUser(user_id=USER_ID),
        kind=kind,
        task_id=task_id,
        user_message_id=None,
        bot_message_id=bot_message_id,
        workflow_id="wf-1" if workflow else None,
        workflow_title="Morning digest" if workflow else "",
        active_todo_id="todo-9" if workflow else None,
    )
    return run


#: One executor tool card, in the shape ``_finalize_executor_run`` snapshots off
#: the session and hands to delivery.
CARDS: list[ToolDataEntry] = [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}]


class TestPersistCancelledRun:
    """Cancelled self-owning runs: cards-only persist, no re-push.

    These pin the "stop the stream → cards survive" fix. The cards were already
    streamed live, so the persisted copy must reconcile with the frontend
    placeholder by message_id == task_id and must NOT go out over the
    WebSocket again.
    """

    async def test_persists_cards_only_message_keyed_by_task_id(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "publish_conversation_message", new_callable=AsyncMock) as ws,
        ):
            await rd.persist_cancelled_run(run, CARDS)

        save.assert_awaited_once()
        saved = save.await_args.args[0].messages[0]
        assert saved.message_id == "task-9"  # reconciles with the placeholder by id
        assert saved.response == ""  # cards-only: the result is told through the outbox
        assert saved.tool_data and saved.tool_data[0]["tool_name"] == "tool_calls_data"
        ws.assert_not_awaited()  # no re-broadcast of already-streamed data

    @pytest.mark.parametrize(
        ("todo_run", "cap"),
        [
            (None, CONVERSATION_MAX_MESSAGES),
            (
                TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO, runs_once=True),
                TODO_CONVERSATION_MAX_MESSAGES,
            ),
        ],
        ids=["chat", "todo-chat"],
    )
    async def test_a_stopped_runs_cards_keep_the_conversations_cap(
        self, todo_run: TodoRun | None, cap: int
    ) -> None:
        """Regression: an explicit None for a plain chat switched off the cap every conversation has."""
        run = replace(
            _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9"), todo_run=todo_run
        )

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run, CARDS)

        assert save.await_args.kwargs["max_messages"] == cap

    async def test_a_bot_reply_keeps_the_conversations_cap(self) -> None:
        bot_message = MessageModel(type="bot", response="hi")
        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd._save_message("conv-1", AuthenticatedUser(user_id=USER_ID), bot_message)

        assert save.await_args.kwargs["max_messages"] == CONVERSATION_MAX_MESSAGES

    async def test_no_cards_writes_nothing(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run, [])

        save.assert_not_awaited()

    async def test_save_failure_is_swallowed(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(
            rd, "update_messages", new_callable=AsyncMock, side_effect=RuntimeError("mongo down")
        ):
            await rd.persist_cancelled_run(run, CARDS)  # must not raise


# ---------------------------------------------------------------------------
# run_executor_background lifecycle analytics
# ---------------------------------------------------------------------------


class TestRunLifecycleAnalytics:
    """AGENT_RUN_STARTED/COMPLETED/FAILED around the executor run boundary."""

    async def _run_lifecycle(
        self,
        result_text: str,
        result_type: str,
        *,
        task_id: str | None = "task-1",
        user_id: str | None = USER_ID,
        error_type: str | None = None,
    ):
        from app.agents.core.background.executor_runner import _ExecutorResult

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            # user_id=None models a run whose user dict carries no id at all.
            user=AuthenticatedUser(user_id=user_id or ""),
            kind=RunKind.LIVE,
            task_id=task_id,
            user_message_id=None,
        )
        with (
            patch("app.services.analytics_service.capture") as mock_capture,
            patch.object(
                er,
                "_execute_executor",
                new_callable=AsyncMock,
                return_value=_ExecutorResult(result_text, result_type, error_type=error_type),
            ),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(run, "do things", {"user_id": user_id})
        return mock_capture

    async def test_started_and_completed_on_final(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final")

        events = [type(c.args[1]) for c in mock_capture.call_args_list]
        assert events == [AgentRunStarted, AgentRunCompleted]
        assert mock_capture.call_args_list[0].args == (
            UserId(USER_ID),
            AgentRunStarted(
                agent="executor", mode="background", conversation_id="conv-1", task_id="task-1"
            ),
        )
        # The TERMINAL event needs the same scrutiny as the opening one: it was
        # asserted only by name, so its user id and payload could both go null
        # without a test noticing.
        assert mock_capture.call_args_list[1].args[0] == UserId(USER_ID)
        terminal = mock_capture.call_args_list[1].args[1]
        assert terminal.agent == "executor"
        assert terminal.mode == "background"
        assert terminal.conversation_id == "conv-1"
        assert terminal.task_id == "task-1"
        assert terminal.queued is False
        assert terminal.executor_active_ms is not None
        assert terminal.executor_active_ms >= 0.0
        # A resumed segment re-enters with the same task, so the terminal is keyed on it.
        assert mock_capture.call_args_list[0].kwargs["dedupe"] is None
        assert mock_capture.call_args_list[1].kwargs["dedupe"].key == "task-1"

    async def test_a_run_without_a_task_keys_its_terminal_on_the_stream(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final", task_id=None)

        assert mock_capture.call_args_list[1].kwargs["dedupe"].key == "stream-1"

    async def test_failed_on_error_result(self) -> None:
        mock_capture = await self._run_lifecycle("it broke", "error", error_type="RuntimeError")

        events = [type(c.args[1]) for c in mock_capture.call_args_list]
        assert events == [AgentRunStarted, AgentRunFailed]
        assert mock_capture.call_args_list[1].args[0] == UserId(USER_ID)
        terminal = mock_capture.call_args_list[1].args[1]
        assert terminal.agent == "executor"
        assert terminal.task_id == "task-1"
        assert terminal.queued is False
        assert terminal.executor_active_ms is not None
        assert terminal.executor_active_ms >= 0.0
        assert terminal.reason == "RuntimeError"

    async def test_a_run_with_no_user_id_captures_nothing(self) -> None:
        """run.user with no id must produce no events at all — the guard relies on a "" default staying falsy."""
        mock_capture = await self._run_lifecycle("done", "final", user_id=None)

        mock_capture.assert_not_called()

    async def test_paused_run_has_no_terminal_event(self) -> None:
        """A HIL pause is not a terminal outcome — the resume re-enters and captures its own STARTED."""
        mock_capture = await self._run_lifecycle("", "paused")

        events = [type(c.args[1]) for c in mock_capture.call_args_list]
        assert events == [AgentRunStarted]

    async def test_no_user_id_skips_events(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final", user_id="")
        mock_capture.assert_not_called()


class TestApprovalId:
    """The key every merge decision is made on.

    Reading it off the wrong kind of card silently turns an ordinary tool
    card into an approval and lets the upsert overwrite it.
    """

    def test_an_approval_card_yields_its_id(self) -> None:
        assert rd._approval_id(_approval_card("a1", "pending")) == "a1"

    def test_an_ordinary_tool_card_is_not_an_approval(self) -> None:
        entry: ToolDataEntry = {"tool_name": "web_search_tool", "data": {"approval_id": "a1"}}
        assert rd._approval_id(entry) is None

    def test_a_non_dict_payload_is_not_an_approval(self) -> None:
        assert rd._approval_id({"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": "a1"}) is None

    def test_a_non_string_id_is_rejected(self) -> None:
        entry: ToolDataEntry = {
            "tool_name": APPROVAL_REQUEST_TOOL_NAME,
            "data": {"approval_id": 17},
        }
        assert rd._approval_id(entry) is None

    def test_a_card_with_no_id_at_all_is_rejected(self) -> None:
        entry: ToolDataEntry = {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": {}}
        assert rd._approval_id(entry) is None


class TestMergeToolData:
    """The resumed stream replays the gate-time PENDING frame after the decision already landed.

    Appending blindly resurrects a decided card.
    """

    def test_ordinary_cards_append_after_the_existing_ones(self) -> None:
        existing: list[ToolDataEntry] = [{"tool_name": "old_tool", "data": {}}]
        new: list[ToolDataEntry] = [{"tool_name": "new_tool", "data": {}}]

        merged = rd._merge_tool_data(existing, new)

        assert [e["tool_name"] for e in merged] == ["old_tool", "new_tool"]

    def test_an_unseen_approval_appends(self) -> None:
        merged = rd._merge_tool_data([], [_approval_card("a1", "pending")])

        assert merged == [_approval_card("a1", "pending")]

    def test_a_replayed_pending_never_downgrades_a_settled_decision(self) -> None:
        """Regression: the user decided, then a replay put the pending card back and re-offered approve/decline."""
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
        """The index has to learn about ids appended during the same pass, or a same-batch card duplicates itself."""
        merged = rd._merge_tool_data(
            [], [_approval_card("a1", "pending"), _approval_card("a1", "approved")]
        )

        assert len(merged) == 1
        assert merged[0]["data"]["status"] == "approved"

    def test_the_existing_list_is_not_mutated(self) -> None:
        existing: list[ToolDataEntry] = [{"tool_name": "old_tool", "data": {}}]

        rd._merge_tool_data(existing, [{"tool_name": "new_tool", "data": {}}])

        assert [e["tool_name"] for e in existing] == ["old_tool"]


class TestReconcileApprovalStatuses:
    """A decision's resolved frame may never reach the stream this delivery drains — the record is the source of truth."""

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
        entry: ToolDataEntry = {"tool_name": "web_search_tool", "data": {"status": "pending"}}
        with patch.object(rd, "get_approval", new=AsyncMock()) as get:
            out = await rd._reconcile_approval_statuses([entry])

        assert out == [entry]
        assert get.await_count == 0, "an ordinary card triggered an approvals lookup"

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


class TestMergeToolDataBookkeeping:
    """The upsert index has to keep pointing at the right slot as the list grows, or it overwrites an unrelated card."""

    def test_an_approval_first_seen_in_the_new_batch_indexes_its_own_slot(self) -> None:
        existing: list[ToolDataEntry] = [{"tool_name": "old_tool", "data": {"keep": "me"}}]

        merged = rd._merge_tool_data(
            existing, [_approval_card("a1", "pending"), _approval_card("a1", "approved")]
        )

        # The replay must land on the approval it appended, not on index 0.
        assert merged[0] == {"tool_name": "old_tool", "data": {"keep": "me"}}
        assert len(merged) == 2
        assert merged[1]["data"]["status"] == "approved"

    def test_skipping_a_pending_replay_does_not_abandon_the_rest_of_the_batch(self) -> None:
        """The replayed frame is rarely last — dropping out of the loop at it loses every card produced afterwards."""
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
        """Reading a different approval's record stamps someone else's decision onto this card."""
        with patch.object(rd, "get_approval", new=AsyncMock(return_value=None)) as get_approval:
            await rd._reconcile_approval_statuses([_approval_card("a-42", "pending")])

        get_approval.assert_awaited_once_with("a-42")


class TestRunBoundaryCarriesTheOriginatingSurface:
    """The executor run stamps the turn's surface on its own wide event.

    An auxiliary call made INSIDE this run (a follow-up, a memory write) is
    handed a bare config with no conversation_source, so without this stamp
    the ledger records a user's web turn as system — and executor turns are
    the expensive ones, so the under-count lands exactly where COGS-by-channel
    is read.
    """

    @staticmethod
    async def _boundary_fields(configurable: dict[str, object]) -> dict[str, object]:
        from app.agents.core.background.executor_runner import _ExecutorResult

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id=USER_ID),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
        )
        with (
            patch("app.services.analytics_service.capture"),
            patch.object(
                er,
                "_execute_executor",
                new_callable=AsyncMock,
                return_value=_ExecutorResult("done", "final"),
            ),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
            patch.object(er, "wide_task") as boundary,
        ):
            await er.run_executor_background(run, "do things", configurable)
        return dict(boundary.call_args.kwargs)

    async def test_the_turns_surface_is_carried_onto_the_run(self) -> None:
        fields = await self._boundary_fields({"user_id": "u1", "conversation_source": "web"})

        assert fields["conversation_source"] == "web"

    async def test_a_run_started_from_no_surface_carries_none(self) -> None:
        """A workflow-triggered executor run has no originating surface; None is the honest value, the ledger classifies it."""
        fields = await self._boundary_fields({"user_id": "u1"})

        assert fields["conversation_source"] is None


@pytest.mark.regression
class TestRunBoundaryCarriesWorkflowExecution:
    """run_executor_background opens its own wide-event boundary; the workflow task stamped execution_id on ITS boundary.

    Unless the run carries it across, model calls land in the ledger with
    a workflow but no execution — $8 of a $10 workflow day was attributed
    to no run at all.
    """

    async def test_executor_calls_see_the_workflow_execution(self) -> None:
        from app.agents.core.background.executor_runner import _ExecutorResult

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id=USER_ID),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
            workflow_id="wf-9",
            workflow_execution_id="exec-42",
        )
        seen: dict[str, object] = {}

        async def capture(*_args: object, **_kwargs: object) -> _ExecutorResult:
            seen["workflow"] = log.get().get("workflow")
            return _ExecutorResult("done", "final")

        with (
            patch("app.services.analytics_service.capture"),
            patch.object(er, "_execute_executor", side_effect=capture),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(
                run, "do things", {"user_id": USER_ID, "workflow_id": "wf-9"}
            )

        assert seen["workflow"] == {"id": "wf-9", "execution_id": "exec-42"}

    @pytest.mark.parametrize(
        ("workflow_id", "execution_id"),
        [("wf-9", None), (None, "exec-42"), (None, None)],
        ids=["workflow-without-execution", "execution-without-workflow", "plain-run"],
    )
    async def test_a_run_missing_either_id_stamps_no_workflow(
        self, workflow_id: str | None, execution_id: str | None
    ) -> None:
        """Half an identity is worse than none: a workflow id alone attributes calls to the workflow's *unknown* execution."""
        from app.agents.core.background.executor_runner import _ExecutorResult

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id=USER_ID),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
            workflow_id=workflow_id,
            workflow_execution_id=execution_id,
        )
        seen: dict[str, object] = {}

        async def capture(*_args: object, **_kwargs: object) -> _ExecutorResult:
            seen["workflow"] = log.get().get("workflow")
            return _ExecutorResult("done", "final")

        with (
            patch("app.services.analytics_service.capture"),
            patch.object(er, "_execute_executor", side_effect=capture),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(run, "do things", {"user_id": USER_ID})

        assert seen["workflow"] is None
