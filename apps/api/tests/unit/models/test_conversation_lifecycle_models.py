"""The lifecycle types refuse the states the old flags could hold."""

from pydantic import ValidationError
import pytest

from app.models.conversation_lifecycle_models import (
    Approval,
    ApprovalPending,
    InputOrigin,
    Lifecycles,
    Message,
    MessageAnswered,
    MessageOpen,
    RunAwaitingApproval,
    RunDone,
    RunMode,
    RunParked,
    RunRunning,
    WorkResult,
    WorkRun,
)
from shared.py.conversation_wire import ReplyOutcome


def _run(task_id: str, status: RunRunning | RunAwaitingApproval | RunParked | RunDone) -> WorkRun:
    return WorkRun(
        task_id=task_id,
        cause_from=1,
        cause_through=1,
        answers=(),
        mode=RunMode.ATTACHED,
        status=status,
    )


def _pending(owner: str) -> Approval:
    return Approval(approval_id="ap", owner=owner, number=1, status=ApprovalPending())


def test_state_refuses_an_answered_input() -> None:
    answered = Message(
        seq=1,
        id="u1",
        origin=InputOrigin.USER,
        status=MessageAnswered(reply_id="r1", outcome=ReplyOutcome.ANSWERED),
    )
    with pytest.raises(ValidationError, match="live inputs only"):
        Lifecycles(messages=(answered,))


def test_state_refuses_an_ended_run() -> None:
    with pytest.raises(ValidationError, match="live runs only"):
        Lifecycles(runs=(_run("t", RunDone()),))


def test_an_approval_cannot_outlive_its_run() -> None:
    with pytest.raises(ValidationError, match="beside its owner run"):
        Lifecycles(approvals=(_pending("t"),))


def test_a_run_cannot_wait_with_nothing_pending() -> None:
    with pytest.raises(ValidationError, match="waits exactly while"):
        Lifecycles(runs=(_run("t", RunParked()),))


def test_a_run_cannot_run_past_a_pending_approval() -> None:
    with pytest.raises(ValidationError, match="waits exactly while"):
        Lifecycles(runs=(_run("t", RunRunning()),), approvals=(_pending("t"),))


def test_a_waiting_run_with_its_pending_approval_is_valid() -> None:
    state = Lifecycles(runs=(_run("t", RunAwaitingApproval()),), approvals=(_pending("t"),))
    assert state.approvals[0].pending


def test_only_a_work_result_carries_a_result() -> None:
    result = WorkResult(task_id="t", cause_from=1, cause_through=1, answers=())
    with pytest.raises(ValidationError, match="only one does"):
        Message(seq=1, id="u1", origin=InputOrigin.USER, status=MessageOpen(), result=result)
    with pytest.raises(ValidationError, match="only one does"):
        Message(seq=1, id="w1", origin=InputOrigin.WORK_RESULT, status=MessageOpen())
