"""Ledger decide: CAS commit, stale-v refresh, queued approvals, no execution yet."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.agents.tools.execute.dispatch import DispatchErrorKind
from app.constants.agents import AgentTag
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.constants.log_tags import LogTag
from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.models.user_models import AuthenticatedUser
from app.schemas.hil_schemas import BatchDecisionItem, BatchDecisionOutcome
from app.services.analytics_service import AnalyticsEvents
from app.services.hil.ledger_decide import (
    STALE_HOLDER_MIN_AGE_SECONDS,
    STALLED_EXECUTING_MINUTES,
    LedgerDecision,
    RedeemResult,
    _reclaim_dead_holder,
    cancel_ledger_approvals,
    decide_ledger,
    decide_ledger_batch,
    publish_ledger_decision,
    publish_ledger_revocation,
    reconcile_conversation_ledger,
    redeem_approved,
    revoke_ticket,
)
from app.services.hil.resolution import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
)

MODULE = "app.services.hil.ledger_decide"
RUNNER = "app.agents.core.background.executor_runner"


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock()
    row.approval_id = "ap_abc"
    row.conversation_id = "conv-1"
    row.user_id = "u1"
    row.tool_name = "GMAIL_SEND_EMAIL"
    row.args = {"to": "b@x"}
    row.summary = "Send it"
    row.state = LedgerState.PENDING
    row.v = 3
    row.blocked_by = []
    row.decided_at = None
    row.feedback = None
    row.owner_run_type = ""
    row.owner_id = ""
    # Real datetime: the decision path computes card age from it, and a
    # MagicMock would TypeError on the subtraction, hiding real type errors.
    row.created_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _repo(row: Any = None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_approval_id = AsyncMock(return_value=row)
    repo.transition = AsyncMock(return_value=True)
    repo.list_stalled_executing = AsyncMock(return_value=[])
    return repo


@pytest.mark.unit
class TestDecideLedger:
    async def test_approve_cas_commits_and_delivers_ticket(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        assert outcome.prior_state == LedgerState.PENDING
        assert outcome.state == LedgerState.APPROVED
        assert outcome.queued is False
        repo.transition.assert_awaited_once_with(
            "ap_abc",
            LedgerState.PENDING,
            LedgerState.APPROVED,
            decided_by="u1",
            feedback=None,
        )
        deliver.assert_awaited_once()

    async def test_approve_delivery_failure_falls_back_to_wake(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(
                ledger_decide,
                "_deliver_ticket",
                new=AsyncMock(side_effect=RuntimeError("redis down")),
            ),
            patch.object(ledger_decide, "_wake_agent", new=AsyncMock()) as wake,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        wake.assert_awaited_once_with(repo.get_by_approval_id.return_value, "APPROVED", None)

    async def test_stale_v_returns_current_row_without_writing(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row(state=LedgerState.APPROVED, v=4))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is False
        assert outcome.state == LedgerState.APPROVED
        repo.transition.assert_not_awaited()
        deliver.assert_not_awaited()

    async def test_deny_commits_without_delivery(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="deny", feedback="nope", v=3)

        assert outcome.committed is True
        assert outcome.state == LedgerState.DENIED
        repo.transition.assert_awaited_once_with(
            "ap_abc",
            LedgerState.PENDING,
            LedgerState.DENIED,
            decided_by="u1",
            feedback="nope",
        )
        deliver.assert_not_awaited()

    async def test_blocked_approval_stays_queued_without_delivery(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row(blocked_by=["ap_dep"]))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        assert outcome.queued is True
        deliver.assert_not_awaited()

    async def test_stale_v_marks_stale_not_gone(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row(state=LedgerState.APPROVED, v=4))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()),
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is False
        assert outcome.stale is True
        assert outcome.state.value == "approved"

    async def test_unknown_id_raises_not_found(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger
        from app.services.hil.resolution import ApprovalRequestNotFoundError

        with (
            patch(f"{MODULE}.approval_ledger_repository", new=_repo(None)),
            pytest.raises(ApprovalRequestNotFoundError),
        ):
            await decide_ledger("ap_nope", user_id="u1", kind="approve", v=None)


@pytest.mark.unit
class TestDecisionSubmittedEvent:
    async def test_approve_emits_event_with_user_id(self) -> None:
        """Same attribution rule as revoke: the decide path resolves its user from the row, so the event must carry that id explicitly."""
        from app.services.analytics_service import AnalyticsEvents
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event") as capture,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        capture.assert_called_once()
        user_id, event, props = capture.call_args.args
        assert user_id == "u1"
        assert event == AnalyticsEvents.HIL_DECISION_SUBMITTED
        assert props["approval_id"] == "ap_abc"
        assert props["decision"] == "approved"
        assert props["ledger_version"] == 4
        assert props["card_age_seconds"] is not None
        assert props["card_age_seconds"] < 60

    async def test_deny_emits_deny_decision(self) -> None:
        from app.services.analytics_service import AnalyticsEvents
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event") as capture,
        ):
            await decide_ledger("ap_abc", user_id="u1", kind="deny", v=3)

        assert capture.call_args.args[1] == AnalyticsEvents.HIL_DECISION_SUBMITTED
        assert capture.call_args.args[2]["decision"] == "denied"

    async def test_uncommitted_decisions_emit_nothing(self) -> None:
        """Stale-v and lost-CAS returns decided nothing — an event would count attempts as successes."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        stale_repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=stale_repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event") as capture,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=99)

        assert outcome.committed is False
        capture.assert_not_called()

        lost_repo = _repo(_row())
        lost_repo.transition = AsyncMock(return_value=False)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=lost_repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event") as capture,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is False
        capture.assert_not_called()


@pytest.mark.unit
class TestConversationFlagSync:
    async def test_decide_refreshes_the_sidebar_flag(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event"),
            patch.object(ledger_decide, "sync_conversation_approval_flag", new=AsyncMock()) as sync,
        ):
            await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        sync.assert_awaited_once_with("conv-1", "u1")

    async def test_revoke_refreshes_the_sidebar_flag(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row())
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event"),
            patch.object(ledger_decide, "sync_conversation_approval_flag", new=AsyncMock()) as sync,
        ):
            await revoke_ticket(
                "ap_abc", user_id="u1", conversation_id="conv-1", caller="executor_conv-1"
            )

        sync.assert_awaited_once_with("conv-1", "u1")

    async def test_refused_revoke_syncs_nothing(self) -> None:
        """A revoke that changed nothing must not touch the flag — the row's state (and any flag it implies) is exactly as it was."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket
        from app.services.hil.resolution import ApprovalRequestForbiddenError

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event"),
            patch.object(ledger_decide, "sync_conversation_approval_flag", new=AsyncMock()) as sync,
            pytest.raises(ApprovalRequestForbiddenError),
        ):
            await revoke_ticket(
                "ap_abc",
                user_id="intruder",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        sync.assert_not_called()


@pytest.mark.unit
class TestDecideHardening:
    async def test_empty_owner_never_matches_any_user(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger
        from app.services.hil.resolution import ApprovalRequestForbiddenError

        repo = _repo(_row(user_id=""))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            pytest.raises(ApprovalRequestForbiddenError),
        ):
            await decide_ledger("ap_abc", user_id="u1", kind="approve", v=None)

        repo.transition.assert_not_awaited()

    async def test_deny_delivers_verdict_to_start_idle_run(self) -> None:
        """A deny must reach the agent even when the conversation is idle: the inbox wake alone is only read by a running run."""
        from app.services.hil.ledger_decide import decide_ledger

        row = _row()
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=_repo(row)),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()),
            patch(f"{MODULE}._deliver_verdict", new=AsyncMock()) as deliver,
            patch(f"{MODULE}._wake_agent", new=AsyncMock()) as wake,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="deny", feedback="nope", v=3)

        assert outcome.committed is True
        deliver.assert_awaited_once()
        assert deliver.await_args.args[1] == "DENIED"
        assert "nope" in str(deliver.await_args.args[2])
        wake.assert_not_awaited()

    async def test_deny_delivery_failure_falls_back_to_wake(self) -> None:
        from app.services.hil.ledger_decide import _deliver_verdict

        row = _row()
        with (
            patch(
                "app.agents.core.background.executor_runner.deliver_to_executor",
                new=AsyncMock(side_effect=RuntimeError("redis down")),
            ),
            patch(f"{MODULE}._wake_agent", new=AsyncMock()) as wake,
        ):
            await _deliver_verdict(row, "DENIED", "nope")

        wake.assert_awaited_once_with(row, "DENIED", "nope")

    async def test_queued_approve_wakes_with_blockers(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        row = _row(blocked_by=["ap_dep"])
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=_repo(row)),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
            patch(f"{MODULE}._wake_agent", new=AsyncMock()) as wake,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.queued is True
        deliver.assert_not_awaited()
        wake.assert_awaited_once_with(row, "QUEUED", "waiting on ap_dep")

    async def test_reconcile_heals_stalled_only(self) -> None:
        """Orphaned APPROVED rows are left alone: the ticket lives in model context and only a redeem runs the envelope — never re-nudge."""
        from app.models.hil_models import LedgerState as LS
        from app.services.hil.ledger_decide import reconcile_conversation_ledger

        stalled = _row(approval_id="ap_old")
        stalled.state = LS.EXECUTING
        orphan = _row(approval_id="ap_orphan")
        orphan.state = LS.APPROVED
        orphan.blocked_by = []
        repo = _repo()
        repo.list_stalled_executing = AsyncMock(return_value=[stalled])
        repo.transition = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
            patch(f"{MODULE}._wake_agent", new=AsyncMock()) as wake,
        ):
            await reconcile_conversation_ledger("conv-1")

        repo.transition.assert_awaited_once_with("ap_old", LS.EXECUTING, LS.UNKNOWN)
        deliver.assert_not_awaited()
        assert wake.await_count == 1

    async def test_reconcile_scopes_stalled_scan_to_conversation(self) -> None:
        # The stalled scan must not read every conversation's stalls on each
        # tap: scope rides in the query, not a Python-side discard.
        from app.services.hil.ledger_decide import reconcile_conversation_ledger

        repo = _repo()
        repo.list_stalled_executing = AsyncMock(return_value=[])
        repo.transition = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            await reconcile_conversation_ledger("conv-1")

        repo.list_stalled_executing.assert_awaited_once()
        assert repo.list_stalled_executing.await_args.args[1] == "conv-1"
        repo.transition.assert_not_awaited()
        deliver.assert_not_awaited()


@pytest.mark.unit
class TestRedeemExecution:
    def _redeem_repo(self) -> MagicMock:
        from app.models.hil_models import LedgerState as LS

        repo = _repo(_row(state=LS.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        return repo

    def _redeem_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": "u1",
            "conversation_id": "conv-1",
            "caller": "executor_conv-1",
        }

    async def test_provider_timeout_lands_unknown_never_failed(self) -> None:
        from app.agents.tools.execute.dispatch import DispatchError, DispatchErrorKind
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        timeout_result = MagicMock(
            ok=False,
            output=None,
            error=DispatchError(kind=DispatchErrorKind.TIMEOUT, detail="slow", hint="x"),
        )
        repo = self._redeem_repo()
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=timeout_result)
            ),
        ):
            result = await redeem_approved("ap_abc", **self._redeem_kwargs())

        repo.transition.assert_awaited_once_with("ap_abc", LS.EXECUTING, LS.UNKNOWN)
        assert result.ok is False
        assert result.state == LS.UNKNOWN
        assert "never auto-retried" in result.detail

    async def test_redeem_terminal_syncs_the_sidebar_flag(self) -> None:
        """A settled ticket must not leave its sidebar row behind."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        ok_result = MagicMock(ok=True, output="sent", error=None)
        repo = self._redeem_repo()
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)),
            patch.object(ledger_decide, "sync_conversation_approval_flag", new=AsyncMock()) as sync,
        ):
            result = await redeem_approved("ap_abc", **self._redeem_kwargs())

        assert result.state.value == "executed"
        sync.assert_awaited_once_with("conv-1", "u1")

    async def test_redeem_failed_transition_still_returns_state(self) -> None:
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        ok_result = MagicMock(ok=True, output="sent", error=None)
        repo = self._redeem_repo()
        repo.transition = AsyncMock(return_value=False)
        reconciled = _row()
        reconciled.state = LS.UNKNOWN
        approved = _row()
        approved.state = LS.APPROVED
        repo.get_by_approval_id = AsyncMock(side_effect=[approved, reconciled])
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)),
        ):
            result = await redeem_approved("ap_abc", **self._redeem_kwargs())

        assert result.ok is False
        assert "Already unknown" in result.detail


@pytest.mark.unit
class TestRedeemIdentity:
    async def test_redeem_dispatches_with_user_identity_in_config(self) -> None:
        """The approved envelope must run AS the row's user."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        config = dispatch.await_args.kwargs["config"]
        assert config["configurable"]["user_id"] == "u1"
        assert config["metadata"]["user_id"] == "u1"


@pytest.mark.unit
class TestRedeemTerminalStates:
    async def test_executed_returns_output(self) -> None:
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide,
                "dispatch_tool",
                new=AsyncMock(return_value=MagicMock(ok=True, output="deleted xyz", error=None)),
            ),
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        repo.transition.assert_awaited_once_with("ap_abc", LS.EXECUTING, LS.EXECUTED)
        assert result.ok is True
        assert result.state == LS.EXECUTED
        assert "deleted xyz" in result.detail

    async def test_failed_returns_error_detail(self) -> None:
        from app.agents.tools.execute.dispatch import DispatchError, DispatchErrorKind
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        failed = MagicMock(
            ok=False,
            output=None,
            error=DispatchError(kind=DispatchErrorKind.INVALID_ARGS, detail="bad date", hint="x"),
        )
        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=failed)),
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        repo.transition.assert_awaited_once_with("ap_abc", LS.EXECUTING, LS.FAILED)
        assert result.ok is False
        assert result.state == LS.FAILED
        assert "bad date" in result.detail

    async def test_raised_execution_returns_unknown_with_cause(self) -> None:
        """An infra raise must still tell the caller what happened: UNKNOWN with the cause, never a silent row flip."""
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide,
                "dispatch_tool",
                new=AsyncMock(side_effect=ValueError("No connected accounts")),
            ),
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        repo.transition.assert_awaited_once_with("ap_abc", LS.EXECUTING, LS.UNKNOWN)
        assert result.ok is False
        assert result.state == LS.UNKNOWN
        assert "No connected accounts" in result.detail


@pytest.mark.unit
class TestRevokeTicket:
    def _revoke_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": "u1",
            "conversation_id": "conv-1",
            "caller": "executor_conv-1",
        }

    async def test_revoke_tombstones_pending_row(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row())
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            text = await revoke_ticket("ap_abc", **self._revoke_kwargs())

        repo.transition.assert_awaited_once_with("ap_abc", LedgerState.PENDING, LedgerState.REVOKED)
        tombstone.assert_awaited_once()
        assert "Revoked 'ap_abc'" in text

    async def test_revoke_emits_event_with_user_id(self) -> None:
        """The revoke event must attribute to the row's user — an anonymous capture would strand it outside the user's funnel, silently."""
        from app.services.analytics_service import AnalyticsEvents
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row())
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()),
            patch.object(ledger_decide, "capture_event") as capture,
        ):
            await revoke_ticket("ap_abc", **self._revoke_kwargs())

        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.HIL_REVOKED,
            {
                "approval_id": "ap_abc",
                "ledger_version": 4,
                "revoker": "executor_conv-1",
            },
        )

    async def test_revoke_wrong_conversation_looks_absent(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            text = await revoke_ticket(
                "ap_abc",
                user_id="u1",
                conversation_id="other-conv",
                caller="executor_other-conv",
            )

        assert "No pending approval" in text
        dispatch.assert_not_awaited()

    async def test_revoke_cross_user_forbidden(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket
        from app.services.hil.resolution import ApprovalRequestForbiddenError

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
            pytest.raises(ApprovalRequestForbiddenError),
        ):
            await revoke_ticket(
                "ap_abc",
                user_id="attacker",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )
        repo.transition.assert_not_awaited()
        tombstone.assert_not_awaited()

    async def test_revoke_decided_row_refused(self) -> None:
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row(state=LS.APPROVED))
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            text = await revoke_ticket("ap_abc", **self._revoke_kwargs())

        assert "already approved" in text
        tombstone.assert_not_awaited()

    async def test_revoke_foreign_worker_refused(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        row = _row()
        row.owner_agent = "worker-other"
        repo = _repo(row)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            text = await revoke_ticket(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="worker-unrelated",
            )

        assert "another worker" in text
        tombstone.assert_not_awaited()


ANY_TEXT = "provider timed out; may or may not have run — never auto-retried"


@pytest.mark.unit
class TestApproveDeliversToExecutor:
    async def test_approve_wakes_executor_with_redeem_task(self) -> None:
        """Approval is permission, not execution: commit wakes the model with the ticket instead of scheduling a backend run."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        deliver.assert_awaited_once()
        claimed_row = deliver.await_args.args[0]
        assert claimed_row.approval_id == "ap_abc"


@pytest.mark.unit
class TestApproveResumesBackgroundOwner:
    async def test_approve_with_todo_owner_resumes(self) -> None:
        """A background todo parked on this approval re-enqueues; the tap never waits on it and never fails for it."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        row = _row(owner_run_type="todo", owner_id="todo-9")
        repo = _repo(row)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "resume_owner_after_approval", new=AsyncMock()) as resume,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        resume.assert_awaited_once_with(row)

    async def test_approve_without_owner_dispatches_to_a_no_op(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "resume_owner_after_approval", new=AsyncMock()) as resume,
        ):
            await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        # Dispatch is unconditional; the no-owner row returns before any claim.
        resume.assert_awaited_once()

    async def test_deny_records_todo_skip_and_resumes_nothing(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row(owner_run_type="todo", owner_id="todo-9"))
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_verdict", new=AsyncMock()),
            patch.object(ledger_decide, "resume_owner_after_approval", new=AsyncMock()) as resume,
            patch.object(ledger_decide, "record_owner_deny", new=AsyncMock()) as record,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="deny", feedback="nope", v=3)

        assert outcome.committed is True
        assert outcome.state == LedgerState.DENIED
        resume.assert_not_called()
        record.assert_awaited_once()

    async def test_redeem_runs_stored_envelope_and_returns_output(self) -> None:
        """The model supplies no args: the ticket IS the approval_id and the envelope runs verbatim."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="deleted xyz", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        dispatch.assert_awaited_once()
        assert dispatch.await_args.kwargs["data"] == {"to": "b@x"}
        assert result.ok is True
        assert "deleted xyz" in result.detail

    async def test_double_redeem_runs_envelope_once(self) -> None:
        """The claim is the single-use CAS: loser is refused, never re-run."""
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(side_effect=[True, False])
        repo.transition = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            first = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )
            second = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        assert first.ok is True
        assert first.state == LS.EXECUTED
        assert second.ok is False
        dispatch.assert_awaited_once()

    async def test_redeem_wrong_conversation_looks_absent(self) -> None:
        """No existence leak across conversations — mirrors revoke_tool."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved
        from app.services.hil.resolution import ApprovalRequestNotFoundError

        repo = _repo(_row(state=LedgerState.APPROVED))
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock()) as dispatch,
            pytest.raises(ApprovalRequestNotFoundError),
        ):
            await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="other-conv",
                caller="executor_other-conv",
            )
        dispatch.assert_not_awaited()

    async def test_redeem_non_approved_row_refused(self) -> None:
        from app.models.hil_models import LedgerState as LS
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LS.EXECUTED))
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        assert result.ok is False
        dispatch.assert_not_awaited()


@pytest.mark.unit
class TestConditionalApproveBecomesDeny:
    async def test_approve_with_feedback_records_denied(self) -> None:
        # Permission-scope guard: an envelope carries no conditions, so
        # "approve + note" must never run the unmodified args. It records
        # as denied with the note attached (chat-classifier parity).
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()) as deliver,
            patch.object(ledger_decide, "_deliver_verdict", new=AsyncMock()) as verdict,
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id="u1", kind="approve", feedback="cc finance", v=3
            )

        assert outcome.committed is True
        assert outcome.state == LedgerState.DENIED
        repo.transition.assert_awaited_once_with(
            "ap_abc",
            LedgerState.PENDING,
            LedgerState.DENIED,
            decided_by="u1",
            feedback="cc finance",
        )
        deliver.assert_not_awaited()
        verdict.assert_awaited_once()

    async def test_plain_approve_unaffected(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        assert outcome.state == LedgerState.APPROVED
        deliver.assert_awaited_once()


@pytest.mark.unit
class TestTicketCarriesAge:
    async def test_old_approve_commits_and_task_names_age(self) -> None:
        """No server refuse: a 3-day-old approve commits like any other, and the ticket wake carries the age so the model judges freshness."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import _ticket_task, decide_ledger

        old = _row()
        old.created_at = datetime.now(UTC) - timedelta(days=3)
        repo = _repo(old)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True
        deliver.assert_awaited_once()
        claimed_row = deliver.await_args.args[0]
        assert claimed_row.approval_id == "ap_abc"
        task = _ticket_task(old)
        assert task.startswith("APPROVAL_READY ap_abc")
        assert "72h" in task
        assert 'execute(tool_name="approve"' in task

    async def test_fresh_approve_still_commits(self) -> None:
        """Guard against over-blocking: a fresh card is unaffected."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        fresh = _row()
        fresh.created_at = datetime.now(UTC)
        repo = _repo(fresh)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="approve", v=3)

        assert outcome.committed is True

    async def test_stale_deny_still_passes(self) -> None:
        """Deny is a refusal — age never gates it."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        old = _row()
        old.created_at = datetime.now(UTC) - timedelta(days=3)
        repo = _repo(old)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
        ):
            outcome = await decide_ledger("ap_abc", user_id="u1", kind="deny", feedback="nope", v=3)

        assert outcome.committed is True
        assert outcome.state == LedgerState.DENIED


@pytest.mark.unit
class TestCancelLedgerApprovals:
    async def test_cancel_withdraws_user_pending_rows_only(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import cancel_ledger_approvals

        mine = _row(approval_id="ap_mine")
        approved = _row(approval_id="ap_ticket", state=LedgerState.APPROVED)
        foreign = _row(approval_id="ap_theirs", user_id="u2")
        repo = _repo()
        repo.list_open = AsyncMock(return_value=[mine, approved, foreign])
        repo.transition = AsyncMock(return_value=True)
        repo.get_by_approval_id = AsyncMock(return_value=mine)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            cancelled = await cancel_ledger_approvals("conv-1", "u1")

        assert cancelled == ["ap_mine"]
        repo.transition.assert_awaited_once_with(
            "ap_mine", LedgerState.PENDING, LedgerState.REVOKED
        )
        tombstone.assert_awaited_once()

    async def test_cancel_lost_race_skips_quietly(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import cancel_ledger_approvals

        repo = _repo()
        repo.list_open = AsyncMock(return_value=[_row()])
        repo.transition = AsyncMock(return_value=False)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            cancelled = await cancel_ledger_approvals("conv-1", "u1")

        assert cancelled == []
        tombstone.assert_not_awaited()


@pytest.mark.unit
class TestRevokeSettlesSessionFrame:
    async def test_revoke_flips_pending_frame_in_proposing_session(self) -> None:
        # BUG: revoke settled mongo + broadcast but never touched the proposing
        # session's in-memory frame; the drain later persisted the stale PENDING
        # frame back over it (production ap_d455 stuck pending post-revoke).
        from app.agents.core.background.session import (
            RunKind,
            create_session,
            get_session,
            teardown_session,
        )
        from app.models.hil_models import HILApprovalStatus
        from app.services.hil import ledger_decide
        from app.services.hil.bridge import GatedApproval, _approval_entry, _publish_entry
        from app.services.hil.utils import GatedCall

        stream_id = "stream-settle-test"
        create_session(stream_id, RunKind.LIVE)
        try:
            with patch(
                "app.services.hil.bridge.stream_manager.publish_chunk",
                new=AsyncMock(),
            ):
                await _publish_entry(
                    stream_id,
                    _approval_entry(
                        GatedApproval(
                            approval_id="ap_abc",
                            stream_id=stream_id,
                            user_id="u1",
                            conversation_id="conv-1",
                            tool_call=GatedCall(
                                name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}
                            ),
                            summary="Send it",
                            integration_name=None,
                        ),
                        HILApprovalStatus.PENDING,
                    ),
                )
            row = _row(proposing_run_id=stream_id, state=LedgerState.REVOKED)
            with (
                patch.object(ledger_decide, "_persist_decision_status", new=AsyncMock()),
                patch.object(ledger_decide, "_broadcast_decision", new=AsyncMock()),
            ):
                await ledger_decide.publish_ledger_revocation(row)
            frames = get_session(stream_id).tool_events
            assert len(frames) == 1
            assert frames[0]["tool_data"]["data"]["status"] == "revoked"
        finally:
            teardown_session(stream_id)


@pytest.mark.unit
class TestRedeemSettlesTerminalFrame:
    async def test_executed_settles_card_as_executed(self) -> None:
        # Production ap_38b3/d74bc/1454/a16e: ledger UNKNOWN while cards stayed
        # approved — redeem settled nothing. Terminal states must settle the frame
        # (persist + broadcast + session) so the card collapses to the outcome chip.
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)),
            patch.object(ledger_decide, "_persist_decision_status", new=AsyncMock()) as persist,
            patch.object(ledger_decide, "_broadcast_decision", new=AsyncMock()) as broadcast,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        assert result.ok is True
        assert result.state == LedgerState.EXECUTED
        persist.assert_awaited_once()
        assert persist.await_args.args[1] == "executed"
        broadcast.assert_awaited_once()
        assert broadcast.await_args.args[1] == "executed"

    async def test_failed_settles_card_as_failed(self) -> None:
        from app.agents.tools.execute.dispatch import DispatchError, DispatchErrorKind
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        failed = MagicMock(
            ok=False,
            output=None,
            error=DispatchError(kind=DispatchErrorKind.INVALID_ARGS, detail="bad", hint="x"),
        )
        repo = _repo(_row(state=LedgerState.APPROVED))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.transition = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=failed)),
            patch.object(ledger_decide, "_persist_decision_status", new=AsyncMock()) as persist,
            patch.object(ledger_decide, "_broadcast_decision", new=AsyncMock()) as broadcast,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id="u1",
                conversation_id="conv-1",
                caller="executor_conv-1",
            )

        assert result.ok is False
        persist.assert_awaited_once()
        assert persist.await_args.args[1] == "failed"
        broadcast.assert_awaited_once()
        assert broadcast.await_args.args[1] == "failed"


@pytest.mark.unit
class TestReclaimDeadHolder:
    async def test_free_lock_means_proceed(self) -> None:
        from app.services.hil import ledger_decide

        with patch.object(ledger_decide, "get_lock_holder", new=AsyncMock(return_value=None)):
            assert await ledger_decide._reclaim_dead_holder("conv-1") is True

    async def test_live_session_means_hold(self) -> None:
        from app.services.hil import ledger_decide

        with (
            patch.object(ledger_decide, "get_lock_holder", new=AsyncMock(return_value="s1:t1")),
            patch.object(ledger_decide, "get_session", return_value=MagicMock()),
        ):
            assert await ledger_decide._reclaim_dead_holder("conv-1") is False

    async def test_fresh_lock_means_hold(self) -> None:
        from types import SimpleNamespace

        from app.constants.cache import EXECUTOR_BUSY_TTL
        from app.services.hil import ledger_decide

        client = SimpleNamespace(ttl=AsyncMock(return_value=EXECUTOR_BUSY_TTL - 10))
        with (
            patch.object(ledger_decide, "get_lock_holder", new=AsyncMock(return_value="s1:t1")),
            patch.object(ledger_decide, "get_session", return_value=None),
            patch.object(ledger_decide, "redis_cache", new=SimpleNamespace(client=client)),
            patch.object(
                ledger_decide,
                "list_pending_for_conversation",
                new=AsyncMock(return_value=[]),
            ),
        ):
            assert await ledger_decide._reclaim_dead_holder("conv-1") is False

    async def test_paused_records_mean_hold(self) -> None:
        from types import SimpleNamespace

        from app.services.hil import ledger_decide

        parked = SimpleNamespace(resume_item={"task": "x"}, subagent_thread_id=None)
        client = SimpleNamespace(ttl=AsyncMock(return_value=100))
        with (
            patch.object(ledger_decide, "get_lock_holder", new=AsyncMock(return_value="s1:t1")),
            patch.object(ledger_decide, "get_session", return_value=None),
            patch.object(ledger_decide, "redis_cache", new=SimpleNamespace(client=client)),
            patch.object(
                ledger_decide,
                "list_pending_for_conversation",
                new=AsyncMock(return_value=[parked]),
            ),
            patch.object(ledger_decide, "break_holder_lock", new=AsyncMock()) as breaker,
        ):
            assert await ledger_decide._reclaim_dead_holder("conv-1") is False
        breaker.assert_not_awaited()

    async def test_dead_holder_is_released(self) -> None:
        from types import SimpleNamespace

        from app.services.hil import ledger_decide

        client = SimpleNamespace(ttl=AsyncMock(return_value=100))
        with (
            patch.object(ledger_decide, "get_lock_holder", new=AsyncMock(return_value="s1:t1")),
            patch.object(ledger_decide, "get_session", return_value=None),
            patch.object(ledger_decide, "redis_cache", new=SimpleNamespace(client=client)),
            patch.object(
                ledger_decide,
                "list_pending_for_conversation",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                ledger_decide, "break_holder_lock", new=AsyncMock(return_value=True)
            ) as breaker,
        ):
            assert await ledger_decide._reclaim_dead_holder("conv-1") is True
        breaker.assert_awaited_once_with("conv-1", "s1:t1")


def _doc(**overrides: Any) -> ApprovalLedgerDocument:
    fields: dict[str, Any] = {
        "approval_id": "ap_1",
        "conversation_id": "conv-1",
        "user_id": "u1",
        "fingerprint": "fp",
        "tool_name": "GMAIL_SEND_EMAIL",
        "args": {"to": "b@x"},
        "summary": "Send it",
        "owner_agent": "gmail_conv-1",
        "proposing_run_id": "stream-1",
        "v": 3,
    }
    return ApprovalLedgerDocument(**{**fields, **overrides})


@dataclass
class LedgerSeams:
    """Every seam the ledger decide path reaches; rows live in a dict the repo serves."""

    rows: dict[str, ApprovalLedgerDocument]
    repo: MagicMock
    capture: MagicMock
    log: MagicMock
    publish_entry: AsyncMock
    settle_frame: MagicMock
    sync_flag: AsyncMock
    persist: AsyncMock
    broadcast: AsyncMock
    inbox: MagicMock
    redis: MagicMock
    resume_owner: AsyncMock
    record_deny: AsyncMock
    deliver: AsyncMock
    lock_holder: AsyncMock
    break_lock: AsyncMock
    get_session: MagicMock
    barrier_pending: AsyncMock
    dispatch: AsyncMock


@pytest.fixture
def seams() -> Iterator[LedgerSeams]:
    rows: dict[str, ApprovalLedgerDocument] = {}

    async def _get(approval_id: str) -> ApprovalLedgerDocument | None:
        return rows.get(approval_id)

    repo = MagicMock()
    repo.get_by_approval_id = AsyncMock(side_effect=_get)
    repo.transition = AsyncMock(return_value=True)
    repo.claim_executing = AsyncMock(return_value=True)
    repo.list_open = AsyncMock(return_value=[])
    repo.list_stalled_executing = AsyncMock(return_value=[])
    inbox = MagicMock()
    inbox.return_value.append = AsyncMock()
    redis = MagicMock()
    redis.client.ttl = AsyncMock(return_value=100)
    conversations = MagicMock()
    conversations.set_message_approval_status = AsyncMock()
    websocket = MagicMock()
    websocket.broadcast_to_user = AsyncMock()
    with (
        patch(f"{MODULE}.approval_ledger_repository", new=repo),
        patch(f"{MODULE}.capture_event") as capture,
        patch(f"{MODULE}.log") as log,
        patch(f"{MODULE}._publish_entry", new=AsyncMock()) as publish_entry,
        patch(f"{MODULE}.settle_session_approval_frame") as settle_frame,
        patch(f"{MODULE}.sync_conversation_approval_flag", new=AsyncMock()) as sync_flag,
        patch(f"{MODULE}.conversation_repository", new=conversations),
        patch(f"{MODULE}.websocket_manager", new=websocket),
        patch(f"{MODULE}.ExecutorInbox", new=inbox),
        patch(f"{MODULE}.redis_cache", new=redis),
        patch(f"{MODULE}.resume_owner_after_approval", new=AsyncMock()) as resume_owner,
        patch(f"{MODULE}.record_owner_deny", new=AsyncMock()) as record_deny,
        patch(f"{RUNNER}.deliver_to_executor", new=AsyncMock()) as deliver,
        patch(f"{MODULE}.get_lock_holder", new=AsyncMock(return_value=None)) as lock_holder,
        patch(f"{MODULE}.break_holder_lock", new=AsyncMock(return_value=True)) as break_lock,
        patch(f"{MODULE}.get_session", return_value=None) as get_session,
        patch(
            f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=[])
        ) as barrier_pending,
        patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch,
        patch(f"{MODULE}.dispatch_config_for", side_effect=lambda uid: {"user": uid}),
    ):
        yield LedgerSeams(
            rows=rows,
            repo=repo,
            capture=capture,
            log=log,
            publish_entry=publish_entry,
            settle_frame=settle_frame,
            sync_flag=sync_flag,
            persist=conversations.set_message_approval_status,
            broadcast=websocket.broadcast_to_user,
            inbox=inbox,
            redis=redis,
            resume_owner=resume_owner,
            record_deny=record_deny,
            deliver=deliver,
            lock_holder=lock_holder,
            break_lock=break_lock,
            get_session=get_session,
            barrier_pending=barrier_pending,
            dispatch=dispatch,
        )


def _inbox_lines(seams: LedgerSeams) -> list[tuple[str, str, str]]:
    """Each wake as (conversation, text, tag), after checking its id is a fresh uuid."""
    lines = []
    for ctor, append in zip(
        seams.inbox.call_args_list, seams.inbox.return_value.append.await_args_list, strict=True
    ):
        message_id, text, tag = append.args
        UUID(message_id)
        lines.append((ctor.args[0], text, tag))
    return lines


def _warned(log_level: MagicMock) -> dict[str, dict[str, object]]:
    return {c.args[0]: c.kwargs for c in log_level.call_args_list}


_DENY_TAIL = (
    " The user said no — report what you skipped and continue without it. Do not re-request it."
)


@pytest.mark.unit
class TestDecideLedgerOutcomes:
    async def test_a_stale_version_refreshes_without_writing(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.PENDING, v=4)

        outcome = await decide_ledger("ap_1", user_id="u1", kind="approve", v=3)

        assert outcome == LedgerDecision(
            committed=False,
            approval_id="ap_1",
            prior_state=LedgerState.PENDING,
            state=LedgerState.PENDING,
            stale=True,
        )
        seams.repo.transition.assert_not_awaited()

    @pytest.mark.parametrize(
        ("current", "state"),
        [(LedgerState.DENIED, LedgerState.DENIED), (None, LedgerState.PENDING)],
        ids=["someone-else-won", "row-vanished"],
    )
    async def test_a_lost_race_reports_what_the_row_says_now(
        self, seams: LedgerSeams, current: LedgerState | None, state: LedgerState
    ) -> None:
        seams.rows["ap_1"] = _doc()

        async def _lose(*_: object, **__: object) -> bool:
            if current is None:
                seams.rows.pop("ap_1")
            else:
                seams.rows["ap_1"] = _doc(state=current)
            return False

        seams.repo.transition.side_effect = _lose

        outcome = await decide_ledger("ap_1", user_id="u1", kind="approve")

        assert outcome == LedgerDecision(
            committed=False, approval_id="ap_1", prior_state=LedgerState.PENDING, state=state
        )
        seams.capture.assert_not_called()

    async def test_whitespace_feedback_is_no_condition(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        outcome = await decide_ledger("ap_1", user_id="u1", kind="approve", feedback="   ")

        assert outcome.state is LedgerState.APPROVED

    async def test_a_conditional_approve_is_recorded_as_a_deny(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        await decide_ledger("ap_1", user_id="u1", kind="approve", feedback="cc finance")

        seams.log.set.assert_any_call(
            hil={"approval_id": "ap_1", "decision": "deny", "tool": "GMAIL_SEND_EMAIL"}
        )

    async def test_a_committed_approve_is_one_exact_decision(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(created_at=None)

        outcome = await decide_ledger("ap_1", user_id="u1", kind="approve")

        assert outcome == LedgerDecision(
            committed=True,
            approval_id="ap_1",
            prior_state=LedgerState.PENDING,
            state=LedgerState.APPROVED,
        )
        seams.repo.get_by_approval_id.assert_any_await("ap_1")
        seams.log.set.assert_any_call(
            hil={"approval_id": "ap_1", "decision": "approve", "tool": "GMAIL_SEND_EMAIL"}
        )
        assert seams.capture.call_args.args[2]["card_age_seconds"] is None
        seams.settle_frame.assert_called_once_with("stream-1", "ap_1", "approved", None)
        stalled_cutoff, conversation = seams.repo.list_stalled_executing.await_args.args
        assert conversation == "conv-1"
        expected = datetime.now(UTC) - timedelta(minutes=STALLED_EXECUTING_MINUTES)
        assert abs(stalled_cutoff - expected) < timedelta(seconds=5)

    async def test_the_ticket_names_its_age_and_the_redeem_call(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(created_at=datetime.now(UTC) - timedelta(hours=2, minutes=5))

        await decide_ledger("ap_1", user_id="u1", kind="approve")

        seams.deliver.assert_awaited_once_with(
            "conv-1",
            AuthenticatedUser(user_id="u1"),
            "APPROVAL_READY ap_1: the user approved Send it (2h5m old). Run it now with "
            'execute(tool_name="approve", data={"id": "ap_1"}) and continue with its result. '
            "If it is no longer needed, say so instead of running it.",
        )
        seams.lock_holder.assert_awaited_once_with("conv-1")

    async def test_a_ticket_with_no_birth_time_says_so(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(created_at=None)

        await decide_ledger("ap_1", user_id="u1", kind="approve")

        assert "Send it (unknown age)." in seams.deliver.await_args.args[2]

    async def test_a_failed_ticket_delivery_is_reported_and_wakes_the_inbox(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc()
        seams.deliver.side_effect = RuntimeError("redis down")

        await decide_ledger("ap_1", user_id="u1", kind="approve")

        errors = _warned(seams.log.error)
        assert errors[
            f"{LogTag.HIL} Ledger ticket delivery failed; falling back to inbox wake"
        ] == {
            "approval_id": "ap_1",
            "error_type": "RuntimeError",
        }
        assert _inbox_lines(seams) == [
            ("conv-1", "DECISIONS: ap_1=APPROVED Send it", AgentTag.HIL_DECISION)
        ]

    async def test_a_deny_settles_the_card_and_tells_the_agent_why(
        self, seams: LedgerSeams
    ) -> None:
        row = _doc()
        seams.rows["ap_1"] = row

        await decide_ledger("ap_1", user_id="u1", kind="deny", feedback="nope")

        seams.deliver.assert_awaited_once_with(
            "conv-1",
            AuthenticatedUser(user_id="u1"),
            f"DECISION ap_1=DENIED Send it :: nope{_DENY_TAIL}",
        )
        seams.record_deny.assert_awaited_once_with(row, "nope")
        seams.lock_holder.assert_awaited_once_with("conv-1")
        seams.settle_frame.assert_called_once_with("stream-1", "ap_1", "denied", "nope")
        seams.persist.assert_awaited_once_with(
            "conv-1", user_id="u1", approval_id="ap_1", status="denied"
        )

    async def test_a_bare_deny_carries_no_preview(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        await decide_ledger("ap_1", user_id="u1", kind="deny")

        assert seams.deliver.await_args.args[2] == f"DECISION ap_1=DENIED Send it{_DENY_TAIL}"

    async def test_a_long_deny_reason_is_clipped_for_the_agent(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        await decide_ledger("ap_1", user_id="u1", kind="deny", feedback="n" * 600)

        assert seams.deliver.await_args.args[2] == (
            f"DECISION ap_1=DENIED Send it :: {'n' * 500}{_DENY_TAIL}"
        )

    async def test_a_failed_verdict_delivery_is_reported_and_wakes_the_inbox(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc()
        seams.deliver.side_effect = RuntimeError("redis down")

        await decide_ledger("ap_1", user_id="u1", kind="deny", feedback="nope")

        errors = _warned(seams.log.error)
        assert errors[
            f"{LogTag.HIL} Ledger verdict delivery failed; falling back to inbox wake"
        ] == {
            "approval_id": "ap_1",
            "outcome": "DENIED",
            "error_type": "RuntimeError",
        }
        assert _inbox_lines(seams) == [
            ("conv-1", "DECISIONS: ap_1=DENIED Send it :: nope", AgentTag.HIL_DECISION)
        ]

    async def test_a_queued_approve_names_its_blockers_in_the_wake(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["ap_a", "ap_b"])

        outcome = await decide_ledger("ap_1", user_id="u1", kind="approve")

        assert outcome.queued is True
        assert _inbox_lines(seams) == [
            (
                "conv-1",
                "DECISIONS: ap_1=QUEUED Send it :: waiting on ap_a,ap_b",
                AgentTag.HIL_DECISION,
            )
        ]
        seams.deliver.assert_not_awaited()


@pytest.mark.unit
class TestPublishLedgerDecision:
    """A committed decision settles the card on the proposing stream, the saved turn, and every client."""

    @pytest.mark.parametrize(
        ("state", "status"),
        [(LedgerState.APPROVED, "approved"), (LedgerState.DENIED, "denied")],
    )
    async def test_the_settled_card_reaches_every_surface(
        self, seams: LedgerSeams, state: LedgerState, status: str
    ) -> None:
        row = _doc(feedback="stored words")

        await publish_ledger_decision(row, state)

        stream_id, entry = seams.publish_entry.await_args.args
        assert stream_id == "stream-1"
        assert entry.data.approval_id == "ap_1"
        assert entry.data.gated_tool_name == "GMAIL_SEND_EMAIL"
        assert entry.data.tool_call_id == ""
        assert entry.data.args_preview == {"to": "b@x"}
        assert entry.data.status == status
        assert entry.data.summary == "Send it"
        assert entry.data.integration_name is None
        assert entry.data.feedback == "stored words"
        seams.settle_frame.assert_called_once_with("stream-1", "ap_1", status, "stored words")
        seams.persist.assert_awaited_once_with(
            "conv-1", user_id="u1", approval_id="ap_1", status=status
        )
        seams.broadcast.assert_awaited_once_with(
            user_id="u1",
            message={
                "type": "hil_approval_decided",
                "data": {
                    "conversation_id": "conv-1",
                    "approval_id": "ap_1",
                    "status": status,
                    "feedback": "stored words",
                    "version": 4,
                },
            },
        )

    async def test_fresh_feedback_wins_over_the_stored_words(self, seams: LedgerSeams) -> None:
        await publish_ledger_decision(_doc(feedback="old"), LedgerState.DENIED, feedback="new")

        assert seams.publish_entry.await_args.args[1].data.feedback == "new"
        assert seams.settle_frame.call_args.args[3] == "new"
        assert seams.broadcast.await_args.kwargs["message"]["data"]["feedback"] == "new"

    async def test_no_proposing_stream_skips_the_live_card(self, seams: LedgerSeams) -> None:
        await publish_ledger_decision(_doc(proposing_run_id=None), LedgerState.APPROVED)

        seams.publish_entry.assert_not_awaited()
        seams.settle_frame.assert_not_called()
        seams.persist.assert_awaited_once()

    async def test_a_missed_stream_is_reported_and_the_rest_still_settles(
        self, seams: LedgerSeams
    ) -> None:
        seams.publish_entry.side_effect = RuntimeError("redis down")

        await publish_ledger_decision(_doc(), LedgerState.APPROVED)

        assert _warned(seams.log.warning) == {
            f"{LogTag.HIL} Ledger decision frame missed its stream": {
                "approval_id": "ap_1",
                "error_type": "RuntimeError",
            }
        }
        seams.settle_frame.assert_called_once()
        seams.broadcast.assert_awaited_once()

    async def test_persist_and_broadcast_failures_are_reported_not_raised(
        self, seams: LedgerSeams
    ) -> None:
        seams.persist.side_effect = RuntimeError("mongo down")
        seams.broadcast.side_effect = ConnectionError("ws down")

        await publish_ledger_decision(_doc(), LedgerState.APPROVED)

        assert _warned(seams.log.warning) == {
            f"{LogTag.HIL} Ledger decision persist missed; live delivery already attempted": {
                "approval_id": "ap_1",
                "error_type": "RuntimeError",
            },
            f"{LogTag.HIL} Ledger decision broadcast missed": {
                "approval_id": "ap_1",
                "error_type": "ConnectionError",
            },
        }

    async def test_a_revocation_tombstones_everywhere(self, seams: LedgerSeams) -> None:
        await publish_ledger_revocation(_doc())

        seams.settle_frame.assert_called_once_with(
            "stream-1", "ap_1", "revoked", drop_if_unpublished=True
        )
        seams.persist.assert_awaited_once_with(
            "conv-1", user_id="u1", approval_id="ap_1", status="revoked"
        )
        message = seams.broadcast.await_args.kwargs["message"]
        assert (message["data"]["status"], message["data"]["feedback"]) == ("revoked", None)


@pytest.mark.unit
class TestTheInboxWake:
    async def test_no_redis_is_a_loud_drop(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["ap_a"])
        seams.redis.client = None

        await decide_ledger("ap_1", user_id="u1", kind="approve")

        seams.inbox.assert_not_called()
        errors = _warned(seams.log.error)
        assert errors[
            f"{LogTag.HIL} Ledger wake dropped: no Redis client; agent will not learn this outcome"
        ] == {"approval_id": "ap_1", "outcome": "QUEUED"}

    async def test_a_failed_append_is_reported(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["ap_a"])
        seams.inbox.return_value.append.side_effect = RuntimeError("redis down")

        await decide_ledger("ap_1", user_id="u1", kind="approve")

        errors = _warned(seams.log.error)
        assert errors[f"{LogTag.HIL} Ledger wake failed; outcome lives on the row only"] == {
            "approval_id": "ap_1",
            "outcome": "QUEUED",
            "error_type": "RuntimeError",
        }

    async def test_a_long_result_is_clipped_in_the_wake(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["x" * 600])

        await decide_ledger("ap_1", user_id="u1", kind="approve")

        text = _inbox_lines(seams)[0][1]
        assert text == f"DECISIONS: ap_1=QUEUED Send it :: {('waiting on ' + 'x' * 600)[:500]}"


@pytest.mark.unit
class TestDecideLedgerBatchOutcomes:
    async def test_every_item_is_decided_and_reported_on_its_own(self, seams: LedgerSeams) -> None:
        results: list[LedgerDecision | Exception] = [
            ApprovalRequestNotFoundError(),
            ApprovalRequestForbiddenError(),
            RuntimeError("mongo down"),
            LedgerDecision(True, "ap_4", LedgerState.PENDING, LedgerState.APPROVED),
            LedgerDecision(False, "ap_5", LedgerState.PENDING, LedgerState.PENDING, stale=True),
            LedgerDecision(False, "ap_6", LedgerState.PENDING, LedgerState.DENIED),
        ]
        items = [
            BatchDecisionItem(
                approval_id=f"ap_{i}",
                decision="approve" if i % 2 else "deny",
                feedback=f"f{i}",
                v=i,
            )
            for i in range(1, 7)
        ]
        with patch(f"{MODULE}.decide_ledger", new=AsyncMock(side_effect=results)) as decide:
            outcomes = await decide_ledger_batch("u1", items)

        assert [c.args for c in decide.await_args_list] == [(f"ap_{i}",) for i in range(1, 7)]
        assert [c.kwargs for c in decide.await_args_list] == [
            {"user_id": "u1", "kind": item.decision, "feedback": item.feedback, "v": item.v}
            for item in items
        ]
        assert outcomes == [
            BatchDecisionOutcome(approval_id="ap_1", resolved=False, reason="not_found"),
            BatchDecisionOutcome(approval_id="ap_2", resolved=False, reason="forbidden"),
            BatchDecisionOutcome(approval_id="ap_3", resolved=False, reason="error"),
            BatchDecisionOutcome(approval_id="ap_4", resolved=True),
            BatchDecisionOutcome(
                approval_id="ap_5", resolved=False, reason="stale", status="pending"
            ),
            BatchDecisionOutcome(
                approval_id="ap_6", resolved=False, reason="not_found", status="denied"
            ),
        ]
        assert _warned(seams.log.error) == {
            f"{LogTag.HIL} Ledger batch decision failed for": {
                "approval_id": "ap_3",
                "error": "mongo down",
                "error_type": "RuntimeError",
                "user_id": "u1",
            }
        }


@pytest.mark.unit
class TestReclaimDeadHolderEdges:
    async def test_the_lock_is_read_for_this_conversation(self, seams: LedgerSeams) -> None:
        await _reclaim_dead_holder("conv-1")

        seams.lock_holder.assert_awaited_once_with("conv-1")

    async def test_only_the_holders_own_live_session_holds_the_lock(
        self, seams: LedgerSeams
    ) -> None:
        seams.lock_holder.return_value = "s1:t1"
        seams.get_session.side_effect = lambda stream: MagicMock() if stream == "s1" else None

        assert await _reclaim_dead_holder("conv-1") is False
        seams.break_lock.assert_not_awaited()

    async def test_no_redis_client_means_free(self, seams: LedgerSeams) -> None:
        seams.lock_holder.return_value = "s1:t1"
        seams.redis.client = None

        assert await _reclaim_dead_holder("conv-1") is True
        seams.break_lock.assert_not_awaited()

    @pytest.mark.parametrize("ttl", [None, -1], ids=["gone", "no-expiry"])
    async def test_a_lock_without_a_live_ttl_is_free(
        self, seams: LedgerSeams, ttl: int | None
    ) -> None:
        seams.lock_holder.return_value = "s1:t1"
        seams.redis.client.ttl.return_value = ttl

        assert await _reclaim_dead_holder("conv-1") is True
        seams.break_lock.assert_not_awaited()
        seams.redis.client.ttl.assert_awaited_once_with(f"{EXECUTOR_BUSY_PREFIX}conv-1")

    @pytest.mark.parametrize(
        "ttl",
        [0, EXECUTOR_BUSY_TTL - STALE_HOLDER_MIN_AGE_SECONDS],
        ids=["expiring-now", "exactly-min-age"],
    )
    async def test_an_old_enough_lock_is_broken(self, seams: LedgerSeams, ttl: int) -> None:
        seams.lock_holder.return_value = "s1:t1"
        seams.redis.client.ttl.return_value = ttl

        assert await _reclaim_dead_holder("conv-1") is True
        seams.break_lock.assert_awaited_once_with("conv-1", "s1:t1")
        seams.barrier_pending.assert_awaited_once_with("conv-1")

    async def test_a_young_lock_holds(self, seams: LedgerSeams) -> None:
        seams.lock_holder.return_value = "s1:t1"
        seams.redis.client.ttl.return_value = EXECUTOR_BUSY_TTL - STALE_HOLDER_MIN_AGE_SECONDS + 1

        assert await _reclaim_dead_holder("conv-1") is False
        seams.break_lock.assert_not_awaited()

    async def test_a_failed_check_keeps_the_lock_and_says_so(self, seams: LedgerSeams) -> None:
        seams.lock_holder.side_effect = ConnectionError("redis down")

        assert await _reclaim_dead_holder("conv-1") is False
        assert _warned(seams.log.warning) == {
            f"{LogTag.HIL} Holder reclaim check failed; keeping the lock": {
                "conversation_id": "conv-1",
                "error_type": "ConnectionError",
            }
        }


@pytest.mark.unit
class TestRedeemOutcomes:
    async def _redeem(self, caller: str = "executor_conv-1") -> RedeemResult:
        return await redeem_approved("ap_1", user_id="u1", conversation_id="conv-1", caller=caller)

    async def test_an_already_settled_ticket_is_refused_with_its_state(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.EXECUTED)

        assert await self._redeem() == RedeemResult(
            ok=False,
            approval_id="ap_1",
            state=LedgerState.EXECUTED,
            detail="Already executed; report that instead of retrying.",
        )
        seams.repo.get_by_approval_id.assert_awaited_once_with("ap_1")

    async def test_the_proposing_worker_may_redeem_its_own_ticket(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)
        seams.dispatch.return_value = MagicMock(ok=True, output="sent", error=None)

        result = await self._redeem(caller="gmail_conv-1")

        assert result == RedeemResult(
            ok=True, approval_id="ap_1", state=LedgerState.EXECUTED, detail="sent"
        )
        seams.repo.claim_executing.assert_awaited_once_with("ap_1")
        seams.dispatch.assert_awaited_once_with(
            user_id="u1",
            tool_name="GMAIL_SEND_EMAIL",
            data={"to": "b@x"},
            config={"user": "u1"},
        )
        seams.settle_frame.assert_called_once_with("stream-1", "ap_1", "executed")

    async def test_another_worker_cannot_redeem(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)

        assert await self._redeem(caller="slack_conv-1") == RedeemResult(
            ok=False,
            approval_id="ap_1",
            state=LedgerState.APPROVED,
            detail="This ticket belongs to another worker; only its proposer or the executor may redeem it.",
        )
        seams.repo.claim_executing.assert_not_awaited()

    @pytest.mark.parametrize(
        ("current", "state"),
        [(LedgerState.EXECUTING, LedgerState.EXECUTING), (None, LedgerState.APPROVED)],
        ids=["another-redeemer", "row-vanished"],
    )
    async def test_a_lost_claim_reports_the_rows_state(
        self, seams: LedgerSeams, current: LedgerState | None, state: LedgerState
    ) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)

        async def _lose(_: str) -> bool:
            if current is None:
                seams.rows.pop("ap_1")
            else:
                seams.rows["ap_1"] = _doc(state=current)
            return False

        seams.repo.claim_executing.side_effect = _lose

        assert await self._redeem() == RedeemResult(
            ok=False,
            approval_id="ap_1",
            state=state,
            detail=f"Already {state.value}; report that instead of retrying.",
        )
        seams.dispatch.assert_not_awaited()

    async def test_an_ownerless_row_dispatches_with_no_user(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED, user_id="")
        seams.dispatch.return_value = MagicMock(ok=True, output="ok", error=None)

        await redeem_approved("ap_1", user_id="", conversation_id="conv-1", caller="executor_c")

        assert seams.dispatch.await_args.kwargs["user_id"] is None

    async def test_a_raised_dispatch_lands_unknown_and_says_why(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)
        seams.dispatch.side_effect = RuntimeError("socket closed")

        result = await self._redeem()

        assert result == RedeemResult(
            ok=False,
            approval_id="ap_1",
            state=LedgerState.UNKNOWN,
            detail="RuntimeError: socket closed",
        )
        assert _warned(seams.log.error)[
            f"{LogTag.HIL} Ticket redeem raised; reconciled as UNKNOWN, never retried"
        ] == {"approval_id": "ap_1", "error_type": "RuntimeError"}
        seams.sync_flag.assert_awaited_once_with("conv-1", "u1")

    async def test_a_provider_timeout_is_unknown_never_retried(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)
        error = MagicMock(kind=DispatchErrorKind.TIMEOUT, detail="slow")
        seams.dispatch.return_value = MagicMock(ok=False, output=None, error=error)

        result = await self._redeem()

        assert result.detail == "provider timed out; may or may not have run — never auto-retried"
        assert result.state is LedgerState.UNKNOWN

    async def test_a_failure_without_detail_still_has_words(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)
        seams.dispatch.return_value = MagicMock(ok=False, output=None, error=None)

        result = await self._redeem()

        assert (result.state, result.detail) == (LedgerState.FAILED, "unknown error")

    async def test_a_lost_receipt_reports_the_reconcilers_verdict(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)
        seams.dispatch.return_value = MagicMock(ok=True, output="sent", error=None)

        async def _reconciled(approval_id: str, *_: object, **__: object) -> bool:
            seams.rows[approval_id] = _doc(state=LedgerState.UNKNOWN)
            return False

        seams.repo.transition.side_effect = _reconciled

        result = await self._redeem()

        assert result == RedeemResult(
            ok=False,
            approval_id="ap_1",
            state=LedgerState.UNKNOWN,
            detail="Already unknown; report that instead of retrying.",
        )
        assert _warned(seams.log.error)[
            f"{LogTag.HIL} Ticket receipt lost its CAS; reporting actual state"
        ] == {"approval_id": "ap_1", "attempted": "executed", "actual": "unknown"}


@pytest.mark.unit
class TestRevokeMessages:
    async def _revoke(self, caller: str = "gmail_conv-1") -> str:
        return await revoke_ticket("ap_1", user_id="u1", conversation_id="conv-1", caller=caller)

    async def test_a_decided_row_cannot_be_revoked(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(state=LedgerState.APPROVED)

        assert await self._revoke() == (
            "Cannot revoke 'ap_1': already approved. Report that to the user instead of retrying."
        )
        seams.repo.get_by_approval_id.assert_awaited_once_with("ap_1")

    async def test_another_worker_cannot_revoke(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        assert await self._revoke(caller="slack_conv-1") == (
            "Cannot revoke 'ap_1': it belongs to another worker. "
            "Only its proposer or the executor can withdraw it."
        )

    @pytest.mark.parametrize(
        ("current", "said"),
        [(LedgerState.APPROVED, "approved"), (None, "gone")],
        ids=["decided-meanwhile", "row-vanished"],
    )
    async def test_a_lost_revoke_race_says_what_happened(
        self, seams: LedgerSeams, current: LedgerState | None, said: str
    ) -> None:
        seams.rows["ap_1"] = _doc()

        async def _lose(*_: object, **__: object) -> bool:
            if current is None:
                seams.rows.pop("ap_1")
            else:
                seams.rows["ap_1"] = _doc(state=current)
            return False

        seams.repo.transition.side_effect = _lose

        assert await self._revoke() == f"Cannot revoke 'ap_1': already {said}."

    async def test_a_revoke_tombstones_the_card_it_withdrew(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        async def _revoked(approval_id: str, *_: object, **__: object) -> bool:
            seams.rows[approval_id] = _doc(state=LedgerState.REVOKED, proposing_run_id="stream-9")
            return True

        seams.repo.transition.side_effect = _revoked

        await self._revoke()

        seams.settle_frame.assert_called_once_with(
            "stream-9", "ap_1", "revoked", drop_if_unpublished=True
        )


@pytest.mark.unit
class TestCancelLedgerApprovalsSweep:
    async def test_only_the_users_pending_rows_are_withdrawn_and_each_is_counted(
        self, seams: LedgerSeams
    ) -> None:
        rows = [
            _doc(approval_id="ap_ok", state=LedgerState.APPROVED),
            _doc(approval_id="ap_other", user_id="u2"),
            _doc(approval_id="ap_lost"),
            _doc(approval_id="ap_1", v=7),
        ]
        seams.repo.list_open.return_value = rows
        seams.rows["ap_1"] = _doc(v=8, state=LedgerState.REVOKED, proposing_run_id="stream-2")
        seams.repo.transition.side_effect = lambda approval_id, *_: approval_id == "ap_1"

        cancelled = await cancel_ledger_approvals("conv-1", "u1")

        assert cancelled == ["ap_1"]
        seams.repo.list_open.assert_awaited_once_with("conv-1")
        seams.settle_frame.assert_called_once_with(
            "stream-2", "ap_1", "revoked", drop_if_unpublished=True
        )
        seams.capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.HIL_REVOKED,
            {"approval_id": "ap_1", "ledger_version": 8, "revoker": "cancelled-run"},
        )
        seams.sync_flag.assert_awaited_once_with("conv-1", "u1")


@pytest.mark.unit
class TestReconcileStalled:
    async def test_a_stalled_row_goes_unknown_settles_and_wakes_with_a_warning(
        self, seams: LedgerSeams
    ) -> None:
        stalled = _doc(state=LedgerState.EXECUTING, user_id="u9", proposing_run_id="stream-3")
        seams.repo.list_stalled_executing.return_value = [stalled]

        await reconcile_conversation_ledger("conv-1")

        cutoff = seams.repo.list_stalled_executing.await_args.args[0]
        assert cutoff.tzinfo is UTC
        assert _warned(seams.log.error) == {
            f"{LogTag.HIL} Ledger execution stalled; reconciled as UNKNOWN, never retried": {
                "approval_id": "ap_1"
            }
        }
        seams.settle_frame.assert_called_once_with("stream-3", "ap_1", "unknown")
        assert _inbox_lines(seams) == [
            (
                "conv-1",
                "DECISIONS: ap_1=UNKNOWN Send it :: stalled execution reconciled; never "
                "retried. The action may or may not have run — verify before re-proposing, "
                "never blind-retry.",
                AgentTag.HIL_DECISION,
            )
        ]
        seams.sync_flag.assert_awaited_once_with("conv-1", "u9")
