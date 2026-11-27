"""A stored entry reads back as a row with its owner and commit time; a page names the openers it lacks."""

from datetime import UTC, datetime

import bson
from pymongo.errors import (
    AutoReconnect,
    DocumentTooLarge,
    DuplicateKeyError,
    OperationFailure,
    WriteError,
)
import pytest

from app.constants.chat import ConversationSource
from app.db.repositories.conversation_entries import (
    EMPTY_LOG_STATE,
    current_state,
    is_too_large,
    log_document,
    newest,
    openers_outside,
    store_errors,
    stored_at,
    stored_row,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    Entry,
    LoggedEntry,
    Reply,
    ReplySettled,
    UserMessage,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_models import ConversationHead, StoredEntry
from app.utils.errors import ConversationStoreError
from shared.py.approvals import ApprovalDecider, ApprovalOutcome
from shared.py.conversation_wire import ReplyOutcome
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import asked


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
        asked("approval:p1", "t2", "p1"),
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
        asked("approval:p1", "t1", "p1"),
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


def test_the_current_state_is_the_stored_fold_at_the_log_head() -> None:
    folded = EMPTY_LOG_STATE.model_copy(update={"stopped_through": 3})
    head = ConversationHead(conversation_id="c1", user_id="u1", log_head=7, state=folded)
    assert current_state(head) == folded.model_copy(update={"head": 7})
    empty = ConversationHead(conversation_id="c1", user_id="u1")
    assert current_state(empty) == EMPTY_LOG_STATE.model_copy(update={"head": 0})


def _copy(revision: int | None) -> StoredEntry:
    return StoredEntry(conversation_id="c1", user_id="u1", seq=1, id="m1", revision=revision)


@pytest.mark.parametrize(
    ("stored", "staged", "read"),
    [
        (None, 1, "staged"),
        (2, None, "stored"),
        (None, None, "stored"),
        (1, 2, "staged"),
        (2, 2, "stored"),
        (3, 2, "stored"),
    ],
)
def test_a_read_returns_the_staged_copy_only_when_it_is_newer(
    stored: int | None, staged: int | None, read: str
) -> None:
    held, outboxed = _copy(stored), _copy(staged)
    assert newest(held, outboxed) is (outboxed if read == "staged" else held)


def test_a_read_with_nothing_stored_returns_the_staged_copy() -> None:
    outboxed = _copy(None)
    assert newest(None, outboxed) is outboxed


def test_a_stored_time_keeps_whole_milliseconds() -> None:
    at = datetime(2026, 1, 2, 3, 4, 5, 999_500, tzinfo=UTC)
    assert stored_at(at) == datetime(2026, 1, 2, 3, 4, 5, 999_000, tzinfo=UTC)


@pytest.mark.parametrize(
    ("failure", "too_large"),
    [
        (DocumentTooLarge("update command document too large"), True),
        (WriteError("BSONObj size is invalid", 10334), True),
        (WriteError("Resulting document after update is larger than 16777216", 17419), True),
        (OperationFailure("Document to upsert is larger than 16777216", 17420), True),
        (DuplicateKeyError("E11000 duplicate key", 11000), False),
        (OperationFailure("no code"), False),
        (AutoReconnect("connection reset by peer"), False),
        (ValueError("10334"), False),
    ],
)
def test_only_a_write_past_the_document_size_cap_is_too_large(
    failure: Exception, too_large: bool
) -> None:
    assert is_too_large(failure) is too_large


async def test_a_failed_store_call_logs_its_cause_and_the_size_of_what_it_wrote_never_the_content() -> (
    None
):
    document = {"id": "work:t1:finished", "report": "the user's private result"}
    failure = WriteError("Resulting document after update is larger than 16777216", 17419)

    async with captured_wide_event() as event:
        with (
            pytest.raises(ConversationStoreError) as raised,
            store_errors("log append", entry=document),
        ):
            raise failure

    cause = {
        "operation": "log append",
        "error_type": "WriteError",
        "mongo_code": 17419,
        "too_large": True,
        "entry_bytes": len(bson.encode(document)),
    }
    assert event["errors"] == [{"msg": "conversation store call failed", **cause}]
    assert raised.value.message == "conversation store log append failed"
    assert raised.value.meta == cause
    assert raised.value.__cause__ is failure


async def test_a_store_call_that_wrote_no_entry_logs_no_size_and_a_driver_error_no_code() -> None:
    async with captured_wide_event() as event:
        with pytest.raises(ConversationStoreError) as raised, store_errors("log claim"):
            raise AutoReconnect("connection reset by peer")

    assert event["errors"] == [
        {
            "msg": "conversation store call failed",
            "operation": "log claim",
            "error_type": "AutoReconnect",
            "mongo_code": None,
            "too_large": False,
            "entry_bytes": None,
        }
    ]
    assert raised.value.why == "connection reset by peer"


def test_an_error_that_is_not_the_stores_passes_through_unchanged() -> None:
    with pytest.raises(ValueError, match="not mongo"), store_errors("log append"):
        raise ValueError("not mongo")


async def test_a_write_the_driver_will_not_send_is_logged_and_raised_as_it_came() -> None:
    document = {"id": "work:t1:finished", "report": "the user's private result"}
    refused = DocumentTooLarge("update command document too large")

    async with captured_wide_event() as event:
        with pytest.raises(DocumentTooLarge) as raised, store_errors("log append", entry=document):
            raise refused

    assert raised.value is refused
    assert event["errors"] == [
        {
            "msg": "conversation store call failed",
            "operation": "log append",
            "error_type": "DocumentTooLarge",
            "mongo_code": None,
            "too_large": True,
            "entry_bytes": len(bson.encode(document)),
        }
    ]
