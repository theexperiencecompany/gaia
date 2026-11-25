"""sweep_conversations: what a dead process left on each due head is finished by the next sweep."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.constants.conversation import (
    APPROVAL_EXPIRY_GRACE,
    APPROVAL_REGISTER_GRACE,
    WORK_LOST_REPORT,
)
from app.constants.hil import DECISION_HANDOFF_LEASE
from app.db.repositories.conversation_sweep import SweepHead
from app.models.conversation_log_models import ApprovalRequested, LiveWork, LoggedEntry, WorkOutcome
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.sweeper import SweepReport, sweep_conversations
from app.services.conversation.work_log import WorkReport
from shared.py.approvals import ApprovalOutcome
from tests.unit.services.conversation.log_helpers import EMPTY, T0, described, logged

MODULE = "app.services.conversation.sweeper"
NOW = T0 + timedelta(hours=1)


def _work(task_id: str, approvals: frozenset[str] = frozenset()) -> LiveWork:
    return LiveWork(
        task_id=task_id, cause_through=1, answers=(), pending_approvals=tuple(sorted(approvals))
    )


def _head(
    name: str,
    *,
    outbox: bool = False,
    work: tuple[LiveWork, ...] = (),
    unsettled: tuple[int, ...] = (),
) -> SweepHead:
    return SweepHead(
        cursor=f"cur-{name}",
        conversation_id=f"c-{name}",
        user_id=f"u-{name}",
        has_outbox=outbox,
        state=EMPTY.model_copy(update={"work": work, "unsettled_waking": unsettled}),
    )


async def _each_requested(
    conversation_id: str, *, user_id: str, ids: list[str]
) -> list[LoggedEntry]:
    return [logged(3, _requested(id_.removeprefix("approval:"), None)) for id_ in ids]


def _requested(approval_id: str, expires_at: datetime | None) -> ApprovalRequested:
    return ApprovalRequested(
        id=f"approval:{approval_id}",
        task_id="t1",
        approval_id=approval_id,
        description=described("Send it"),
        expires_at=expires_at,
    )


@dataclass
class Seams:
    repo: MagicMock
    kick: AsyncMock
    lost: AsyncMock
    finished: AsyncMock
    ledger: AsyncMock
    expire: AsyncMock
    unledgered: AsyncMock
    log: MagicMock
    ledger_repo: MagicMock
    hand_off: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    kick = AsyncMock()
    ports = SimpleNamespace(clock=lambda: NOW, effects=SimpleNamespace(kick=kick))
    with (
        patch(f"{MODULE}.runtime_ports", return_value=ports),
        patch(f"{MODULE}.conversation_sweep_repository") as repo,
        patch(f"{MODULE}.run_is_lost", AsyncMock(return_value=False)) as lost,
        patch(f"{MODULE}.record_work_finished", AsyncMock()) as finished,
        patch(f"{MODULE}.approval_ledger_repository") as ledger_repo,
        patch(f"{MODULE}.expire_ledger_approval", AsyncMock(return_value=False)) as expire,
        patch(f"{MODULE}.end_unledgered_approval", AsyncMock(return_value=True)) as unledgered,
        patch(f"{MODULE}.hand_off_stale_decision", AsyncMock(return_value=False)) as hand_off,
        patch(f"{MODULE}.log") as log,
    ):
        repo.list_heads_to_sweep = AsyncMock(return_value=[])
        repo.flush_outbox = AsyncMock()
        repo.read_log = AsyncMock(return_value=[])
        ledger_repo.get_by_approval_id = AsyncMock(return_value=None)
        ledger_repo.list_stale_deliveries = AsyncMock(return_value=[])
        yield Seams(
            repo,
            kick,
            lost,
            finished,
            ledger_repo.get_by_approval_id,
            expire,
            unledgered,
            log,
            ledger_repo,
            hand_off,
        )


def _report(seams: Seams) -> dict[str, int]:
    (call_kwargs,) = [c.kwargs for c in seams.log.set.call_args_list]
    return call_kwargs["conversation_sweep"]


async def test_it_pages_through_every_due_head_until_a_short_page(seams: Seams) -> None:
    pages = [[_head("a"), _head("b")], [_head("c")]]
    seams.repo.list_heads_to_sweep.side_effect = pages

    with patch(f"{MODULE}.SWEEP_BATCH", 2):
        report = await sweep_conversations()

    assert seams.repo.list_heads_to_sweep.await_args_list == [call(2, None), call(2, "cur-b")]
    assert report == SweepReport()


async def test_a_full_last_page_asks_for_one_more(seams: Seams) -> None:
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a"), _head("b")], []]

    with patch(f"{MODULE}.SWEEP_BATCH", 2):
        await sweep_conversations()

    assert seams.repo.list_heads_to_sweep.await_args_list == [call(2, None), call(2, "cur-b")]


async def test_it_flushes_ends_lost_work_and_kicks_unsettled_inputs(seams: Seams) -> None:
    head = _head("a", outbox=True, work=(_work("live"), _work("dead")), unsettled=(4,))
    seams.repo.list_heads_to_sweep.side_effect = [[head]]
    seams.lost.side_effect = lambda _conversation, task_id: task_id == "dead"

    report = await sweep_conversations()

    seams.repo.flush_outbox.assert_awaited_once_with("c-a", user_id="u-a")
    assert seams.lost.await_args_list == [call("c-a", "live"), call("c-a", "dead")]
    seams.finished.assert_awaited_once_with(
        "c-a", "u-a", "dead", WorkOutcome.LOST, WorkReport(WORK_LOST_REPORT)
    )
    # Named by task, so the line joins the run's own event, where a failed finish save is logged.
    seams.log.warning.assert_called_once_with(
        "work with no live run ended as lost", conversation_id="c-a", task_id="dead"
    )
    seams.kick.assert_awaited_once_with("c-a", "u-a")
    assert report == SweepReport(flushed=1, lost_work=1, kicked=1)
    assert _report(seams) == {
        "flushed": 1,
        "lost_work": 1,
        "undecidable_approvals": 0,
        "kicked": 1,
        "handed_off": 0,
        "failed": 0,
    }


async def test_a_quiet_head_is_left_alone(seams: Seams) -> None:
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(_work("live"),))]]

    report = await sweep_conversations()

    seams.repo.flush_outbox.assert_not_awaited()
    seams.finished.assert_not_awaited()
    seams.kick.assert_not_awaited()
    assert report == SweepReport()


async def test_one_failing_conversation_is_logged_and_the_rest_still_swept(seams: Seams) -> None:
    seams.repo.list_heads_to_sweep.side_effect = [
        [_head("bad", outbox=True), _head("good", unsettled=(2,))]
    ]
    seams.repo.flush_outbox.side_effect = RuntimeError("mongo down")

    report = await sweep_conversations()

    assert report == SweepReport(kicked=1, failed=1)
    seams.log.error.assert_called_once_with(
        "conversation sweep failed for one conversation",
        conversation_id="c-bad",
        error_type="RuntimeError",
        error="mongo down",
    )
    assert _report(seams)["failed"] == 1


async def test_an_expired_approval_resumes_its_work_instead_of_ending_it(seams: Seams) -> None:
    work = _work("t1", frozenset({"expired", "orphan"}))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    lapsed = NOW - APPROVAL_EXPIRY_GRACE - timedelta(seconds=1)
    seams.repo.read_log.return_value = [
        logged(3, _requested("expired", lapsed)),
        logged(4, _requested("orphan", None)),
    ]
    envelope = object()
    seams.ledger.side_effect = lambda approval_id: envelope if approval_id == "expired" else None
    seams.expire.return_value = True

    report = await sweep_conversations()

    read = seams.repo.read_log.await_args
    assert read.args == ("c-a",)
    assert read.kwargs["user_id"] == "u-a"
    assert sorted(read.kwargs["ids"]) == ["approval:expired", "approval:orphan"]
    seams.expire.assert_awaited_once_with(envelope)
    seams.unledgered.assert_awaited_once_with(
        "c-a", "u-a", _requested("orphan", None), ApprovalOutcome.WITHDRAWN
    )
    seams.finished.assert_not_awaited()
    seams.lost.assert_not_awaited()
    assert report == SweepReport(undecidable_approvals=2)


async def test_work_left_only_with_approvals_nobody_holds_resumes_withdrawn_never_failed(
    seams: Seams,
) -> None:
    work = _work("t1", frozenset({"orphan"}))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    seams.repo.read_log.side_effect = _each_requested

    report = await sweep_conversations()

    seams.expire.assert_not_awaited()
    seams.unledgered.assert_awaited_once_with(
        "c-a", "u-a", _requested("orphan", None), ApprovalOutcome.WITHDRAWN
    )
    seams.finished.assert_not_awaited()
    assert report == SweepReport(undecidable_approvals=1)


async def test_a_request_whose_gate_is_still_registering_its_row_is_left_pending(
    seams: Seams,
) -> None:
    """The gate asks in the log before it registers the row: a sweep in between must not withdraw it."""
    work = _work("t1", frozenset({"a1"}))
    asked = logged(3, _requested("a1", None))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    seams.repo.read_log.return_value = [asked]

    with patch(f"{MODULE}.runtime_ports") as ports:
        ports.return_value = SimpleNamespace(
            clock=lambda: asked.at + APPROVAL_REGISTER_GRACE - timedelta(seconds=1),
            effects=SimpleNamespace(kick=seams.kick),
        )
        report = await sweep_conversations()

    seams.unledgered.assert_not_awaited()
    assert report == SweepReport()


async def test_a_request_whose_register_grace_ran_out_without_a_row_is_withdrawn(
    seams: Seams,
) -> None:
    work = _work("t1", frozenset({"a1"}))
    asked = logged(3, _requested("a1", None))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    seams.repo.read_log.return_value = [asked]

    with patch(f"{MODULE}.runtime_ports") as ports:
        ports.return_value = SimpleNamespace(
            clock=lambda: asked.at + APPROVAL_REGISTER_GRACE,
            effects=SimpleNamespace(kick=seams.kick),
        )
        report = await sweep_conversations()

    seams.unledgered.assert_awaited_once_with(
        "c-a", "u-a", _requested("a1", None), ApprovalOutcome.WITHDRAWN
    )
    assert report == SweepReport(undecidable_approvals=1)


async def test_an_unledgered_approval_a_decision_beat_is_not_counted(seams: Seams) -> None:
    work = _work("t1", frozenset({"orphan"}))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    seams.repo.read_log.side_effect = _each_requested
    seams.unledgered.return_value = False

    report = await sweep_conversations()

    seams.finished.assert_not_awaited()
    assert report == SweepReport()


async def test_an_expiry_a_decision_beat_leaves_the_work_to_that_decision(seams: Seams) -> None:
    work = _work("t1", frozenset({"a1"}))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    lapsed = NOW - APPROVAL_EXPIRY_GRACE - timedelta(seconds=1)
    seams.repo.read_log.return_value = [logged(3, _requested("a1", lapsed))]
    seams.ledger.return_value = object()

    report = await sweep_conversations()

    seams.expire.assert_awaited_once()
    seams.finished.assert_not_awaited()
    assert report == SweepReport()


async def test_an_approval_still_in_its_grace_keeps_its_work_waiting(seams: Seams) -> None:
    work = _work("t1", frozenset({"a1"}))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    seams.repo.read_log.return_value = [logged(3, _requested("a1", NOW - APPROVAL_EXPIRY_GRACE))]
    seams.ledger.return_value = object()

    report = await sweep_conversations()

    seams.expire.assert_not_awaited()
    seams.unledgered.assert_not_awaited()
    seams.finished.assert_not_awaited()
    assert report == SweepReport()


async def test_an_envelope_less_approval_that_lapsed_is_expired_not_withdrawn(
    seams: Seams,
) -> None:
    work = _work("t1", frozenset({"a1", "a2"}))
    seams.repo.list_heads_to_sweep.side_effect = [[_head("a", work=(work,))]]
    lapsed = NOW - APPROVAL_EXPIRY_GRACE - timedelta(seconds=1)
    seams.repo.read_log.return_value = [
        logged(3, _requested("a1", lapsed)),
        logged(4, _requested("a2", None)),
    ]
    seams.unledgered.side_effect = [True, False]

    report = await sweep_conversations()

    assert seams.unledgered.await_args_list == [
        call("c-a", "u-a", _requested("a1", lapsed), ApprovalOutcome.EXPIRED),
        call("c-a", "u-a", _requested("a2", None), ApprovalOutcome.WITHDRAWN),
    ]
    seams.finished.assert_not_awaited()
    assert report == SweepReport(undecidable_approvals=1)


def _flush_fails_for(*conversation_ids: str) -> Callable[..., Awaitable[None]]:
    async def flush(conversation_id: str, user_id: str) -> None:
        if conversation_id in conversation_ids:
            raise RuntimeError("flush failed")

    return flush


async def test_counts_add_up_across_heads_pages_and_work(seams: Seams) -> None:
    def busy(name: str) -> SweepHead:
        return _head(
            name,
            outbox=True,
            work=(_work(f"{name}-held", frozenset({f"{name}-ap"})), _work(f"{name}-dead")),
            unsettled=(3,),
        )

    seams.repo.list_heads_to_sweep.side_effect = [
        [busy("a"), _head("x", outbox=True), busy("b")],
        [busy("c"), _head("y", outbox=True)],
    ]
    seams.repo.flush_outbox.side_effect = _flush_fails_for("c-x", "c-y")
    seams.repo.read_log.side_effect = _each_requested
    seams.lost.return_value = True

    with patch(f"{MODULE}.SWEEP_BATCH", 3):
        report = await sweep_conversations()

    assert seams.repo.list_heads_to_sweep.await_args_list == [call(3, None), call(3, "cur-b")]
    assert [c.args[2] for c in seams.finished.await_args_list] == ["a-dead", "b-dead", "c-dead"]
    assert [c.args[2].approval_id for c in seams.unledgered.await_args_list] == [
        "a-ap",
        "b-ap",
        "c-ap",
    ]
    assert report == SweepReport(
        flushed=3, lost_work=3, undecidable_approvals=3, kicked=3, failed=2
    )


def _handing_off(approval_id: str, since: datetime) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=f"c-{approval_id}",
        user_id="u1",
        fingerprint=f"fp-{approval_id}",
        tool_name="GMAIL_SEND_EMAIL",
        args={},
        summary="Send it",
        outcome=ApprovalOutcome.APPROVED,
        delivering_since=since,
    )


def _ledger_holding(
    *rows: ApprovalLedgerDocument,
) -> Callable[..., Awaitable[list[ApprovalLedgerDocument]]]:
    """Serve list_stale_deliveries as the repository does: hand-offs begun before the cutoff."""

    async def stale(cutoff: datetime) -> list[ApprovalLedgerDocument]:
        return [row for row in rows if row.delivering_since and row.delivering_since < cutoff]

    return stale


async def test_a_hand_off_older_than_its_lease_is_retried_and_a_newer_one_is_not(
    seams: Seams,
) -> None:
    stale = [
        _handing_off(name, NOW - DECISION_HANDOFF_LEASE - timedelta(seconds=1))
        for name in ("ap-1", "ap-2", "ap-done")
    ]
    fresh = _handing_off("ap-fresh", NOW - DECISION_HANDOFF_LEASE + timedelta(seconds=1))
    seams.ledger_repo.list_stale_deliveries.side_effect = _ledger_holding(*stale, fresh)
    # ap-done's own decide finished the hand-off before the sweep's lease: none was due.
    seams.hand_off.side_effect = lambda row, now: row.approval_id != "ap-done"

    report = await sweep_conversations()

    assert seams.hand_off.await_args_list == [call(row, NOW) for row in stale]
    assert report == SweepReport(handed_off=2)
    assert _report(seams)["handed_off"] == 2


async def test_a_hand_off_that_fails_again_is_logged_and_the_rest_still_handed_off(
    seams: Seams,
) -> None:
    rows = [
        _handing_off(name, NOW - DECISION_HANDOFF_LEASE - timedelta(seconds=1))
        for name in ("ap-1", "ap-2", "ap-3")
    ]
    seams.ledger_repo.list_stale_deliveries.side_effect = _ledger_holding(*rows)

    async def hand_off(row: ApprovalLedgerDocument, now: datetime) -> bool:
        if row.approval_id != "ap-2":
            raise RuntimeError(f"executor down for {row.approval_id}")
        return True

    seams.hand_off.side_effect = hand_off

    report = await sweep_conversations()

    assert report == SweepReport(handed_off=1, failed=2)
    assert seams.log.error.call_args_list == [
        call(
            "approval decision hand-off failed again",
            approval_id=approval_id,
            conversation_id=f"c-{approval_id}",
            error_type="RuntimeError",
            error=f"executor down for {approval_id}",
        )
        for approval_id in ("ap-1", "ap-3")
    ]
