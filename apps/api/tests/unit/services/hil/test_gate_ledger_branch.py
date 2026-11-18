"""Ledger branch of the approval gate (flag on: register, never interrupt)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
import pytest
import time_machine

from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.hil import AUTO_ASK_NOTE, HIL_APPROVAL_TIMEOUT_SECONDS, HIL_STATUS_KWARG
from app.constants.log_tags import LogTag
from app.models.conversation_log_models import ApprovalRequested
from app.models.hil_models import (
    ApprovalDetail,
    ApprovalLedgerDocument,
    ApprovalProposal,
)
from app.services.hil import gate
from app.services.hil.describe import describe_call
from app.services.hil.fingerprint import approval_fingerprint
from app.services.hil.intent import AutoContext, IntentDecision, JudgedCall, summarize_history
from app.services.hil.jev_judge import JevIntentJudge
from app.services.hil.prompts import GATE_ERROR_TEMPLATE
from app.services.hil.utils import GatedApproval, GatedCall
from app.services.hil.when import UserClock
from app.utils.general_utils import ELLIPSIS
from app.utils.timezone import Timezone
from shared.py.approvals import ApprovalOutcome

from .conftest import (
    CONVERSATION_ID,
    GATED_ACCOUNT,
    GATED_ACCOUNT_SUMMARY,
    GATED_ARGS,
    GATED_SUMMARY,
    GATED_TOOL,
    STREAM_ID,
    USER_ID,
    GateSeams,
    account_gated_request,
    gated_request,
    make_request,
)

MODULE = "app.services.hil.gate"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


def _ledger(
    live: Any = None, denied: Any = None, registered_id: str = "ap_abc1234567"
) -> MagicMock:
    ledger = MagicMock()
    ledger.find_live = AsyncMock(return_value=live)
    ledger.find_latest_denied = AsyncMock(return_value=denied)
    ledger.find_amended = AsyncMock(return_value=None)
    ledger.register = AsyncMock(return_value=registered_id)
    return ledger


def _gated_request(**overrides: Any) -> ToolCallRequest:
    return make_request(
        name="GMAIL_SEND_EMAIL",
        args={"to": "b@x"},
        configurable={
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
            "user_messages": ["send it"],
            **overrides,
        },
    )


@pytest.mark.unit
class TestLedgerBranch:
    async def test_registers_pending_and_never_interrupts(self) -> None:
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)
        assert "needs the user's explicit approval" in str(result.content)
        assert 'execute(tool_name="revoke"' in str(result.content)
        assert "approve ticket" in str(result.content)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"

    async def test_the_approval_is_logged_on_the_work_its_run_belongs_to(
        self, logged_work: AsyncMock
    ) -> None:
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            await gate.decide_tool_call(_gated_request())

        assert ledger.register.await_args.args[0].task_id == "t1"
        (_, _, request), _ = logged_work.await_args
        assert (request.task_id, request.approval_id) == ("t1", "ap_abc1234567")

    async def test_a_request_the_log_refuses_leaves_no_ledger_row(
        self, logged_work: AsyncMock
    ) -> None:
        """Regression for review finding 8: the row was registered first, so a failed log append left a live row with no card."""
        ledger = _ledger()
        logged_work.side_effect = ConnectionError("mongo blip")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        assert result is not None and "NOT performed" in str(result.content)

    async def test_a_request_that_loses_the_register_race_withdraws_and_points_at_the_winner(
        self,
    ) -> None:
        winner = ApprovalLedgerDocument(
            approval_id="ap_winner00001",
            conversation_id=CONVERSATION_ID,
            user_id=USER_ID,
            fingerprint="fp",
            tool_name="GMAIL_SEND_EMAIL",
            summary="Send it",
            owner_agent="executor",
        )
        ledger = _ledger(registered_id="ap_winner00001")
        ledger.get_by_approval_id = AsyncMock(
            side_effect=lambda approval_id: winner if approval_id == "ap_winner00001" else None
        )
        withdrawn = AsyncMock()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()) as announced,
            patch(f"{MODULE}.record_approval_decided", new=withdrawn),
        ):
            result = await gate.decide_tool_call(_gated_request())

        withdrawn.assert_awaited_once_with(
            CONVERSATION_ID, USER_ID, "ap_abc1234567", ApprovalOutcome.WITHDRAWN, None
        )
        announced.assert_not_awaited()
        assert result is not None and "ap_winner00001" in str(result.content)
        assert "ap_abc1234567" not in str(result.content)

    async def test_a_call_from_no_logged_work_is_refused_and_never_registered(self) -> None:
        ledger = _ledger()
        unlogged = AsyncMock(side_effect=LookupError("run s1 is no logged work"))
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
            patch(f"{MODULE}.work_of_run", new=unlogged),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        assert result is not None and "NOT performed" in str(result.content)

    async def test_background_pending_points_at_its_conversation(self) -> None:
        """A background run has no watcher: the card waits in its conversation, so the guidance must say so instead of "when this run ends"."""
        ledger = _ledger()
        request = _gated_request(execution_mode="background")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            result = await gate.decide_tool_call(request)
        assert result is not None
        assert "this conversation, which shows in their chat list" in str(result.content)
        assert "Approvals tab" not in str(result.content)
        assert "when this run ends" not in str(result.content)

    async def test_background_workflow_run_tags_the_ledger_owner(self) -> None:
        """The resume driver needs to know WHAT parked: a background workflow run stamps its owner on the row; nothing else does."""
        ledger = _ledger()
        request = _gated_request(execution_mode="background", workflow_id="wf-1")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            await gate.decide_tool_call(request)

        assert ledger.register.await_args.args[0].owner_run_type == "workflow"
        assert ledger.register.await_args.args[0].owner_id == "wf-1"

    async def test_background_todo_run_tags_the_ledger_owner(self) -> None:
        ledger = _ledger()
        request = _gated_request(execution_mode="background", active_todo_id="todo-9")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            await gate.decide_tool_call(request)

        assert ledger.register.await_args.args[0].owner_run_type == "todo"
        assert ledger.register.await_args.args[0].owner_id == "todo-9"

    async def test_live_run_with_ids_tags_no_owner(self) -> None:
        """Owner tagging is resume-scoped: a live run resumes through the executor inbox and must never re-enqueue, even carrying the keys."""
        ledger = _ledger()
        request = _gated_request(workflow_id="wf-1", active_todo_id="todo-9")
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            await gate.decide_tool_call(request)

        assert ledger.register.await_args.args[0].owner_run_type == ""
        assert ledger.register.await_args.args[0].owner_id == ""

    async def test_live_duplicate_returns_existing_id_without_register(self) -> None:
        live = MagicMock(approval_id="ap_live", summary="Send it")
        live.outcome = None
        live.action = None
        ledger = _ledger(live=live)
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        assert result is not None
        assert "PENDING ap_live" in str(result.content)
        assert "already requested" in str(result.content)

    async def test_live_approved_row_is_not_called_awaiting_decision(self) -> None:
        live = MagicMock(approval_id="ap_live", summary="Send it")
        live.outcome = ApprovalOutcome.APPROVED
        live.action = None
        ledger = _ledger(live=live)
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        assert result is not None
        assert "APPROVED ap_live" in str(result.content)
        assert "awaiting redeem" in str(result.content)

    async def test_same_run_denied_reissue_is_refused(self) -> None:
        denied = MagicMock(proposing_run_id=STREAM_ID, feedback="too broad", decided_at=None)
        ledger = _ledger(denied=denied)
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        assert result is not None
        assert "REFUSED" in str(result.content)
        assert "DO NOT re-request" in str(result.content)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"

    async def test_older_denied_run_registers_with_the_why_attached(self) -> None:
        denied = MagicMock(proposing_run_id="other-stream", feedback="wrong day", decided_at=None)
        ledger = _ledger(denied=denied)
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)
        assert "wrong day" in str(result.content)

    async def test_ledger_failure_fails_closed_without_interrupt(self) -> None:
        ledger = _ledger()
        ledger.find_live = AsyncMock(side_effect=ConnectionError("mongo down"))
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
        ):
            result = await gate.decide_tool_call(_gated_request())
        assert result is not None
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"


@pytest.mark.unit
class TestLedgerAutoParity:
    async def test_auto_aligned_call_runs_without_card_or_row(self) -> None:
        """Auto mode keeps its intent judge on the ledger path: an aligned call clears to run with no card and no ledger row, exactly like the barrier path."""
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(
                f"{MODULE}._judge",
                new=AsyncMock(return_value=IntentDecision(outcome="accept", reason="asked")),
            ),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()) as pub,
        ):
            result = await gate.decide_tool_call(_gated_request())

        assert result is None
        ledger.register.assert_not_awaited()
        pub.assert_not_awaited()

    async def test_auto_misaligned_call_still_registers(self) -> None:
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(
                f"{MODULE}._judge",
                new=AsyncMock(return_value=IntentDecision(outcome="ask", reason="unclear")),
            ),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()),
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)
        assert "auto-approve did not cover" in str(result.content)


class _StrictArgs(BaseModel):
    to: str
    subject: str


def _strict_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda: None,
        name="GMAIL_SEND_EMAIL",
        description="Send.",
        args_schema=_StrictArgs,
    )


@pytest.mark.unit
class TestLedgerBranchValidatesArgs:
    async def test_invalid_args_fail_before_any_card_exists(self) -> None:
        """No card for malformed args: the user must never approve a call the model will have to retry."""
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=_strict_tool())),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()) as pub,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        pub.assert_not_awaited()
        assert result is not None
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"
        assert "subject" in str(result.content)
        assert "no approval was requested" in str(result.content)

    async def test_unresolvable_tool_skips_validation(self) -> None:
        """Resolution failure must not gate: execution validates authoritatively, the gate only pre-filters what it can read."""
        ledger = _ledger()
        with (
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.announce_approval", new=AsyncMock()) as pub,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        pub.assert_awaited_once()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)


def _row(**overrides: Any) -> ApprovalLedgerDocument:
    fields: dict[str, Any] = {
        "approval_id": "ap_old",
        "conversation_id": CONVERSATION_ID,
        "user_id": USER_ID,
        "fingerprint": approval_fingerprint(GATED_TOOL, GATED_ARGS),
        "tool_name": GATED_TOOL,
        "summary": "Send the old one",
    }
    return ApprovalLedgerDocument(**{**fields, **overrides})


def _assert_pending(result: ToolMessage | None) -> None:
    assert result is not None
    assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"


@pytest.mark.unit
class TestLedgerRegistration:
    """A fresh gated call becomes one exact ledger row and one card, and the model is told so."""

    async def test_the_proposal_carries_the_whole_call_and_its_provenance(
        self, gate_seams: GateSeams
    ) -> None:
        result = await gate.decide_tool_call(gated_request(thread_id="gmail_conv-1"))

        fingerprint = approval_fingerprint(GATED_TOOL, GATED_ARGS)
        gate_seams.ledger.find_live.assert_awaited_once_with(fingerprint, CONVERSATION_ID)
        gate_seams.ledger.find_latest_denied.assert_awaited_once_with(fingerprint, CONVERSATION_ID)
        gate_seams.ledger.register.assert_awaited_once_with(
            ApprovalProposal(
                conversation_id=CONVERSATION_ID,
                user_id=USER_ID,
                fingerprint=fingerprint,
                tool_name=GATED_TOOL,
                tool_key=GATED_TOOL,
                args=GATED_ARGS,
                summary=GATED_SUMMARY,
                preview='{"to": "b@x"}',
                owner_agent="gmail_conv-1",
                proposing_run_id=STREAM_ID,
                task_id="t1",
            ),
            "ap_abc1234567",
        )
        gate_seams.announce.assert_awaited_once_with(
            GatedApproval(
                approval_id="ap_abc1234567",
                stream_id=STREAM_ID,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                tool_call=GatedCall(name=GATED_TOOL, id="call-1", args=GATED_ARGS),
                summary=GATED_SUMMARY,
                integration_name="Gmail",
            ),
            background=False,
        )
        _assert_pending(result)
        assert (result.name, result.tool_call_id) == (GATED_TOOL, "call-1")

    @time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False)
    async def test_the_log_records_the_request_with_everything_its_card_shows(
        self, gate_seams: GateSeams
    ) -> None:
        with (
            patch(f"{MODULE}.asks_every_time", new=AsyncMock(return_value=True)) as asks,
            patch(f"{MODULE}.work_of_run", new=AsyncMock(return_value="t1")) as work,
        ):
            result = await gate.decide_tool_call(gated_request())

        work.assert_awaited_once_with(CONVERSATION_ID, USER_ID, STREAM_ID)
        asks.assert_awaited_once_with(GATED_TOOL, GATED_ARGS)
        gate_seams.requested.assert_awaited_once_with(
            CONVERSATION_ID,
            USER_ID,
            ApprovalRequested(
                id="approval:ap_abc1234567",
                task_id="t1",
                approval_id="ap_abc1234567",
                description=describe_call(
                    GATED_TOOL, GATED_ARGS, "Gmail", clock=UserClock.current(Timezone.utc())
                ),
                expires_at=datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
                + timedelta(seconds=HIL_APPROVAL_TIMEOUT_SECONDS),
                tool_call_id="call-1",
                gated_tool_name=GATED_TOOL,
                integration_name="Gmail",
                args_preview=GATED_ARGS,
                always_asks=True,
            ),
        )
        assert result is not None
        assert 'execute(tool_name="revoke", data={"id": "ap_abc1234567"})' in str(result.content)

    async def test_only_the_call_carrying_the_amendment_id_is_the_re_ask(
        self, gate_seams: GateSeams
    ) -> None:
        """Two calls of the amended tool follow a yes with a change; only the one naming it is its redo."""
        todo = "create_todo"
        amended = _row(
            outcome=ApprovalOutcome.APPROVED,
            tool_name=todo,
            approval_id="ap_before",
            args={"title": "Pay rent", "priority": None},
            feedback="yes but make it high priority",
        )

        async def find_amended(
            approval_id: str, conversation_id: str
        ) -> ApprovalLedgerDocument | None:
            linked = (approval_id, conversation_id) == ("ap_before", CONVERSATION_ID)
            return amended if linked else None

        gate_seams.ledger.find_amended.side_effect = find_amended
        redo = {
            "task_description": "Create the todo",
            "tool_name": todo,
            "data": {"title": "Pay rent", "priority": "high"},
            "amends": "ap_before",
        }
        await gate.decide_tool_call(
            gated_request(name=todo, args={"title": "Pay rent", "priority": "low"})
        )
        await gate.decide_tool_call(gated_request(name=EXECUTE_TOOL_NAME, args=redo))

        unrelated, redone = (
            call.args[2].description for call in gate_seams.requested.await_args_list
        )
        assert unrelated.changes == []
        assert redone.changes == [ApprovalDetail(label="Priority", value="high")]
        assert redone.details[0] == ApprovalDetail(label="Priority", value="high")
        gate_seams.ledger.find_amended.assert_awaited_once_with("ap_before", CONVERSATION_ID)

    async def test_a_call_on_a_named_account_is_its_own_approval(
        self, gate_seams: GateSeams
    ) -> None:
        """Approving a send from one mailbox must never clear the same send from another."""
        await gate.decide_tool_call(account_gated_request())

        fingerprint = approval_fingerprint(GATED_TOOL, GATED_ARGS, GATED_ACCOUNT)
        assert fingerprint != approval_fingerprint(GATED_TOOL, GATED_ARGS)
        gate_seams.ledger.find_live.assert_awaited_once_with(fingerprint, CONVERSATION_ID)
        proposal = gate_seams.ledger.register.await_args.args[0]
        assert (proposal.fingerprint, proposal.account, proposal.summary) == (
            fingerprint,
            GATED_ACCOUNT,
            GATED_ACCOUNT_SUMMARY,
        )
        assert gate_seams.announce.await_args.args[0].summary == GATED_ACCOUNT_SUMMARY

    async def test_a_worker_with_no_thread_is_recorded_as_unknown(
        self, gate_seams: GateSeams
    ) -> None:
        await gate.decide_tool_call(gated_request())

        assert gate_seams.ledger.register.await_args.args[0].owner_agent == "unknown"

    async def test_a_background_run_with_no_owner_stamps_none(self, gate_seams: GateSeams) -> None:
        result = await gate.decide_tool_call(gated_request(execution_mode="background"))

        proposal = gate_seams.ledger.register.await_args.args[0]
        assert (proposal.owner_run_type, proposal.owner_id) == ("", "")
        assert gate_seams.announce.await_args.kwargs["background"] is True
        _assert_pending(result)

    async def test_a_long_or_non_json_argument_still_previews(self, gate_seams: GateSeams) -> None:
        args: dict[str, Any] = {"to": "b@x", "at": datetime(2026, 1, 1), "note": "n" * 600}

        await gate.decide_tool_call(gated_request(args=args))

        preview = gate_seams.ledger.register.await_args.args[0].preview
        assert preview.startswith('{"to": "b@x", "at": "2026-01-01 00:00:00", "note": "nnn')
        assert len(preview) == 500 + len(ELLIPSIS)
        assert preview.endswith(ELLIPSIS)

    async def test_an_older_denial_still_leaves_the_call_pending(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.ledger.find_latest_denied.return_value = _row(
            outcome=ApprovalOutcome.DENIED,
            action=None,
            proposing_run_id="other-stream",
            feedback="wrong day",
            decided_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        )

        result = await gate.decide_tool_call(gated_request())

        _assert_pending(result)
        gate_seams.ledger.find_latest_denied.assert_awaited_once()
        gate_seams.ledger.register.assert_awaited_once()

    async def test_a_bare_older_denial_still_leaves_the_call_pending(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.ledger.find_latest_denied.return_value = _row(
            outcome=ApprovalOutcome.DENIED, action=None, proposing_run_id="other-stream"
        )

        result = await gate.decide_tool_call(gated_request())

        _assert_pending(result)
        gate_seams.ledger.find_latest_denied.assert_awaited_once()
        gate_seams.ledger.register.assert_awaited_once()

    async def test_a_registry_failure_is_reported_and_denies(self, gate_seams: GateSeams) -> None:
        gate_seams.ledger.register.side_effect = RuntimeError("mongo down")

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == GATE_ERROR_TEMPLATE.format(tool=GATED_TOOL)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"
        gate_seams.log.error.assert_called_once()
        assert "Ledger gate failed; denying" in gate_seams.log.error.call_args.args[0]
        assert gate_seams.log.error.call_args.kwargs == {
            "name": GATED_TOOL,
            "error": "mongo down",
            "error_type": "RuntimeError",
        }


@pytest.mark.unit
class TestLedgerCollapsesIntoExistingRows:
    async def test_an_approved_twin_points_at_its_redeem(self, gate_seams: GateSeams) -> None:
        gate_seams.ledger.find_live.return_value = _row(
            approval_id="ap_live", outcome=ApprovalOutcome.APPROVED, action=None
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == (
            "APPROVED ap_live: Send the old one already approved, awaiting redeem — not "
            "awaiting the user's decision. Do not re-request it; redeem it or continue "
            "other work."
        )
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"
        gate_seams.ledger.register.assert_not_awaited()

    @pytest.mark.parametrize("background", [False, True], ids=["live", "background"])
    async def test_a_pending_twin_returns_pending_without_registering(
        self, gate_seams: GateSeams, background: bool
    ) -> None:
        gate_seams.ledger.find_live.return_value = _row(approval_id="ap_live")
        extra: dict[str, Any] = {"execution_mode": "background"} if background else {}

        result = await gate.decide_tool_call(gated_request(**extra))

        expected_destination = (
            gate.ApprovalDestination.CONVERSATION if background else gate.ApprovalDestination.CHAT
        )
        assert gate._approval_destination(background=background) is expected_destination
        _assert_pending(result)
        assert result is not None
        content = str(result.content)
        where = gate._DESTINATION_WORDING[expected_destination]
        assert content.startswith(
            "PENDING ap_live: Send the old one already requested and awaiting the user's "
            f"decision. The approval request appears to the user in {where}, "
        )
        assert 'execute(tool_name="revoke", data={"id": "ap_live"})' in content
        gate_seams.ledger.register.assert_not_awaited()
        gate_seams.announce.assert_not_awaited()

    @pytest.mark.parametrize(
        ("feedback", "said"),
        [("too broad", " The user said: 'too broad'."), (None, "")],
        ids=["with-words", "bare"],
    )
    async def test_a_same_run_reissue_is_refused(
        self, gate_seams: GateSeams, feedback: str | None, said: str
    ) -> None:
        gate_seams.ledger.find_latest_denied.return_value = _row(
            outcome=ApprovalOutcome.DENIED,
            action=None,
            proposing_run_id=STREAM_ID,
            feedback=feedback,
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == (
            f"REFUSED ap_old: the user denied Send the old one in this run.{said} "
            "DO NOT re-request it. State what you skipped and continue without it."
        )
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"


@pytest.mark.unit
class TestLedgerValidatesArgsAgainstTheRealTool:
    async def test_malformed_args_answer_with_the_schema_error(self, gate_seams: GateSeams) -> None:
        result = await gate.decide_tool_call(gated_request(args={}))

        assert result is not None
        content = str(result.content)
        assert content.startswith(f"Invalid arguments for {GATED_TOOL}: ")
        assert "to" in content
        assert content.endswith(" Fix the arguments and retry — no approval was requested.")
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"
        gate_seams.ledger.register.assert_not_awaited()

    async def test_an_unresolvable_tool_is_reported_and_skips_the_check(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.gated_tool.side_effect = RuntimeError("catalog down")

        result = await gate.decide_tool_call(gated_request(args={}))

        assert result is not None
        assert str(result.content).startswith("PENDING ap_abc1234567")
        gate_seams.log.warning.assert_called_once()
        assert "Pre-validation tool resolve failed" in gate_seams.log.warning.call_args.args[0]
        assert gate_seams.log.warning.call_args.kwargs == {
            "tool": GATED_TOOL,
            "error_type": "RuntimeError",
        }


@pytest.mark.unit
class TestLedgerAutoMode:
    """Auto mode on the ledger path: the judge sees the real call, and its verdict decides."""

    async def test_the_judge_rules_on_the_real_call_with_the_users_memory(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        rows = [
            _row(
                outcome=ApprovalOutcome.DENIED,
                action=None,
                feedback="no",
                decided_at=datetime(2026, 9, 1),
            )
        ]
        gate_seams.ledger.recent_tool_outcomes.side_effect = lambda uid, tool: (
            rows if (uid, tool) == (USER_ID, GATED_TOOL) else []
        )
        messages = [AIMessage(content="Your draft to b@x is ready.")]

        await gate.decide_tool_call(gated_request(messages=messages))

        kwargs = gate_seams.judge.await_args.kwargs
        assert gate_seams.judge.await_args.args == (
            AutoContext(user_id=USER_ID, history=summarize_history(rows), never_auto=False),
        )
        assert kwargs["call"] == JudgedCall(
            tool_name=GATED_TOOL,
            description="Send an email.",
            args=GATED_ARGS,
            summary=GATED_SUMMARY,
            tool_schema=gate_seams.tool.args,
        )
        assert kwargs["assistant_turns"] == ["Your draft to b@x is ready."]
        assert isinstance(kwargs["judge"], JevIntentJudge)
        assert kwargs["user_messages"] == ["send it to b@x"]

    async def test_a_tool_the_user_never_lets_auto_mode_run_reaches_the_judge_as_never_auto(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"

        await gate.decide_tool_call(gated_request(name="DROP_TABLE"))

        (context,) = gate_seams.judge.await_args.args
        assert context.never_auto is True

    # 20:00 UTC on the 14th is already the 15th in Kolkata.
    @time_machine.travel(datetime(2026, 11, 14, 20, 0, tzinfo=UTC), tick=False)
    async def test_the_card_and_the_judge_name_a_date_on_the_users_own_calendar(
        self, gate_seams: GateSeams
    ) -> None:
        todo = gated_request(
            name="create_todo",
            args={"title": "Pay rent", "due_date": "2026-11-15"},
            user_timezone="Asia/Kolkata",
        )

        await gate.decide_tool_call(todo)
        gate_seams.policy.return_value = "auto"
        await gate.decide_tool_call(todo)

        asked = gate_seams.requested.await_args.args[2].description.headline
        judged = gate_seams.judge.await_args.kwargs["call"].summary
        assert asked.endswith("for today")
        assert judged.endswith("for today")

    async def test_the_judge_is_told_which_account_the_call_acts_as(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"

        await gate.decide_tool_call(account_gated_request())

        assert gate_seams.judge.await_args.kwargs["call"].summary == GATED_ACCOUNT_SUMMARY

    async def test_an_accepted_call_runs_with_no_row(self, gate_seams: GateSeams) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("accept", "asked")

        assert await gate.decide_tool_call(gated_request()) is None
        gate_seams.ledger.register.assert_not_awaited()

    @pytest.mark.regression
    async def test_an_auto_run_is_counted_as_a_decision_made_by_auto(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("accept", "asked")
        posthog = MagicMock()

        with patch("app.services.analytics_service._get_posthog_client", return_value=posthog):
            await gate.decide_tool_call(gated_request())

        [sent] = [c.kwargs for c in posthog.capture.call_args_list]
        assert (sent["event"], sent["distinct_id"]) == ("hil:decision_submitted", USER_ID)
        decided = {key: sent["properties"].get(key) for key in ("decision", "tool_name", "via")}
        assert decided == {"decision": "approved", "tool_name": GATED_TOOL, "via": "auto"}

    async def test_an_unsure_judge_decides_nothing(self, gate_seams: GateSeams) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("ask", "the recipient is new")
        posthog = MagicMock()

        with patch("app.services.analytics_service._get_posthog_client", return_value=posthog):
            await gate.decide_tool_call(gated_request())

        assert "hil:decision_submitted" not in [
            c.kwargs["event"] for c in posthog.capture.call_args_list
        ]

    async def test_an_unsure_judge_tells_the_user_in_plain_words_and_the_model_why(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("ask", "the recipient is new")

        result = await gate.decide_tool_call(gated_request())

        _assert_pending(result)
        assert gate_seams.requested.await_args.args[2].auto_reason == AUTO_ASK_NOTE
        assert "Auto mode wasn't sure: the recipient is new" in str(result.content)

    async def test_an_unsure_judge_with_no_reason_still_says_why_it_asks(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"

        result = await gate.decide_tool_call(gated_request())

        _assert_pending(result)
        assert gate_seams.requested.await_args.args[2].auto_reason == AUTO_ASK_NOTE
        # With no reason to quote, nothing trails the guidance the model reads.
        assert str(result.content).endswith(
            "after approval you run it once via the approve ticket."
        )

    async def test_an_ask_policy_card_carries_no_auto_note(self, gate_seams: GateSeams) -> None:
        result = await gate.decide_tool_call(gated_request())

        _assert_pending(result)
        assert gate_seams.requested.await_args.args[2].auto_reason is None

    async def test_unreadable_memory_is_reported_and_judged_without(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.ledger.recent_tool_outcomes.side_effect = RuntimeError("mongo down")

        await gate.decide_tool_call(gated_request())

        assert gate_seams.judge.await_args.args == (AutoContext(user_id=USER_ID),)
        warnings = {c.args[0]: c.kwargs for c in gate_seams.log.warning.call_args_list}
        assert warnings == {
            f"{LogTag.HIL} auto history unavailable; judging without memory": {
                "tool_name": GATED_TOOL,
                "error": "mongo down",
                "error_type": "RuntimeError",
            },
        }

    async def test_an_unreadable_deny_rule_list_denies_the_call_instead_of_judging_it(
        self, gate_seams: GateSeams
    ) -> None:
        """Regression for review finding 23: the judge ran without the deny rules, so a never-auto tool could be auto-approved."""
        gate_seams.policy.return_value = "auto"
        gate_seams.prefs.side_effect = ConnectionError("prefs down")

        result = await gate.decide_tool_call(gated_request())

        gate_seams.judge.assert_not_awaited()
        gate_seams.ledger.register.assert_not_awaited()
        assert result is not None and "NOT performed" in str(result.content)


@pytest.mark.unit
class TestTheGateBeforeAnyPolicy:
    async def test_an_identity_less_call_is_refused_and_reported(
        self, gate_seams: GateSeams
    ) -> None:
        request = make_request(name=GATED_TOOL, args=GATED_ARGS, configurable={})

        refused = await gate.decide_tool_call(request)
        assert refused is not None
        assert refused.additional_kwargs[HIL_STATUS_KWARG] == "error"
        gate_seams.log.error.assert_called_once()
        assert "no run identity" in gate_seams.log.error.call_args.args[0]
        assert gate_seams.log.error.call_args.kwargs == {"tool_name": GATED_TOOL}
        gate_seams.policy.assert_not_awaited()
