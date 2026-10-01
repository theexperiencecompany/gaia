"""Ledger branch of the approval gate (flag on: register, never interrupt)."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
import pytest

from app.constants.hil import HIL_STATUS_KWARG
from app.constants.log_tags import LogTag
from app.models.hil_models import (
    ApprovalLedgerDocument,
    ApprovalProposal,
    HILApprovalStatus,
    LedgerState,
)
from app.services.hil import gate
from app.services.hil.bridge import ApprovalOutcome
from app.services.hil.fingerprint import approval_fingerprint
from app.services.hil.intent import AutoContext, IntentDecision, JudgedCall, summarize_history
from app.services.hil.jev_judge import JevIntentJudge
from app.services.hil.prompts import AUTO_REJECT_TEMPLATE, DENIED_TEMPLATE, GATE_ERROR_TEMPLATE
from app.services.hil.utils import GatedCall
from app.utils.general_utils import ELLIPSIS

from .conftest import (
    CONVERSATION_ID,
    GATED_ARGS,
    GATED_SUMMARY,
    GATED_TOOL,
    STREAM_ID,
    USER_ID,
    GateSeams,
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
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        intr.assert_not_called()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)
        assert "needs the user's explicit approval" in str(result.content)
        assert 'execute(tool_name="revoke"' in str(result.content)
        assert "approve ticket" in str(result.content)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"

    async def test_background_pending_points_at_the_approvals_tab(self) -> None:
        """A background run has no watcher: the card lives in the Approvals tab, so the guidance must say so instead of "when this run ends"."""
        ledger = _ledger()
        request = _gated_request(execution_mode="background")
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(request)

        intr.assert_not_called()
        assert result is not None
        assert "Approvals tab" in str(result.content)
        assert "when this run ends" not in str(result.content)

    async def test_background_workflow_run_tags_the_ledger_owner(self) -> None:
        """The resume driver needs to know WHAT parked: a background workflow run stamps its owner on the row; nothing else does."""
        ledger = _ledger()
        request = _gated_request(execution_mode="background", workflow_id="wf-1")
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt"),
        ):
            await gate.decide_tool_call(request)

        assert ledger.register.await_args.args[0].owner_run_type == "workflow"
        assert ledger.register.await_args.args[0].owner_id == "wf-1"

    async def test_background_run_threads_the_owner_to_publish(self) -> None:
        """Publish is what raises the sidebar flag — it must receive the same owner the row carries, or background cards never surface."""
        ledger = _ledger()
        request = _gated_request(execution_mode="background", active_todo_id="todo-9")
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
            patch(f"{MODULE}.interrupt"),
        ):
            await gate.decide_tool_call(request)

        assert pub.await_args.kwargs["owner_run_type"] == "todo"
        assert pub.await_args.kwargs["owner_id"] == "todo-9"

    async def test_live_run_publishes_with_no_owner(self) -> None:
        """Live runs resume through the inbox — an owner here would wrongly surface (and re-enqueue) them."""
        ledger = _ledger()
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
            patch(f"{MODULE}.interrupt"),
        ):
            await gate.decide_tool_call(_gated_request())

        assert pub.await_args.kwargs["owner_run_type"] == ""
        assert pub.await_args.kwargs["owner_id"] == ""

    async def test_background_todo_run_tags_the_ledger_owner(self) -> None:
        ledger = _ledger()
        request = _gated_request(execution_mode="background", active_todo_id="todo-9")
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt"),
        ):
            await gate.decide_tool_call(request)

        assert ledger.register.await_args.args[0].owner_run_type == "todo"
        assert ledger.register.await_args.args[0].owner_id == "todo-9"

    async def test_live_run_with_ids_tags_no_owner(self) -> None:
        """Owner tagging is resume-scoped: a live run resumes through the executor inbox and must never re-enqueue, even carrying the keys."""
        ledger = _ledger()
        request = _gated_request(workflow_id="wf-1", active_todo_id="todo-9")
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt"),
        ):
            await gate.decide_tool_call(request)

        assert ledger.register.await_args.args[0].owner_run_type == ""
        assert ledger.register.await_args.args[0].owner_id == ""

    async def test_flag_off_takes_the_old_interrupt_path(self) -> None:
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=_ledger()) as ledger,
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.recall_declined_call", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.publish_approval_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            await gate.decide_tool_call(_gated_request())

        ledger.find_live.assert_not_awaited()
        intr.assert_called_once()

    async def test_live_duplicate_returns_existing_id_without_register(self) -> None:
        live = MagicMock(approval_id="ap_live", summary="Send it")
        live.state = LedgerState.PENDING
        ledger = _ledger(live=live)
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        intr.assert_not_called()
        assert result is not None
        assert "PENDING ap_live" in str(result.content)
        assert "already requested" in str(result.content)

    async def test_live_approved_row_is_not_called_awaiting_decision(self) -> None:
        live = MagicMock(approval_id="ap_live", summary="Send it")
        live.state = LedgerState.APPROVED
        ledger = _ledger(live=live)
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        intr.assert_not_called()
        assert result is not None
        assert "APPROVED ap_live" in str(result.content)
        assert "awaiting redeem" in str(result.content)

    async def test_same_run_denied_reissue_is_refused(self) -> None:
        denied = MagicMock(proposing_run_id=STREAM_ID, feedback="too broad", decided_at=None)
        ledger = _ledger(denied=denied)
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        intr.assert_not_called()
        assert result is not None
        assert "REFUSED" in str(result.content)
        assert "DO NOT re-request" in str(result.content)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"

    async def test_older_denied_run_registers_with_the_why_attached(self) -> None:
        denied = MagicMock(proposing_run_id="other-stream", feedback="wrong day", decided_at=None)
        ledger = _ledger(denied=denied)
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        intr.assert_not_called()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)
        assert "wrong day" in str(result.content)

    async def test_ledger_failure_fails_closed_without_interrupt(self) -> None:
        ledger = _ledger()
        ledger.find_live = AsyncMock(side_effect=ConnectionError("mongo down"))
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        intr.assert_not_called()
        assert result is not None
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"


@pytest.mark.unit
class TestLedgerAutoParity:
    async def test_auto_aligned_call_runs_without_card_or_row(self) -> None:
        """Auto mode keeps its intent judge on the ledger path: an aligned call clears to run with no card and no ledger row, exactly like the barrier path."""
        ledger = _ledger()
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(
                f"{MODULE}._judge",
                new=AsyncMock(return_value=IntentDecision(outcome="accept", reason="asked")),
            ),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        assert result is None
        ledger.register.assert_not_awaited()
        pub.assert_not_awaited()
        intr.assert_not_called()

    async def test_auto_misaligned_call_still_registers(self) -> None:
        ledger = _ledger()
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="auto")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(
                f"{MODULE}._judge",
                new=AsyncMock(return_value=IntentDecision(outcome="ask", reason="unclear")),
            ),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()),
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        intr.assert_not_called()
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
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=_strict_tool())),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_not_awaited()
        pub.assert_not_awaited()
        intr.assert_not_called()
        assert result is not None
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "error"
        assert "subject" in str(result.content)
        assert "no approval was requested" in str(result.content)

    async def test_unresolvable_tool_skips_validation(self) -> None:
        """Resolution failure must not gate: execution validates authoritatively, the gate only pre-filters what it can read."""
        ledger = _ledger()
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}.gated_tool_object", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
            patch(f"{MODULE}.interrupt") as intr,
        ):
            result = await gate.decide_tool_call(_gated_request())

        ledger.register.assert_awaited_once()
        pub.assert_awaited_once()
        intr.assert_not_called()
        assert result is not None
        assert "PENDING ap_abc1234567" in str(result.content)


def _guidance(approval_id: str, *, background: bool = False) -> str:
    """Spell out the pending-card guidance: it is the model's whole instruction set."""
    where = (
        "the Approvals tab (this run has no watcher; nothing here will wake it)"
        if background
        else "chat (web, mobile, desktop) when this run ends"
    )
    return (
        f"The approval card appears to the user in {where}, and they decide there; "
        "you cannot approve it yourself. "
        f'If this step is not needed, withdraw it with execute(tool_name="revoke", '
        f'data={{"id": "{approval_id}"}}) before the run ends and the user will never see it. '
        "If it is genuinely needed, leave it and move on to independent work "
        "or exit — you will be woken with the approval and run it via "
        'execute(tool_name="approve", data={"id": ...}). '
        "Re-calling with the same arguments returns the same pending id: it "
        "never runs the tool directly — after approval you run it once via "
        "the approve ticket."
    )


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


def _pending_text(*, why: str, tail: str = "", background: bool = False) -> str:
    return (
        f"PENDING ap_abc1234567: {GATED_SUMMARY} queued — {why}. "
        f"{_guidance('ap_abc1234567', background=background)}{tail}"
    )


_ASK_WHY = "this tool needs the user's explicit approval"
_AUTO_WHY = "auto-approve did not cover this call, so it needs the user's decision"


@pytest.mark.unit
class TestLedgerRegistration:
    """A fresh gated call becomes one exact ledger row and one card, and the model is told so."""

    async def test_the_proposal_carries_the_whole_call_and_its_provenance(
        self, gate_seams: GateSeams
    ) -> None:
        result = await gate.decide_tool_call(gated_request(thread_id="gmail_conv-1"))

        fingerprint = approval_fingerprint(GATED_TOOL, GATED_ARGS)
        gate_seams.recall.assert_awaited_once_with(STREAM_ID, GATED_TOOL, GATED_ARGS)
        gate_seams.ledger.find_live.assert_awaited_once_with(fingerprint, CONVERSATION_ID)
        gate_seams.ledger.find_latest_denied.assert_awaited_once_with(fingerprint, CONVERSATION_ID)
        gate_seams.ledger.register.assert_awaited_once_with(
            ApprovalProposal(
                conversation_id=CONVERSATION_ID,
                user_id=USER_ID,
                fingerprint=fingerprint,
                tool_name=GATED_TOOL,
                args=GATED_ARGS,
                summary=GATED_SUMMARY,
                preview='{"to": "b@x"}',
                owner_agent="gmail_conv-1",
                proposing_run_id=STREAM_ID,
            )
        )
        gate_seams.publish_ledger.assert_awaited_once_with(
            approval_id="ap_abc1234567",
            stream_id=STREAM_ID,
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            tool_call=GatedCall(name=GATED_TOOL, id="call-1", args=GATED_ARGS),
            summary=GATED_SUMMARY,
            integration_name="Gmail",
            auto_reason=None,
            owner_run_type="",
            owner_id="",
            live=True,
        )
        assert result is not None
        assert result.content == _pending_text(why=_ASK_WHY)
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"
        gate_seams.interrupt.assert_not_called()

    async def test_a_worker_with_no_thread_is_recorded_as_unknown(
        self, gate_seams: GateSeams
    ) -> None:
        await gate.decide_tool_call(gated_request())

        assert gate_seams.ledger.register.await_args.args[0].owner_agent == "unknown"

    async def test_a_background_run_with_no_owner_stamps_none(self, gate_seams: GateSeams) -> None:
        result = await gate.decide_tool_call(gated_request(execution_mode="background"))

        proposal = gate_seams.ledger.register.await_args.args[0]
        assert (proposal.owner_run_type, proposal.owner_id) == ("", "")
        assert gate_seams.publish_ledger.await_args.kwargs["live"] is False
        assert result is not None
        assert result.content == _pending_text(why=_ASK_WHY, background=True)

    async def test_a_long_or_non_json_argument_still_previews(self, gate_seams: GateSeams) -> None:
        args: dict[str, Any] = {"to": "b@x", "at": datetime(2026, 1, 1), "note": "n" * 600}

        await gate.decide_tool_call(gated_request(args=args))

        preview = gate_seams.ledger.register.await_args.args[0].preview
        assert preview.startswith('{"to": "b@x", "at": "2026-01-01 00:00:00", "note": "nnn')
        assert len(preview) == 500 + len(ELLIPSIS)
        assert preview.endswith(ELLIPSIS)

    async def test_an_older_denial_is_quoted_with_its_time_and_words(
        self, gate_seams: GateSeams
    ) -> None:
        decided_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        gate_seams.ledger.find_latest_denied.return_value = _row(
            state=LedgerState.DENIED,
            proposing_run_id="other-stream",
            feedback="wrong day",
            decided_at=decided_at,
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == _pending_text(
            why=_ASK_WHY,
            tail=(
                f" The user denied this exact call at {decided_at.isoformat()}, saying "
                "'wrong day'. Only re-ask if something changed or the user asked for it."
            ),
        )

    async def test_a_bare_older_denial_still_warns(self, gate_seams: GateSeams) -> None:
        gate_seams.ledger.find_latest_denied.return_value = _row(
            state=LedgerState.DENIED, proposing_run_id="other-stream"
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == _pending_text(
            why=_ASK_WHY,
            tail=(
                " The user denied this exact call. Only re-ask if something changed or "
                "the user asked for it."
            ),
        )

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
            approval_id="ap_live", state=LedgerState.APPROVED
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
    async def test_a_pending_twin_repeats_its_guidance(
        self, gate_seams: GateSeams, background: bool
    ) -> None:
        gate_seams.ledger.find_live.return_value = _row(approval_id="ap_live")
        extra = {"execution_mode": "background"} if background else {}

        result = await gate.decide_tool_call(gated_request(**extra))

        assert result is not None
        assert result.content == (
            "PENDING ap_live: Send the old one already requested and awaiting the user's "
            f"decision. {_guidance('ap_live', background=background)}"
        )
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "pending"

    @pytest.mark.parametrize(
        ("feedback", "said"),
        [("too broad", " The user said: 'too broad'."), (None, "")],
        ids=["with-words", "bare"],
    )
    async def test_a_same_run_reissue_is_refused(
        self, gate_seams: GateSeams, feedback: str | None, said: str
    ) -> None:
        gate_seams.ledger.find_latest_denied.return_value = _row(
            state=LedgerState.DENIED, proposing_run_id=STREAM_ID, feedback=feedback
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == (
            f"REFUSED ap_old: the user denied Send the old one in this run.{said} "
            "DO NOT re-request it. State what you skipped and continue without it."
        )
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"


@pytest.mark.unit
class TestLedgerDeclineMemory:
    async def test_a_users_decline_this_turn_is_repeated_back(self, gate_seams: GateSeams) -> None:
        gate_seams.recall.return_value = ApprovalOutcome(
            status=HILApprovalStatus.DENIED, feedback="wrong person"
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == DENIED_TEMPLATE.format(
            tool=GATED_TOOL, feedback=" The user said: 'wrong person'."
        )
        assert result.additional_kwargs[HIL_STATUS_KWARG] == "denied"
        gate_seams.ledger.register.assert_not_awaited()

    async def test_an_auto_refusal_without_words_is_repeated_as_auto(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.recall.return_value = ApprovalOutcome(
            status=HILApprovalStatus.DENIED, feedback=None, auto=True
        )

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == AUTO_REJECT_TEMPLATE.format(tool=GATED_TOOL, reason="")
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
        rows = [_row(state=LedgerState.DENIED, feedback="no", decided_at=datetime(2026, 9, 1))]
        gate_seams.ledger.recent_tool_outcomes.side_effect = lambda uid, tool: (
            rows if (uid, tool) == (USER_ID, GATED_TOOL) else []
        )
        messages = [AIMessage(content="Your draft to b@x is ready.")]

        await gate.decide_tool_call(gated_request(messages=messages))

        kwargs = gate_seams.judge.await_args.kwargs
        assert gate_seams.judge.await_args.args == (
            AutoContext(
                user_id=USER_ID,
                history=summarize_history(rows),
                never_auto_tools=frozenset({"DROP_TABLE"}),
            ),
        )
        assert kwargs["call"] == JudgedCall(
            tool_name=GATED_TOOL,
            description="Send an email.",
            args=GATED_ARGS,
            summary=GATED_SUMMARY,
            tool_schema=gate_seams.tool.args,
        )
        assert kwargs["assistant_turns"] == ["Your draft to b@x is ready."]
        assert kwargs["judge"] is None
        assert kwargs["user_messages"] == ["send it to b@x"]

    async def test_the_jev_judge_is_used_only_for_its_enrolled_user(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.jev_enabled.add(USER_ID)

        await gate.decide_tool_call(gated_request())

        assert isinstance(gate_seams.judge.await_args.kwargs["judge"], JevIntentJudge)

    async def test_an_accepted_call_runs_with_no_row(self, gate_seams: GateSeams) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("accept", "asked")

        assert await gate.decide_tool_call(gated_request()) is None
        gate_seams.ledger.register.assert_not_awaited()

    async def test_a_pausing_sibling_withholds_auto_approval(self, gate_seams: GateSeams) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.pausing_sibling.return_value = True
        gate_seams.judge.return_value = IntentDecision("accept", "asked")

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == _pending_text(why=_AUTO_WHY)
        gate_seams.judge.assert_not_awaited()

    async def test_an_unsure_judge_explains_itself_on_the_card_and_to_the_model(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("ask", "the recipient is new")

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == _pending_text(
            why=_AUTO_WHY, tail=" Auto mode wasn't sure: the recipient is new"
        )
        assert (
            gate_seams.publish_ledger.await_args.kwargs["auto_reason"]
            == "Auto mode wasn't sure: the recipient is new"
        )

    async def test_an_unsure_judge_with_no_reason_adds_nothing(self, gate_seams: GateSeams) -> None:
        gate_seams.policy.return_value = "auto"

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == _pending_text(why=_AUTO_WHY)
        assert gate_seams.publish_ledger.await_args.kwargs["auto_reason"] is None

    async def test_a_rejected_call_is_refused_and_remembered_as_auto(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("reject", "you said never email b@x")

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == AUTO_REJECT_TEMPLATE.format(
            tool=GATED_TOOL, reason="you said never email b@x"
        )
        gate_seams.remember.assert_awaited_once_with(
            STREAM_ID, GATED_TOOL, GATED_ARGS, "you said never email b@x", auto=True
        )
        gate_seams.ledger.register.assert_not_awaited()

    async def test_a_lost_decline_memory_is_reported_but_still_refuses(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.judge.return_value = IntentDecision("reject", "no")
        gate_seams.remember.side_effect = RuntimeError("redis down")

        result = await gate.decide_tool_call(gated_request())

        assert result is not None
        assert result.content == AUTO_REJECT_TEMPLATE.format(tool=GATED_TOOL, reason="no")
        gate_seams.log.warning.assert_called_once()
        assert "decline memory write failed" in gate_seams.log.warning.call_args.args[0]
        assert gate_seams.log.warning.call_args.kwargs == {
            "tool_name": GATED_TOOL,
            "error": "redis down",
            "error_type": "RuntimeError",
        }

    async def test_unreadable_memory_and_prefs_are_reported_and_judged_without(
        self, gate_seams: GateSeams
    ) -> None:
        gate_seams.policy.return_value = "auto"
        gate_seams.ledger.recent_tool_outcomes.side_effect = RuntimeError("mongo down")
        gate_seams.prefs.side_effect = ConnectionError("prefs down")

        await gate.decide_tool_call(gated_request())

        assert gate_seams.judge.await_args.args == (AutoContext(user_id=USER_ID),)
        warnings = {c.args[0]: c.kwargs for c in gate_seams.log.warning.call_args_list}
        assert warnings == {
            f"{LogTag.HIL} auto history unavailable; judging without memory": {
                "tool_name": GATED_TOOL,
                "error": "mongo down",
                "error_type": "RuntimeError",
            },
            f"{LogTag.HIL} never-auto list unreadable; judging without it": {
                "error": "prefs down",
                "error_type": "ConnectionError",
            },
        }


@pytest.mark.unit
class TestTheGateBeforeAnyPolicy:
    async def test_an_identity_less_call_is_reported_as_skipped(
        self, gate_seams: GateSeams
    ) -> None:
        request = make_request(name=GATED_TOOL, args=GATED_ARGS, configurable={})

        assert await gate.decide_tool_call(request) is None
        gate_seams.log.warning.assert_called_once()
        assert "Gate skipped: no run identity" in gate_seams.log.warning.call_args.args[0]
        assert gate_seams.log.warning.call_args.kwargs == {"tool_name": GATED_TOOL}
        gate_seams.policy.assert_not_awaited()
