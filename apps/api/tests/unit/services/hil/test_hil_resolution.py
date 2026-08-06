"""Attacks on decision resolution (app/services/hil/resolution.py).

An approval decision moves money, sends mail, deletes things. The attacks:

* decide someone else's approval;
* decide the same approval twice and get the action executed twice;
* be told "approved" for an action that can never actually run.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.hil.resolution import (
    ApprovalNotResumable,
    ApprovalRequestForbidden,
    ApprovalRequestNotFound,
    abandon_conversation_approvals,
    resolve_approval,
    resolve_approvals_batch,
    sweep_approvals,
)

from .conftest import USER_ID, make_record

MODULE = "app.services.hil.resolution"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture
def resume() -> Any:
    """Mocks the run-dispatch boundary; the resolution logic itself runs for real."""
    prepared = MagicMock(run=MagicMock(), task=MagicMock(), configurable={})
    with (
        patch(f"{MODULE}.prepare_run_from_item", new=AsyncMock(return_value=prepared)) as prepare,
        patch(f"{MODULE}.run_executor_background", new=AsyncMock()) as runner,
        patch(f"{MODULE}.mark_resumed", new=AsyncMock()) as resumed,
        patch(f"{MODULE}.claim_resume_dispatch", new=AsyncMock(return_value=True)) as claim,
        patch(f"{MODULE}.release_resume_dispatch", new=AsyncMock()) as release,
    ):
        yield MagicMock(
            prepare=prepare, runner=runner, mark_resumed=resumed, claim=claim, release=release
        )


class TestAuthorization:
    async def test_another_users_approval_cannot_be_decided(self, resume: Any) -> None:
        record = make_record(user_id="507f1f77bcf86cd799439011")
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock()) as decided,
            pytest.raises(ApprovalRequestForbidden),
        ):
            await resolve_approval(approval_id="appr-1", user_id="attacker-id", kind="approve")

        # Not merely rejected — nothing was recorded and nothing was run.
        assert decided.await_count == 0
        assert resume.prepare.await_count == 0

    async def test_a_missing_approval_raises_rather_than_resuming_anything(
        self, resume: Any
    ) -> None:
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=None)),
            pytest.raises(ApprovalRequestNotFound),
        ):
            await resolve_approval(approval_id="nope", user_id=USER_ID, kind="approve")
        assert resume.prepare.await_count == 0


class TestExactlyOnce:
    async def test_a_second_decision_on_the_same_approval_does_not_run_the_action_twice(
        self, resume: Any
    ) -> None:
        # Double-click, or a bot callback racing the UI. mark_decided is a conditional
        # pending->decided update, so the loser transitions nothing and MUST NOT resume:
        # a second dispatch is a second send.
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=False)),
            pytest.raises(ApprovalRequestNotFound),
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert resume.prepare.await_count == 0
        assert resume.runner.call_count == 0

    async def test_the_winning_decision_resumes_the_run_exactly_once(self, resume: Any) -> None:
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)),
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert resume.runner.call_count == 1
        command = resume.runner.call_args.kwargs["resume"]
        assert command.resume["status"] == "approved"


class TestUnresumableRecords:
    async def test_a_record_with_no_resume_context_is_not_marked_decided(self, resume: Any) -> None:
        # Ordering invariant. If the decided-transition happened first, the user would be
        # told "approved" for an action that can never execute, and the sweep could never
        # expire the record. The check must come BEFORE the write.
        record = make_record(resume_item=None)
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock()) as decided,
            pytest.raises(ApprovalNotResumable),
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert decided.await_count == 0  # stays pending; the sweep will expire it
        assert resume.prepare.await_count == 0

    async def test_an_early_decision_on_a_parked_subagent_decides_without_dispatch(
        self, resume: Any
    ) -> None:
        # The user answers a parked subagent's card BEFORE the executor reaches its
        # join (so no resume_item exists yet). With a live executor (busy lock held)
        # the decision must land — the running executor collects it durably — and
        # must NOT dispatch or stamp a resume.
        record = make_record(resume_item=None, subagent_thread_id="gmail_executor_conv-1")
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.is_executor_busy", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert decided.await_count == 1  # the decision is durable
        assert resume.prepare.await_count == 0  # nothing to wake — executor is running
        assert resume.mark_resumed.await_count == 0  # no dispatch happened, none stamped

    async def test_an_early_decision_with_no_live_executor_fails_loudly(self, resume: Any) -> None:
        # Fire-and-forget: the executor finished without ever joining, so nobody
        # will collect this decision. Accepting it would tell the user "going
        # ahead" for an action that never runs — refuse instead; the sweep
        # expires the record as a visible timeout.
        record = make_record(resume_item=None, subagent_thread_id="gmail_executor_conv-1")
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.is_executor_busy", new=AsyncMock(return_value=False)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock()) as decided,
            pytest.raises(ApprovalNotResumable),
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert decided.await_count == 0  # stays pending for the sweep's loud timeout
        assert resume.prepare.await_count == 0

    async def test_a_failed_run_preparation_leaves_the_record_unstamped_for_the_sweep(
        self, resume: Any
    ) -> None:
        # The conversation lock could not be seized. Stamping resumed_at here would hide
        # the record from the sweep forever and strand the paused run.
        resume.prepare.return_value = None
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)),
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert resume.runner.call_count == 0
        assert resume.mark_resumed.await_count == 0
        # The slot was claimed but no run will release it — the dispatch must.
        assert resume.release.await_count == 1

    async def test_a_lost_resume_slot_skips_dispatch_but_keeps_the_decision(
        self, resume: Any
    ) -> None:
        # Two decisions on one batch land near-simultaneously. The loser must NOT
        # start a second LangGraph run on the same executor thread (checkpoint
        # corruption) — and must NOT stamp resumed_at, so the sweep can dispatch
        # the decision later if the in-flight round misses it.
        resume.claim.return_value = False
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="approve")

        assert decided.await_count == 1  # the decision itself is durable
        assert resume.prepare.await_count == 0
        assert resume.runner.call_count == 0
        assert resume.mark_resumed.await_count == 0
        assert resume.release.await_count == 0  # never touch a slot we don't hold


class TestDecisionSemantics:
    async def test_a_timeout_is_not_attributed_to_the_user(self, resume: Any) -> None:
        # decided_by must be None: nobody decided this, the clock did.
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="timeout")

        assert decided.await_args.kwargs["decided_by"] is None
        assert decided.await_args.args[1] == "timeout"

    async def test_a_user_decision_is_attributed_to_them(self, resume: Any) -> None:
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="deny")

        assert decided.await_args.kwargs["decided_by"] == USER_ID
        assert decided.await_args.args[1] == "denied"

    async def test_an_abandoned_approval_is_audited_as_abandoned_but_resumes_as_a_denial(
        self, resume: Any
    ) -> None:
        # The user moved on. The audit trail must say "abandoned", but the agent must be
        # told "denied" — if it resumed as anything else it would perform the action the
        # user walked away from.
        record = make_record()
        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(return_value=record)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            await resolve_approval(approval_id="appr-1", user_id=USER_ID, kind="abandon")

        assert decided.await_args.args[1] == "abandoned"
        assert resume.runner.call_args.kwargs["resume"].resume["status"] == "denied"


class TestBatchDecisions:
    async def test_one_failed_item_never_blocks_the_rest(self, resume: Any) -> None:
        # The batch review submits N decisions; an already-decided approval (double
        # click, resolved elsewhere) must be reported per-item, not abort the batch.
        good = make_record(approval_id="a-good")
        gone = make_record(approval_id="a-gone")

        async def load(approval_id: str) -> Any:
            return {"a-good": good, "a-gone": gone}[approval_id]

        async def transition(approval_id: str, *args: Any, **kwargs: Any) -> bool:
            return approval_id == "a-good"  # "a-gone" was already decided

        with (
            patch(f"{MODULE}.get_approval", new=AsyncMock(side_effect=load)),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(side_effect=transition)),
        ):
            outcomes = await resolve_approvals_batch(
                USER_ID,
                [("a-good", "approve", None), ("a-gone", "deny", None)],
            )

        assert outcomes == [
            {"approval_id": "a-good", "resolved": True, "reason": None},
            {"approval_id": "a-gone", "resolved": False, "reason": "not_found"},
        ]
        assert resume.prepare.await_count == 1  # only the real transition dispatched


class TestAbandonConversation:
    async def test_one_undecidable_record_does_not_strand_the_others(self, resume: Any) -> None:
        # The whole point of abandoning is to release the conversation's executor lock.
        # If a single already-decided record aborted the loop, the lock would stay held.
        records = [
            make_record(approval_id="a1"),
            make_record(approval_id="a2"),  # this one loses the transition race
            make_record(approval_id="a3"),
        ]

        async def decided(approval_id: str, *_: Any, **__: Any) -> bool:
            return approval_id != "a2"

        with (
            patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=records)),
            patch(f"{MODULE}.mark_decided", side_effect=decided),
        ):
            abandoned = await abandon_conversation_approvals("conv-1", USER_ID, "moved on")

        assert abandoned == ["a1", "a3"]

    async def test_a_record_with_no_resume_context_is_closed_rather_than_left_pending(
        self, resume: Any
    ) -> None:
        # A record left pending goes on hijacking every later message in the conversation
        # via the conversational resolver. It must be closed even though nothing can resume.
        record = make_record(approval_id="a1", resume_item=None)
        with (
            patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=[record])),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            abandoned = await abandon_conversation_approvals("conv-1", USER_ID, "moved on")

        assert abandoned == ["a1"]
        assert decided.await_args.args[1] == "abandoned"
        assert resume.prepare.await_count == 0


class TestSweep:
    async def test_expired_approvals_time_out_and_resume_their_runs(self, resume: Any) -> None:
        expired = make_record(approval_id="a1")
        with (
            patch(f"{MODULE}.list_expired_pending", new=AsyncMock(return_value=[expired])),
            patch(f"{MODULE}.list_decided_unresumed", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=True)) as decided,
        ):
            counts = await sweep_approvals()

        assert counts == {"expired": 1, "redispatched": 0}
        assert decided.await_args.args[1] == "timeout"
        assert resume.runner.call_args.kwargs["resume"].resume["status"] == "timeout"

    async def test_a_crashed_resume_is_redispatched(self, resume: Any) -> None:
        # Decided, but the process died before the run spawned. Without this the user
        # clicked approve and nothing ever happened.
        stranded = make_record(approval_id="a2", status="approved", resumed_at=None)
        with (
            patch(f"{MODULE}.list_expired_pending", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.list_decided_unresumed", new=AsyncMock(return_value=[stranded])),
        ):
            counts = await sweep_approvals()

        assert counts == {"expired": 0, "redispatched": 1}
        assert resume.runner.call_args.kwargs["resume"].resume["status"] == "approved"

    async def test_a_stranded_abandoned_record_redispatches_as_a_denial(self, resume: Any) -> None:
        # "abandoned" is not a resumable status — the gate would read it as malformed and
        # deny anyway, but relying on that is luck. It must be mapped explicitly.
        stranded = make_record(approval_id="a3", status="abandoned", resumed_at=None)
        with (
            patch(f"{MODULE}.list_expired_pending", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.list_decided_unresumed", new=AsyncMock(return_value=[stranded])),
        ):
            await sweep_approvals()

        assert resume.runner.call_args.kwargs["resume"].resume["status"] == "denied"

    async def test_an_expired_record_already_decided_by_the_user_is_not_double_resolved(
        self, resume: Any
    ) -> None:
        # The sweep fires just as the user clicks approve. The user wins; the sweep must
        # not overwrite their decision or resume the run a second time.
        expired = make_record(approval_id="a1")
        with (
            patch(f"{MODULE}.list_expired_pending", new=AsyncMock(return_value=[expired])),
            patch(f"{MODULE}.list_decided_unresumed", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.mark_decided", new=AsyncMock(return_value=False)),
        ):
            counts = await sweep_approvals()

        assert counts == {"expired": 0, "redispatched": 0}
        assert resume.runner.call_count == 0
