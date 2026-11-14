"""A stored entry reads back as a row with its owner and commit time; a page names the openers it lacks."""

from datetime import UTC, datetime

from app.constants.chat import ConversationSource
from app.db.repositories.conversation_entries import log_document, openers_outside, stored_row
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from shared.py.approvals import ApprovalDecider, ApprovalOutcome


def test_a_stored_row_carries_its_commit_time() -> None:
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    logged = LoggedEntry(
        seq=4, at=at, entry=UserMessage(id="m1", text="hi", surface=ConversationSource.WEB)
    )

    row = stored_row(log_document("c1", "u1", logged))

    assert (row.conversation_id, row.logged) == ("c1", logged)


_AT = datetime(2026, 1, 2, tzinfo=UTC)


def _page(*entries: Entry) -> list[LoggedEntry]:
    return [LoggedEntry(seq=n, at=_AT, entry=entry) for n, entry in enumerate(entries, 10)]


def _settle(reply_id: str) -> ReplySettled:
    return ReplySettled(
        id=f"settle:{reply_id}",
        reply_id=reply_id,
        outcome=ReplyOutcome.ANSWERED,
        answers=("m1",),
        through=1,
        quote_target=None,
    )


def test_a_page_names_the_opener_of_everything_it_completes() -> None:
    page = _page(
        _settle("r1"),
        WorkFinished(id="work:t1:finished", task_id="t1", outcome=WorkOutcome.DONE, report=""),
        ApprovalRequested(id="approval:p1", task_id="t2", approval_id="p1"),
        ApprovalDecided(
            id="approval:p2:decided",
            approval_id="p2",
            outcome=ApprovalOutcome.APPROVED,
            decider=ApprovalDecider.USER,
        ),
        WorkStarted(id="work:t3", task_id="t3", cause_through=1, joins="t4"),
    )

    assert openers_outside(page) == {
        "reply_id": ["r1"],
        "task_id": ["t1", "t2", "t4"],
        "approval_id": ["p2"],
    }


def test_a_page_holding_its_openers_names_none() -> None:
    page = _page(
        Reply(id="o-r1", reply_id="r1", attempt_id="a1"),
        WorkStarted(id="work:t1", task_id="t1", cause_through=1),
        ApprovalRequested(id="approval:p1", task_id="t1", approval_id="p1"),
        ApprovalDecided(
            id="approval:p1:decided",
            approval_id="p1",
            outcome=ApprovalOutcome.DENIED,
            decider=ApprovalDecider.USER,
        ),
        WorkFinished(id="work:t1:finished", task_id="t1", outcome=WorkOutcome.DONE, report=""),
        _settle("r1"),
    )

    assert openers_outside(page) == {}
