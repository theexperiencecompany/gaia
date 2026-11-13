"""Ledger decide: CAS commit, stale-v refresh, queued approvals, no execution yet."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_queue import hold_run_alive
from app.constants.agents import AgentTag
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.log_tags import LogTag
from app.models.execute_models import DispatchError, DispatchErrorKind
from app.models.hil_models import ApprovalLedgerDocument
from app.models.user_models import AuthenticatedUser
from app.schemas.hil_schemas import ApprovalDecisionRequest, BatchDecisionItem, BatchDecisionOutcome
from app.services.hil import ledger_decide, resolution
from app.services.hil.bridge import CardEnd
from app.services.hil.ledger_decide import (
    STALLED_EXECUTING_MINUTES,
    LedgerDecision,
    RedeemResult,
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
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import (
    ActionResult,
    ApprovalDecider,
    ApprovalOutcome,
    HilDecisionSubmitted,
    HilRevoked,
)
from tests.helpers import ledger_facts

from .conftest import tools_that_always_ask

MODULE = "app.services.hil.ledger_decide"
RUNNER = "app.agents.core.background.executor_runner"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
OTHER_USER_ID = "6812f0b3c9a14e2b7d5a91c2"
THIRD_USER_ID = "6812f0b3c9a14e2b7d5a91c9"
# The executor run a ticket is redeemed on.
RUN_CONFIG: RunnableConfig = {
    "configurable": {
        "thread_id": "executor_conv-1",
        "user_id": USER_ID,
        "conversation_id": "conv-1",
    }
}


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock()
    row.approval_id = "ap_abc"
    row.conversation_id = "conv-1"
    row.user_id = USER_ID
    row.tool_name = "GMAIL_SEND_EMAIL"
    row.tool_key = "GMAIL_SEND_EMAIL"
    row.args = {"to": "b@x"}
    row.summary = "Send it"
    row.outcome = None
    row.action = None
    row.v = 3
    row.blocked_by = []
    row.decided_at = None
    row.feedback = None
    row.owner_run_type = ""
    row.owner_id = ""
    row.task_id = None
    # Real datetime: the decision path computes card age from it, and a
    # MagicMock would TypeError on the subtraction, hiding real type errors.
    row.created_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(row, key, value)
    # The row's derived reads, from its own outcome and action (a MagicMock has its own class).
    type(row).standing = ApprovalLedgerDocument.standing
    type(row).live = ApprovalLedgerDocument.live
    return row


def _repo(row: Any = None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_approval_id = AsyncMock(return_value=row)
    repo.settle = AsyncMock(return_value=True)
    repo.finish_action = AsyncMock(return_value=True)
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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.outcome == ApprovalOutcome.APPROVED
        assert outcome.queued is False
        repo.settle.assert_awaited_once_with(
            "ap_abc",
            ApprovalOutcome.APPROVED,
            decided_by=USER_ID,
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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is True
        wake.assert_awaited_once_with(repo.get_by_approval_id.return_value, "APPROVED", None)

    async def test_stale_v_returns_current_row_without_writing(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None, v=4))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is False
        assert outcome.outcome == ApprovalOutcome.APPROVED
        repo.settle.assert_not_awaited()
        deliver.assert_not_awaited()

    async def test_deny_commits_without_delivery(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
            patch(f"{MODULE}._deliver_verdict", new=AsyncMock()),
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="deny", feedback="nope", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.outcome == ApprovalOutcome.DENIED
        repo.settle.assert_awaited_once_with(
            "ap_abc",
            ApprovalOutcome.DENIED,
            decided_by=USER_ID,
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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.queued is True
        deliver.assert_not_awaited()

    async def test_stale_v_marks_stale_not_gone(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None, v=4))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()),
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is False
        assert outcome.stale is True
        assert outcome.outcome == "approved"

    async def test_unknown_id_raises_not_found(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger
        from app.services.hil.resolution import ApprovalRequestNotFoundError

        with (
            patch(f"{MODULE}.approval_ledger_repository", new=_repo(None)),
            pytest.raises(ApprovalRequestNotFoundError),
        ):
            await decide_ledger("ap_nope", user_id=USER_ID, kind="approve", v=None, via="card")


@pytest.mark.unit
@pytest.mark.parametrize(("task_id", "logged"), [("t1", True), (None, False)])
async def test_a_decision_on_step_logged_work_is_appended_to_the_conversation_log(
    task_id: str | None, logged: bool
) -> None:
    with (
        patch.object(ledger_decide, "approval_ledger_repository", new=_repo(_row(task_id=task_id))),
        patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
        patch.object(ledger_decide, "_deliver_verdict", new=AsyncMock()),
        patch.object(ledger_decide, "record_approval_decided", new=AsyncMock()) as decided,
    ):
        await ledger_decide.decide_ledger("ap_abc", user_id=USER_ID, kind="deny", v=3, via="card")
    if logged:
        decided.assert_awaited_once_with(
            "conv-1", USER_ID, "ap_abc", ApprovalOutcome.DENIED, ApprovalDecider.USER
        )
    else:
        decided.assert_not_awaited()


@pytest.mark.unit
class TestDecisionSubmittedEvent:
    async def test_approve_emits_event_with_user_id(self) -> None:
        """Same attribution rule as revoke: the decide path resolves its user from the row, so the event must carry that id explicitly."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is True
        capture.assert_called_once()
        user_id, event = capture.call_args.args
        assert user_id == UserId(USER_ID)
        assert isinstance(event, HilDecisionSubmitted)
        assert event.approval_id == "ap_abc"
        assert event.outcome == "approved"
        assert event.ledger_version == 4
        assert event.card_age_seconds is not None
        assert event.card_age_seconds < 60

    @pytest.mark.regression
    async def test_the_decision_names_its_tool_and_where_it_was_made(self) -> None:
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=_repo(_row())),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            await decide_ledger("ap_abc", user_id=USER_ID, kind="approve", v=3, via="chat")

        event = capture.call_args.args[1]
        assert (event.tool_name, event.via) == ("GMAIL_SEND_EMAIL", "chat")

    @pytest.mark.regression
    async def test_a_batch_review_decision_is_marked_as_the_batch(self) -> None:
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=_repo(_row())),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            await decide_ledger_batch(
                USER_ID,
                [BatchDecisionItem(approval_id="ap_abc", decision="approve", feedback=None, v=3)],
            )

        assert capture.call_args.args[1].via == "batch"

    async def test_deny_emits_deny_decision(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_verdict", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            await decide_ledger("ap_abc", user_id=USER_ID, kind="deny", v=3, via="card")

        assert isinstance(capture.call_args.args[1], HilDecisionSubmitted)
        assert capture.call_args.args[1].outcome == "denied"

    async def test_uncommitted_decisions_emit_nothing(self) -> None:
        """Stale-v and lost-CAS returns decided nothing — an event would count attempts as successes."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import decide_ledger

        stale_repo = _repo(_row())
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=stale_repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=99, via="card"
            )

        assert outcome.committed is False
        capture.assert_not_called()

        lost_repo = _repo(_row())
        lost_repo.settle = AsyncMock(return_value=False)
        lost_repo.finish_action = AsyncMock(return_value=False)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=lost_repo),
            patch.object(ledger_decide, "publish_ledger_decision", new=AsyncMock()),
            patch.object(ledger_decide, "_deliver_ticket", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is False
        capture.assert_not_called()


@pytest.mark.unit
class TestConversationFlagSync:
    async def test_empty_owner_never_matches_any_user(self) -> None:
        from app.services.hil.ledger_decide import decide_ledger
        from app.services.hil.resolution import ApprovalRequestForbiddenError

        repo = _repo(_row(user_id=""))
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            pytest.raises(ApprovalRequestForbiddenError),
        ):
            await decide_ledger("ap_abc", user_id=USER_ID, kind="approve", v=None, via="card")

        repo.settle.assert_not_awaited()

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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="deny", feedback="nope", v=3, via="card"
            )

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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.queued is True
        deliver.assert_not_awaited()
        wake.assert_awaited_once_with(row, "QUEUED", "waiting on ap_dep")

    async def test_reconcile_heals_stalled_only(self) -> None:
        """Orphaned APPROVED rows are left alone: the ticket lives in model context and only a redeem runs the envelope — never re-nudge."""
        from app.services.hil.ledger_decide import reconcile_conversation_ledger

        stalled = _row(approval_id="ap_old")
        stalled.outcome = ApprovalOutcome.APPROVED
        stalled.action = ActionResult.EXECUTING
        orphan = _row(approval_id="ap_orphan")
        orphan.outcome = ApprovalOutcome.APPROVED
        orphan.action = None
        orphan.blocked_by = []
        repo = _repo()
        repo.list_stalled_executing = AsyncMock(return_value=[stalled])
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
            patch(f"{MODULE}._wake_agent", new=AsyncMock()) as wake,
        ):
            await reconcile_conversation_ledger("conv-1")

        repo.finish_action.assert_awaited_once_with("ap_old", ActionResult.UNKNOWN)
        deliver.assert_not_awaited()
        assert wake.await_count == 1

    async def test_reconcile_scopes_stalled_scan_to_conversation(self) -> None:
        # The stalled scan must not read every conversation's stalls on each
        # tap: scope rides in the query, not a Python-side discard.
        from app.services.hil.ledger_decide import reconcile_conversation_ledger

        repo = _repo()
        repo.list_stalled_executing = AsyncMock(return_value=[])
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()) as deliver,
        ):
            await reconcile_conversation_ledger("conv-1")

        repo.list_stalled_executing.assert_awaited_once()
        assert repo.list_stalled_executing.await_args.args[1] == "conv-1"
        repo.settle.assert_not_awaited()
        deliver.assert_not_awaited()


@pytest.mark.unit
class TestRedeemExecution:
    def _redeem_repo(self) -> MagicMock:
        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        return repo

    def _redeem_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": USER_ID,
            "conversation_id": "conv-1",
            "caller": "executor_conv-1",
            "run_config": RUN_CONFIG,
        }

    async def test_provider_timeout_lands_unknown_never_failed(self) -> None:
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

        repo.finish_action.assert_awaited_once_with("ap_abc", ActionResult.UNKNOWN)
        assert result.ok is False
        assert result.action == ActionResult.UNKNOWN
        assert "never auto-retried" in result.detail

    async def test_redeem_failed_transition_still_returns_state(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        ok_result = MagicMock(ok=True, output="sent", error=None)
        repo = self._redeem_repo()
        repo.settle = AsyncMock(return_value=False)
        repo.finish_action = AsyncMock(return_value=False)
        reconciled = _row()
        reconciled.outcome = ApprovalOutcome.APPROVED
        reconciled.action = ActionResult.UNKNOWN
        approved = _row()
        approved.outcome = ApprovalOutcome.APPROVED
        approved.action = None
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

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        config = dispatch.await_args.kwargs["config"]
        assert config["configurable"]["user_id"] == USER_ID
        assert config["metadata"]["user_id"] == USER_ID

    @pytest.mark.regression
    async def test_redeem_runs_the_envelope_on_the_redeeming_run(self) -> None:
        """Regression: a rebuilt bare config dropped the run's stream writer, stream and surface."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        run_config: RunnableConfig = {
            "configurable": {
                "thread_id": "executor_conv-1",
                "user_id": USER_ID,
                "conversation_id": "conv-1",
                "stream_id": "stream-1",
                "source_category": "ui",
            },
            "metadata": {"source": "chat"},
            "tags": ["executor"],
        }
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=run_config,
            )

        assert dispatch.await_args.kwargs["config"] == {
            "configurable": run_config["configurable"],
            "metadata": {"source": "chat", "user_id": USER_ID},
            "tags": ["executor"],
        }
        assert run_config["metadata"] == {"source": "chat"}


@pytest.mark.unit
class TestRedeemTerminalStates:
    async def test_executed_returns_output(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
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
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        repo.finish_action.assert_awaited_once_with("ap_abc", ActionResult.EXECUTED)
        assert result.ok is True
        assert result.action == ActionResult.EXECUTED
        assert "deleted xyz" in result.detail

    async def test_failed_returns_error_detail(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        failed = MagicMock(
            ok=False,
            output=None,
            error=DispatchError(kind=DispatchErrorKind.INVALID_ARGS, detail="bad date", hint="x"),
        )
        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=failed)),
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        repo.finish_action.assert_awaited_once_with("ap_abc", ActionResult.FAILED)
        assert result.ok is False
        assert result.action == ActionResult.FAILED
        assert "bad date" in result.detail

    async def test_raised_execution_returns_unknown_with_cause(self) -> None:
        """An infra raise must still tell the caller what happened: UNKNOWN with the cause, never a silent row flip."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
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
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        repo.finish_action.assert_awaited_once_with("ap_abc", ActionResult.UNKNOWN)
        assert result.ok is False
        assert result.action == ActionResult.UNKNOWN
        assert "No connected accounts" in result.detail


@pytest.mark.unit
class TestRevokeTicket:
    def _revoke_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": USER_ID,
            "conversation_id": "conv-1",
            "caller": "executor_conv-1",
        }

    async def test_revoke_tombstones_pending_row(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row())
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            text = await revoke_ticket("ap_abc", **self._revoke_kwargs())

        repo.settle.assert_awaited_once_with("ap_abc", ApprovalOutcome.WITHDRAWN)
        tombstone.assert_awaited_once()
        assert "Revoked 'ap_abc'" in text

    async def test_revoke_emits_event_with_user_id(self) -> None:
        """The revoke event must attribute to the row's user — an anonymous capture would strand it outside the user's funnel, silently."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row())
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()),
            patch.object(ledger_decide, "capture") as capture,
        ):
            await revoke_ticket("ap_abc", **self._revoke_kwargs())

        capture.assert_called_once_with(
            UserId(USER_ID),
            HilRevoked(
                approval_id="ap_abc",
                ledger_version=4,
                revoker="executor_conv-1",
                outcome=ApprovalOutcome.WITHDRAWN,
            ),
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
                user_id=USER_ID,
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
        repo.settle.assert_not_awaited()
        tombstone.assert_not_awaited()

    async def test_revoke_decided_row_refused(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import revoke_ticket

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
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
                user_id=USER_ID,
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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

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
            await decide_ledger("ap_abc", user_id=USER_ID, kind="approve", v=3, via="card")

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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="deny", feedback="nope", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.outcome == ApprovalOutcome.DENIED
        resume.assert_not_called()
        record.assert_awaited_once()

    async def test_redeem_runs_stored_envelope_and_returns_output(self) -> None:
        """The model supplies no args: the ticket IS the approval_id and the envelope runs verbatim."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="deleted xyz", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        dispatch.assert_awaited_once()
        assert dispatch.await_args.kwargs["data"] == {"to": "b@x"}
        assert result.ok is True
        assert "deleted xyz" in result.detail

    async def test_double_redeem_runs_envelope_once(self) -> None:
        """The claim is the single-use CAS: loser is refused, never re-run."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        repo.claim_executing = AsyncMock(side_effect=[True, False])
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(
                ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)
            ) as dispatch,
        ):
            first = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )
            second = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        assert first.ok is True
        assert first.action == ActionResult.EXECUTED
        assert second.ok is False
        dispatch.assert_awaited_once()

    async def test_redeem_wrong_conversation_looks_absent(self) -> None:
        """No existence leak across conversations — mirrors revoke_tool."""
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved
        from app.services.hil.resolution import ApprovalRequestNotFoundError

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None))
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock()) as dispatch,
            pytest.raises(ApprovalRequestNotFoundError),
        ):
            await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="other-conv",
                caller="executor_other-conv",
                run_config=RUN_CONFIG,
            )
        dispatch.assert_not_awaited()

    async def test_redeem_non_approved_row_refused(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=ActionResult.EXECUTED))
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock()) as dispatch,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
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
                "ap_abc", user_id=USER_ID, kind="approve", feedback="cc finance", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.outcome == ApprovalOutcome.DENIED
        repo.settle.assert_awaited_once_with(
            "ap_abc",
            ApprovalOutcome.DENIED,
            decided_by=USER_ID,
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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.outcome == ApprovalOutcome.APPROVED
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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

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
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="approve", v=3, via="card"
            )

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
            patch.object(ledger_decide, "_deliver_verdict", new=AsyncMock()),
        ):
            outcome = await decide_ledger(
                "ap_abc", user_id=USER_ID, kind="deny", feedback="nope", v=3, via="card"
            )

        assert outcome.committed is True
        assert outcome.outcome == ApprovalOutcome.DENIED


@pytest.mark.unit
class TestCancelLedgerApprovals:
    async def test_cancel_withdraws_user_pending_rows_only(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import cancel_ledger_approvals

        mine = _row(approval_id="ap_mine")
        approved = _row(approval_id="ap_ticket", outcome=ApprovalOutcome.APPROVED, action=None)
        foreign = _row(approval_id="ap_theirs", user_id=OTHER_USER_ID)
        repo = _repo()
        repo.list_open = AsyncMock(return_value=[mine, approved, foreign])
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        repo.get_by_approval_id = AsyncMock(return_value=mine)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            cancelled = await cancel_ledger_approvals(
                "conv-1", USER_ID, ["ap_mine", "ap_ticket", "ap_theirs"]
            )

        assert cancelled == ["ap_mine"]
        repo.settle.assert_awaited_once_with("ap_mine", ApprovalOutcome.CANCELLED)
        tombstone.assert_awaited_once()

    async def test_a_pending_row_the_cancel_does_not_name_stays_pending(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import cancel_ledger_approvals

        repo = _repo()
        repo.list_open = AsyncMock(return_value=[_row(approval_id="ap_later")])
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()),
        ):
            cancelled = await cancel_ledger_approvals("conv-1", USER_ID, ["ap_mine"])

        assert cancelled == []
        repo.settle.assert_not_awaited()

    async def test_cancel_lost_race_skips_quietly(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import cancel_ledger_approvals

        repo = _repo()
        repo.list_open = AsyncMock(return_value=[_row()])
        repo.settle = AsyncMock(return_value=False)
        repo.finish_action = AsyncMock(return_value=False)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "publish_ledger_revocation", new=AsyncMock()) as tombstone,
        ):
            cancelled = await cancel_ledger_approvals("conv-1", USER_ID, ["ap_abc"])

        assert cancelled == []
        tombstone.assert_not_awaited()


@pytest.mark.unit
class TestRevokeSettlesSessionFrame:
    async def test_revoke_flips_pending_frame_in_proposing_session(self) -> None:
        # BUG: revoke settled mongo but never touched the proposing
        # session's in-memory frame; the drain later persisted the stale PENDING
        # frame back over it (production ap_d455 stuck pending post-revoke).
        from app.agents.core.background.session import (
            RunKind,
            create_session,
            get_session,
            teardown_session,
        )
        from app.services.hil import ledger_decide
        from app.services.hil.bridge import _approval_entry, _publish_entry
        from app.services.hil.utils import GatedApproval, GatedCall

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
                            user_id=USER_ID,
                            conversation_id="conv-1",
                            tool_call=GatedCall(
                                name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}
                            ),
                            summary="Send it",
                            integration_name=None,
                        ),
                        None,
                    ),
                )
            row = _row(proposing_run_id=stream_id, outcome=ApprovalOutcome.WITHDRAWN, action=None)
            await ledger_decide.publish_ledger_revocation(row, ApprovalOutcome.WITHDRAWN)
            frames = get_session(stream_id).tool_events
            assert len(frames) == 1
            assert frames[0]["tool_data"]["data"]["outcome"] == "withdrawn"
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

        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None, task_id="t1"))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        ok_result = MagicMock(ok=True, output="sent", error=None)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=ok_result)),
            patch.object(ledger_decide, "record_approved_action_ended", new=AsyncMock()) as acted,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        assert result.ok is True
        assert result.action == ActionResult.EXECUTED
        acted.assert_awaited_once_with("conv-1", USER_ID, "ap_abc", ActionResult.EXECUTED)

    async def test_failed_settles_card_as_failed(self) -> None:
        from app.services.hil import ledger_decide
        from app.services.hil.ledger_decide import redeem_approved

        failed = MagicMock(
            ok=False,
            output=None,
            error=DispatchError(kind=DispatchErrorKind.INVALID_ARGS, detail="bad", hint="x"),
        )
        repo = _repo(_row(outcome=ApprovalOutcome.APPROVED, action=None, task_id="t1"))
        repo.claim_executing = AsyncMock(return_value=True)
        repo.settle = AsyncMock(return_value=True)
        repo.finish_action = AsyncMock(return_value=True)
        with (
            patch.object(ledger_decide, "approval_ledger_repository", new=repo),
            patch.object(ledger_decide, "dispatch_tool", new=AsyncMock(return_value=failed)),
            patch.object(ledger_decide, "record_approved_action_ended", new=AsyncMock()) as acted,
        ):
            result = await redeem_approved(
                "ap_abc",
                user_id=USER_ID,
                conversation_id="conv-1",
                caller="executor_conv-1",
                run_config=RUN_CONFIG,
            )

        assert result.ok is False
        # Approved, but it didn't go through: the card reads both facts, never a third status.
        acted.assert_awaited_once_with("conv-1", USER_ID, "ap_abc", ActionResult.FAILED)


def _doc(**overrides: Any) -> ApprovalLedgerDocument:
    fields: dict[str, Any] = {
        "approval_id": "ap_1",
        "conversation_id": "conv-1",
        "user_id": USER_ID,
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
    inbox: MagicMock
    redis: MagicMock
    resume_owner: AsyncMock
    record_deny: AsyncMock
    deliver: AsyncMock
    dispatch: AsyncMock


@pytest.fixture
def seams() -> Iterator[LedgerSeams]:
    rows: dict[str, ApprovalLedgerDocument] = {}

    async def _get(approval_id: str) -> ApprovalLedgerDocument | None:
        return rows.get(approval_id)

    repo = MagicMock()
    repo.get_by_approval_id = AsyncMock(side_effect=_get)
    repo.settle = AsyncMock(return_value=True)
    repo.finish_action = AsyncMock(return_value=True)
    repo.claim_executing = AsyncMock(return_value=True)
    repo.list_open = AsyncMock(return_value=[])
    repo.list_stalled_executing = AsyncMock(return_value=[])
    inbox = MagicMock()
    inbox.return_value.append = AsyncMock()
    redis = MagicMock()
    with (
        patch(f"{MODULE}.approval_ledger_repository", new=repo),
        patch(f"{MODULE}.capture") as capture,
        patch(f"{MODULE}.log") as log,
        patch(f"{MODULE}._publish_entry", new=AsyncMock()) as publish_entry,
        patch(f"{MODULE}.settle_session_approval_frame") as settle_frame,
        patch(f"{MODULE}.ExecutorInbox", new=inbox),
        patch(f"{MODULE}.redis_cache", new=redis),
        patch(f"{MODULE}.resume_owner_after_approval", new=AsyncMock()) as resume_owner,
        patch(f"{MODULE}.record_owner_deny", new=AsyncMock()) as record_deny,
        patch(f"{RUNNER}.deliver_to_executor", new=AsyncMock()) as deliver,
        patch(f"{MODULE}.dispatch_tool", new=AsyncMock()) as dispatch,
        patch(f"{MODULE}.dispatch_config_for", side_effect=lambda uid, _run_config: {"user": uid}),
    ):
        yield LedgerSeams(
            rows=rows,
            repo=repo,
            capture=capture,
            log=log,
            publish_entry=publish_entry,
            settle_frame=settle_frame,
            inbox=inbox,
            redis=redis,
            resume_owner=resume_owner,
            record_deny=record_deny,
            deliver=deliver,
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


def _warned(log_level: MagicMock) -> dict[str, Mapping[str, object]]:
    return {c.args[0]: c.kwargs for c in log_level.call_args_list}


_DENY_TAIL = (
    " The user said no — report what you skipped and continue without it. Do not re-request it."
)


@pytest.mark.unit
class TestDecideLedgerOutcomes:
    async def test_a_stale_version_refreshes_without_writing(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=None, action=None, v=4)

        outcome = await decide_ledger("ap_1", user_id=USER_ID, kind="approve", v=3, via="card")

        assert outcome == LedgerDecision(
            committed=False,
            approval_id="ap_1",
            outcome=None,
            action=None,
            stale=True,
        )
        seams.repo.settle.assert_not_awaited()

    @pytest.mark.parametrize(
        ("current", "state"),
        [(ApprovalOutcome.DENIED, ApprovalOutcome.DENIED), (None, None)],
        ids=["someone-else-won", "row-vanished"],
    )
    async def test_a_lost_race_reports_what_the_row_says_now(
        self,
        seams: LedgerSeams,
        current: ApprovalOutcome | ActionResult | None,
        state: ApprovalOutcome | ActionResult | None,
    ) -> None:
        seams.rows["ap_1"] = _doc()

        async def _lose(*_: object, **__: object) -> bool:
            if current is None:
                seams.rows.pop("ap_1")
            else:
                seams.rows["ap_1"] = _doc(**ledger_facts(current))
            return False

        seams.repo.settle.side_effect = _lose

        outcome = await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        assert outcome == LedgerDecision(committed=False, approval_id="ap_1", **ledger_facts(state))
        seams.capture.assert_not_called()

    async def test_whitespace_feedback_is_no_condition(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        outcome = await decide_ledger(
            "ap_1", user_id=USER_ID, kind="approve", feedback="   ", via="card"
        )

        assert outcome.outcome is ApprovalOutcome.APPROVED

    async def test_a_conditional_approve_is_recorded_as_a_deny(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        await decide_ledger(
            "ap_1", user_id=USER_ID, kind="approve", feedback="cc finance", via="card"
        )

        seams.log.set.assert_any_call(
            hil={"approval_id": "ap_1", "decision": "deny", "tool": "GMAIL_SEND_EMAIL"}
        )

    async def test_a_committed_approve_is_one_exact_decision(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(created_at=None)

        outcome = await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        assert outcome == LedgerDecision(
            committed=True,
            approval_id="ap_1",
            outcome=ApprovalOutcome.APPROVED,
            action=None,
        )
        seams.repo.get_by_approval_id.assert_any_await("ap_1")
        seams.log.set.assert_any_call(
            hil={"approval_id": "ap_1", "decision": "approve", "tool": "GMAIL_SEND_EMAIL"}
        )
        assert seams.capture.call_args.args[1].card_age_seconds is None
        seams.settle_frame.assert_called_once_with(
            "stream-1",
            "ap_1",
            CardEnd(ApprovalOutcome.APPROVED, decider=ApprovalDecider.USER, feedback=None),
        )
        stalled_cutoff, conversation = seams.repo.list_stalled_executing.await_args.args
        assert conversation == "conv-1"
        expected = datetime.now(UTC) - timedelta(minutes=STALLED_EXECUTING_MINUTES)
        assert abs(stalled_cutoff - expected) < timedelta(seconds=5)

    async def test_the_ticket_names_its_age_and_the_redeem_call(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(created_at=datetime.now(UTC) - timedelta(hours=2, minutes=5))

        await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        seams.deliver.assert_awaited_once_with(
            "conv-1",
            AuthenticatedUser(user_id=USER_ID),
            "APPROVAL_READY ap_1: the user approved Send it (2h5m old). Run it now with "
            'execute(tool_name="approve", data={"id": "ap_1"}) and continue with its result. '
            "If it is no longer needed, say so instead of running it.",
        )

    async def test_a_ticket_with_no_birth_time_says_so(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(created_at=None)

        await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        assert "Send it (unknown age)." in seams.deliver.await_args.args[2]

    async def test_a_failed_ticket_delivery_is_reported_and_wakes_the_inbox(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc()
        seams.deliver.side_effect = RuntimeError("redis down")

        await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

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

        await decide_ledger("ap_1", user_id=USER_ID, kind="deny", feedback="nope", via="card")

        seams.deliver.assert_awaited_once_with(
            "conv-1",
            AuthenticatedUser(user_id=USER_ID),
            f"DECISION ap_1=DENIED Send it :: nope{_DENY_TAIL}",
        )
        seams.record_deny.assert_awaited_once_with(row, "nope")
        seams.settle_frame.assert_called_once_with(
            "stream-1",
            "ap_1",
            CardEnd(ApprovalOutcome.DENIED, decider=ApprovalDecider.USER, feedback="nope"),
        )

    async def test_a_bare_deny_carries_no_preview(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        await decide_ledger("ap_1", user_id=USER_ID, kind="deny", via="card")

        assert seams.deliver.await_args.args[2] == f"DECISION ap_1=DENIED Send it{_DENY_TAIL}"

    async def test_a_long_deny_reason_is_clipped_for_the_agent(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        await decide_ledger("ap_1", user_id=USER_ID, kind="deny", feedback="n" * 600, via="card")

        assert seams.deliver.await_args.args[2] == (
            f"DECISION ap_1=DENIED Send it :: {'n' * 500}{_DENY_TAIL}"
        )

    async def test_a_failed_verdict_delivery_is_reported_and_wakes_the_inbox(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc()
        seams.deliver.side_effect = RuntimeError("redis down")

        await decide_ledger("ap_1", user_id=USER_ID, kind="deny", feedback="nope", via="card")

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

        outcome = await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

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
    """A committed decision settles the card on the proposing stream; every other device reads the logged decision."""

    @pytest.mark.parametrize("outcome", [ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED])
    async def test_the_settled_card_reaches_every_surface(
        self, seams: LedgerSeams, outcome: ApprovalOutcome
    ) -> None:
        row = _doc(feedback="stored words")

        await publish_ledger_decision(row, outcome)

        stream_id, entry = seams.publish_entry.await_args.args
        assert stream_id == "stream-1"
        assert entry.data.approval_id == "ap_1"
        assert entry.data.gated_tool_name == "GMAIL_SEND_EMAIL"
        assert entry.data.tool_call_id == ""
        assert entry.data.args_preview == {"to": "b@x"}
        assert (entry.data.outcome, entry.data.decider, entry.data.action) == (
            outcome,
            ApprovalDecider.USER,
            None,
        )
        assert entry.data.summary == "Send it"
        assert entry.data.integration_name is None
        assert entry.data.feedback == "stored words"
        seams.settle_frame.assert_called_once_with(
            "stream-1",
            "ap_1",
            CardEnd(outcome, decider=ApprovalDecider.USER, feedback="stored words"),
        )

    async def test_fresh_feedback_wins_over_the_stored_words(self, seams: LedgerSeams) -> None:
        await publish_ledger_decision(_doc(feedback="old"), ApprovalOutcome.DENIED, feedback="new")

        assert seams.publish_entry.await_args.args[1].data.feedback == "new"
        assert seams.settle_frame.call_args.args[2].feedback == "new"

    async def test_no_proposing_stream_skips_the_live_card(self, seams: LedgerSeams) -> None:
        await publish_ledger_decision(_doc(proposing_run_id=None), ApprovalOutcome.APPROVED)

        seams.publish_entry.assert_not_awaited()
        seams.settle_frame.assert_not_called()

    async def test_a_missed_stream_is_reported_and_the_rest_still_settles(
        self, seams: LedgerSeams
    ) -> None:
        seams.publish_entry.side_effect = RuntimeError("redis down")

        await publish_ledger_decision(_doc(), ApprovalOutcome.APPROVED)

        assert _warned(seams.log.warning) == {
            f"{LogTag.HIL} Ledger decision frame missed its stream": {
                "approval_id": "ap_1",
                "error_type": "RuntimeError",
            }
        }
        seams.settle_frame.assert_called_once()

    async def test_a_revocation_tombstones_the_proposing_stream(self, seams: LedgerSeams) -> None:
        await publish_ledger_revocation(_doc(), ApprovalOutcome.WITHDRAWN)

        seams.settle_frame.assert_called_once_with(
            "stream-1", "ap_1", CardEnd(ApprovalOutcome.WITHDRAWN), drop_if_unpublished=True
        )


@pytest.mark.unit
class TestTheInboxWake:
    async def test_no_redis_is_a_loud_drop(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["ap_a"])
        seams.redis.client = None

        await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        seams.inbox.assert_not_called()
        errors = _warned(seams.log.error)
        assert errors[
            f"{LogTag.HIL} Ledger wake dropped: no Redis client; agent will not learn this outcome"
        ] == {"approval_id": "ap_1", "outcome": "QUEUED"}

    async def test_a_failed_append_is_reported(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["ap_a"])
        seams.inbox.return_value.append.side_effect = RuntimeError("redis down")

        await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        errors = _warned(seams.log.error)
        assert errors[f"{LogTag.HIL} Ledger wake failed; outcome lives on the row only"] == {
            "approval_id": "ap_1",
            "outcome": "QUEUED",
            "error_type": "RuntimeError",
        }

    async def test_a_long_result_is_clipped_in_the_wake(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(blocked_by=["x" * 600])

        await decide_ledger("ap_1", user_id=USER_ID, kind="approve", via="card")

        text = _inbox_lines(seams)[0][1]
        assert text == f"DECISIONS: ap_1=QUEUED Send it :: {('waiting on ' + 'x' * 600)[:500]}"


@pytest.mark.unit
class TestDecideLedgerBatchOutcomes:
    async def test_every_item_is_decided_and_reported_on_its_own(self, seams: LedgerSeams) -> None:
        results: list[LedgerDecision | Exception] = [
            ApprovalRequestNotFoundError(),
            ApprovalRequestForbiddenError(),
            RuntimeError("mongo down"),
            LedgerDecision(True, "ap_4", ApprovalOutcome.APPROVED, None),
            LedgerDecision(False, "ap_5", None, None, stale=True),
            LedgerDecision(False, "ap_6", ApprovalOutcome.DENIED, None),
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
            outcomes = await decide_ledger_batch(USER_ID, items)

        assert [c.args for c in decide.await_args_list] == [(f"ap_{i}",) for i in range(1, 7)]
        assert [c.kwargs for c in decide.await_args_list] == [
            {
                "user_id": USER_ID,
                "kind": item.decision,
                "feedback": item.feedback,
                "v": item.v,
                "via": "batch",
            }
            for item in items
        ]
        assert outcomes == [
            BatchDecisionOutcome(approval_id="ap_1", resolved=False, reason="not_found"),
            BatchDecisionOutcome(approval_id="ap_2", resolved=False, reason="forbidden"),
            BatchDecisionOutcome(approval_id="ap_3", resolved=False, reason="error"),
            BatchDecisionOutcome(approval_id="ap_4", resolved=True),
            BatchDecisionOutcome(approval_id="ap_5", resolved=False, reason="stale", outcome=None),
            BatchDecisionOutcome(
                approval_id="ap_6", resolved=False, reason="not_found", outcome="denied"
            ),
        ]
        assert _warned(seams.log.error) == {
            f"{LogTag.HIL} Ledger batch decision failed for": {
                "approval_id": "ap_3",
                "error": "mongo down",
                "error_type": "RuntimeError",
                "user_id": USER_ID,
            }
        }


@pytest.mark.unit
class TestRedeemOutcomes:
    async def _redeem(self, caller: str = "executor_conv-1") -> RedeemResult:
        return await redeem_approved(
            "ap_1", user_id=USER_ID, conversation_id="conv-1", caller=caller, run_config=RUN_CONFIG
        )

    async def test_an_already_settled_ticket_is_refused_with_its_state(
        self, seams: LedgerSeams
    ) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=ActionResult.EXECUTED)

        assert await self._redeem() == RedeemResult(
            ok=False,
            approval_id="ap_1",
            action=ActionResult.EXECUTED,
            detail="Already executed; report that instead of retrying.",
        )
        seams.repo.get_by_approval_id.assert_awaited_once_with("ap_1")

    async def test_the_proposing_worker_may_redeem_its_own_ticket(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)
        seams.dispatch.return_value = MagicMock(ok=True, output="sent", error=None)

        result = await self._redeem(caller="gmail_conv-1")

        assert result == RedeemResult(
            ok=True,
            approval_id="ap_1",
            action=ActionResult.EXECUTED,
            detail="sent",
        )
        seams.repo.claim_executing.assert_awaited_once_with("ap_1")
        seams.dispatch.assert_awaited_once_with(
            user_id=USER_ID,
            tool_name="GMAIL_SEND_EMAIL",
            data={"to": "b@x"},
            account=None,
            config={"user": USER_ID},
        )
        seams.settle_frame.assert_called_once_with(
            "stream-1",
            "ap_1",
            CardEnd(
                ApprovalOutcome.APPROVED, decider=ApprovalDecider.USER, action=ActionResult.EXECUTED
            ),
        )

    async def test_another_worker_cannot_redeem(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)

        assert await self._redeem(caller="slack_conv-1") == RedeemResult(
            ok=False,
            approval_id="ap_1",
            action=None,
            detail="This ticket belongs to another worker; only its proposer or the executor may redeem it.",
        )
        seams.repo.claim_executing.assert_not_awaited()

    @pytest.mark.parametrize(
        ("current", "state"),
        [(ActionResult.EXECUTING, ActionResult.EXECUTING), (None, ApprovalOutcome.APPROVED)],
        ids=["another-redeemer", "row-vanished"],
    )
    async def test_a_lost_claim_reports_the_rows_state(
        self,
        seams: LedgerSeams,
        current: ApprovalOutcome | ActionResult | None,
        state: ApprovalOutcome | ActionResult | None,
    ) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)

        async def _lose(_: str) -> bool:
            if current is None:
                seams.rows.pop("ap_1")
            else:
                seams.rows["ap_1"] = _doc(**ledger_facts(current))
            return False

        seams.repo.claim_executing.side_effect = _lose

        assert await self._redeem() == RedeemResult(
            ok=False,
            approval_id="ap_1",
            action=ledger_facts(state)["action"],
            detail=f"Already {state}; report that instead of retrying.",
        )
        seams.dispatch.assert_not_awaited()

    async def test_an_ownerless_row_dispatches_with_no_user(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None, user_id="")
        seams.dispatch.return_value = MagicMock(ok=True, output="ok", error=None)

        await redeem_approved(
            "ap_1", user_id="", conversation_id="conv-1", caller="executor_c", run_config=RUN_CONFIG
        )

        assert seams.dispatch.await_args.kwargs["user_id"] is None

    async def test_a_raised_dispatch_lands_unknown_and_says_why(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)
        seams.dispatch.side_effect = RuntimeError("socket closed")

        result = await self._redeem()

        assert result == RedeemResult(
            ok=False,
            approval_id="ap_1",
            action=ActionResult.UNKNOWN,
            detail="RuntimeError: socket closed",
        )
        assert _warned(seams.log.error)[
            f"{LogTag.HIL} Ticket redeem raised; reconciled as UNKNOWN, never retried"
        ] == {"approval_id": "ap_1", "error_type": "RuntimeError"}

    async def test_a_provider_timeout_is_unknown_never_retried(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)
        error = MagicMock(kind=DispatchErrorKind.TIMEOUT, detail="slow")
        seams.dispatch.return_value = MagicMock(ok=False, output=None, error=error)

        result = await self._redeem()

        assert result.detail == "provider timed out; may or may not have run — never auto-retried"
        assert result.action is ActionResult.UNKNOWN

    async def test_a_failure_without_detail_still_has_words(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)
        seams.dispatch.return_value = MagicMock(ok=False, output=None, error=None)

        result = await self._redeem()

        assert (result.action, result.detail) == (ActionResult.FAILED, "unknown error")

    async def test_a_lost_receipt_reports_the_reconcilers_verdict(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)
        seams.dispatch.return_value = MagicMock(ok=True, output="sent", error=None)

        async def _reconciled(approval_id: str, *_: object, **__: object) -> bool:
            seams.rows[approval_id] = _doc(
                outcome=ApprovalOutcome.APPROVED, action=ActionResult.UNKNOWN
            )
            return False

        seams.repo.finish_action.side_effect = _reconciled

        result = await self._redeem()

        assert result == RedeemResult(
            ok=False,
            approval_id="ap_1",
            action=ActionResult.UNKNOWN,
            detail="Already unknown; report that instead of retrying.",
        )
        assert _warned(seams.log.error)[
            f"{LogTag.HIL} Ticket receipt lost its CAS; reporting actual state"
        ] == {"approval_id": "ap_1", "attempted": "executed", "actual": "unknown"}


@pytest.mark.unit
class TestRevokeMessages:
    async def _revoke(self, caller: str = "gmail_conv-1") -> str:
        return await revoke_ticket("ap_1", user_id=USER_ID, conversation_id="conv-1", caller=caller)

    async def test_a_decided_row_cannot_be_revoked(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc(outcome=ApprovalOutcome.APPROVED, action=None)

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
        [(ApprovalOutcome.APPROVED, "approved"), (None, "gone")],
        ids=["decided-meanwhile", "row-vanished"],
    )
    async def test_a_lost_revoke_race_says_what_happened(
        self, seams: LedgerSeams, current: ApprovalOutcome | ActionResult | None, said: str
    ) -> None:
        seams.rows["ap_1"] = _doc()

        async def _lose(*_: object, **__: object) -> bool:
            if current is None:
                seams.rows.pop("ap_1")
            else:
                seams.rows["ap_1"] = _doc(**ledger_facts(current))
            return False

        seams.repo.settle.side_effect = _lose

        assert await self._revoke() == f"Cannot revoke 'ap_1': already {said}."

    async def test_a_revoke_tombstones_the_card_it_withdrew(self, seams: LedgerSeams) -> None:
        seams.rows["ap_1"] = _doc()

        async def _revoked(approval_id: str, *_: object, **__: object) -> bool:
            seams.rows[approval_id] = _doc(
                outcome=ApprovalOutcome.WITHDRAWN, action=None, proposing_run_id="stream-9"
            )
            return True

        seams.repo.settle.side_effect = _revoked

        await self._revoke()

        seams.settle_frame.assert_called_once_with(
            "stream-9", "ap_1", CardEnd(ApprovalOutcome.WITHDRAWN), drop_if_unpublished=True
        )


@pytest.mark.unit
class TestCancelLedgerApprovalsSweep:
    async def test_only_the_users_pending_rows_are_withdrawn_and_each_is_counted(
        self, seams: LedgerSeams
    ) -> None:
        rows = [
            _doc(approval_id="ap_ok", outcome=ApprovalOutcome.APPROVED, action=None),
            _doc(approval_id="ap_other", user_id=OTHER_USER_ID),
            _doc(approval_id="ap_lost"),
            _doc(approval_id="ap_1", v=7),
        ]
        seams.repo.list_open.return_value = rows
        seams.rows["ap_1"] = _doc(
            v=8, outcome=ApprovalOutcome.WITHDRAWN, action=None, proposing_run_id="stream-2"
        )
        seams.repo.settle.side_effect = lambda approval_id, *_: approval_id == "ap_1"

        cancelled = await cancel_ledger_approvals(
            "conv-1", USER_ID, ["ap_ok", "ap_other", "ap_lost", "ap_1"]
        )

        assert cancelled == ["ap_1"]
        seams.repo.list_open.assert_awaited_once_with("conv-1")
        seams.settle_frame.assert_called_once_with(
            "stream-2", "ap_1", CardEnd(ApprovalOutcome.CANCELLED), drop_if_unpublished=True
        )
        seams.capture.assert_called_once_with(
            UserId(USER_ID),
            HilRevoked(
                approval_id="ap_1",
                ledger_version=8,
                revoker="cancelled-run",
                outcome=ApprovalOutcome.CANCELLED,
            ),
        )


@pytest.mark.unit
class TestReconcileStalled:
    async def test_a_stalled_row_goes_unknown_settles_and_wakes_with_a_warning(
        self, seams: LedgerSeams
    ) -> None:
        stalled = _doc(
            outcome=ApprovalOutcome.APPROVED,
            action=ActionResult.EXECUTING,
            user_id=THIRD_USER_ID,
            proposing_run_id="stream-3",
        )
        seams.repo.list_stalled_executing.return_value = [stalled]

        await reconcile_conversation_ledger("conv-1")

        cutoff = seams.repo.list_stalled_executing.await_args.args[0]
        assert cutoff.tzinfo is UTC
        assert _warned(seams.log.error) == {
            f"{LogTag.HIL} Ledger execution stalled; reconciled as UNKNOWN, never retried": {
                "approval_id": "ap_1"
            }
        }
        seams.settle_frame.assert_called_once_with(
            "stream-3",
            "ap_1",
            CardEnd(
                ApprovalOutcome.APPROVED, decider=ApprovalDecider.USER, action=ActionResult.UNKNOWN
            ),
        )
        assert _inbox_lines(seams) == [
            (
                "conv-1",
                "DECISIONS: ap_1=UNKNOWN Send it :: stalled execution reconciled; never "
                "retried. The action may or may not have run — verify before re-proposing, "
                "never blind-retry.",
                AgentTag.HIL_DECISION,
            )
        ]


@pytest.mark.unit
class TestTheTicketReachesARunWhateverHeldTheConversation:
    """The ledger's delivery over the real lock: a dead holder never strands an approval."""

    _LOCK_KEY = f"{EXECUTOR_BUSY_PREFIX}conv-1"
    _HOLDER = "dead-stream:dead-task"
    _OLD = EXECUTOR_BUSY_TTL - EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS

    async def _approve(self) -> MagicMock:
        from app.agents.core.background import executor_queue as eq, executor_runner as er
        from app.services.hil.ledger_decide import _deliver_ticket

        with (
            patch.object(eq, "StreamManager", AsyncMock()),
            patch.object(er, "_spawn_detached_run") as spawn,
            patch.object(er, "record_work_carried", AsyncMock(return_value=True)),
        ):
            await _deliver_ticket(_doc())
        return spawn

    async def test_a_ticket_for_a_conversation_whose_run_died_starts_a_run(
        self, fake_redis
    ) -> None:
        await fake_redis.set(self._LOCK_KEY, self._HOLDER, ex=self._OLD)

        spawn = await self._approve()

        assert spawn.call_args.args[0].task.startswith("APPROVAL_READY ap_1:")
        assert await fake_redis.get(self._LOCK_KEY) != self._HOLDER

    async def test_a_ticket_for_a_run_that_lives_steers_it_through_the_inbox(
        self, fake_redis
    ) -> None:
        """A live or parked run renews its liveness: the ticket joins it, never a second run."""
        await fake_redis.set(self._LOCK_KEY, self._HOLDER, ex=self._OLD)
        await hold_run_alive("conv-1", self._HOLDER)

        spawn = await self._approve()

        spawn.assert_not_called()
        [entry] = await ExecutorInbox("conv-1").read()
        assert entry.text.startswith("APPROVAL_READY ap_1:")
        assert await fake_redis.get(self._LOCK_KEY) == self._HOLDER


@pytest.mark.unit
class TestDecideLedgerAlwaysToolScope:
    """An approved "always" tap turns the tool's ask off, unless the call asks every time."""

    async def _decide(self, repo: MagicMock, **tap: Any) -> AsyncMock:
        with (
            patch(f"{MODULE}.approval_ledger_repository", new=repo),
            patch(f"{MODULE}.publish_ledger_decision", new=AsyncMock()),
            patch(f"{MODULE}._deliver_ticket", new=AsyncMock()),
            patch(f"{MODULE}._deliver_verdict", new=AsyncMock()),
            patch(f"{MODULE}.set_tool_override", new=AsyncMock()) as override,
        ):
            await ledger_decide.decide_ledger_card(
                "ap_abc", user_id=USER_ID, tap=ApprovalDecisionRequest(v=3, **tap)
            )
        return override

    async def test_an_approved_always_tap_turns_the_tools_ask_off(self) -> None:
        override = await self._decide(_repo(_row()), decision="approve", scope="always_tool")
        override.assert_awaited_once_with(USER_ID, "GMAIL_SEND_EMAIL", False)

    async def test_an_always_tap_on_an_mcp_tool_writes_its_server_scoped_key(self) -> None:
        row = _row(tool_name="posthog_delete_item", tool_key="mcp:srv_a:delete_item")
        override = await self._decide(_repo(row), decision="approve", scope="always_tool")
        override.assert_awaited_once_with(USER_ID, "mcp:srv_a:delete_item", False)

    async def test_a_row_registered_before_tool_keys_resolves_the_key_from_the_live_tool(
        self,
    ) -> None:
        row = _row(tool_name="delete_item", tool_key=None)
        with patch(
            f"{MODULE}.resolved_tool_key", new=AsyncMock(return_value="mcp:srv_a:delete_item")
        ) as resolve:
            override = await self._decide(_repo(row), decision="approve", scope="always_tool")
        resolve.assert_awaited_once_with(USER_ID, "delete_item")
        override.assert_awaited_once_with(USER_ID, "mcp:srv_a:delete_item", False)

    async def test_a_denied_always_tap_leaves_the_ask_on(self) -> None:
        override = await self._decide(_repo(_row()), decision="deny", scope="always_tool")
        override.assert_not_awaited()

    async def test_a_once_tap_leaves_the_ask_on(self) -> None:
        override = await self._decide(_repo(_row()), decision="approve")
        override.assert_not_awaited()

    async def test_a_stale_always_tap_leaves_the_ask_on(self) -> None:
        override = await self._decide(_repo(_row(v=4)), decision="approve", scope="always_tool")
        override.assert_not_awaited()

    async def test_the_tap_decides_the_approval_it_names(self) -> None:
        repo = _repo(_row())
        await self._decide(repo, decision="approve")
        assert repo.get_by_approval_id.await_args_list[0].args == ("ap_abc",)

    async def test_an_approve_with_feedback_is_recorded_as_a_conditional_deny(self) -> None:
        repo = _repo(_row())
        override = await self._decide(
            repo, decision="approve", scope="always_tool", feedback="only to bob"
        )
        repo.settle.assert_awaited_once_with(
            "ap_abc",
            ApprovalOutcome.DENIED,
            decided_by=USER_ID,
            feedback="only to bob",
        )
        override.assert_not_awaited()

    async def test_a_disconnect_refuses_the_always_scope_by_its_arguments_alone(self) -> None:
        repo = _repo(_row(tool_name="manage_linked_account", args={"action": "disconnect"}))
        with tools_that_always_ask(), pytest.raises(resolution.ToolAlwaysAsksError):
            await self._decide(repo, decision="approve", scope="always_tool")
        repo.settle.assert_not_awaited()

    @pytest.mark.regression
    async def test_a_call_that_always_asks_refuses_the_always_scope_before_committing(
        self,
    ) -> None:
        repo = _repo(_row(tool_name="update_preferences"))
        with (
            tools_that_always_ask("update_preferences"),
            pytest.raises(resolution.ToolAlwaysAsksError),
        ):
            await self._decide(repo, decision="approve", scope="always_tool")
        repo.settle.assert_not_awaited()
