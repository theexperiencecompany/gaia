"""verdict, merge_group, needs_reply and quote_target."""

from datetime import timedelta

import pytest

from app.constants.conversation import RESTART_WINDOW_SECONDS
from app.models.conversation_log_models import (
    Batch,
    CommitReason,
    Entry,
    MergeGroup,
    PreemptHint,
    StepClaim,
    Verdict,
    VisibleEntry,
    WakingEntry,
    WorkOutcome,
)
from app.services.conversation.verdict import merge_group, needs_reply, quote_target, verdict
from tests.unit.services.conversation.log_helpers import (
    T0,
    asked,
    barge,
    decided,
    finished,
    fired,
    logged,
    notice,
    opened,
    settled,
    started,
    stop,
    todo_woke,
    user,
)

EPOCH = 3
BATCH = Batch(start=5, end=6, waking=(logged(5, user("u5")), logged(6, user("u6"))), first_at=T0)
CLAIM = StepClaim(conversation_id="c1", user_id="u", epoch=EPOCH)
WITHIN = T0 + timedelta(seconds=5)


def _hint(
    *, head: int = 6, stop_through: int = 0, barge_reply_id: str | None = None, epoch: int = EPOCH
) -> PreemptHint:
    return PreemptHint(
        head=head, stop_through=stop_through, barge_reply_id=barge_reply_id, epoch=epoch
    )


def _verdict(
    hint: PreemptHint, *, committed: CommitReason | None = None, now_offset: float = 5.0
) -> Verdict:
    return verdict(
        committed=committed,
        batch=BATCH,
        hint=hint,
        claim=CLAIM,
        now=T0 + timedelta(seconds=now_offset),
    )


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        (_hint(epoch=EPOCH + 1, stop_through=5, barge_reply_id="r", head=9), Verdict.LOST),
        (_hint(stop_through=5, barge_reply_id="r", head=9), Verdict.STOP),
        (_hint(barge_reply_id="r", head=9), Verdict.TRUNCATE),
        (_hint(head=7), Verdict.RESTART),
        (_hint(), Verdict.CONTINUE),
    ],
)
def test_verdict_truth_table_in_precedence_order(hint: PreemptHint, expected: Verdict) -> None:
    assert _verdict(hint) is expected


@pytest.mark.parametrize(
    ("stop_through", "expected"), [(4, Verdict.CONTINUE), (5, Verdict.STOP), (6, Verdict.STOP)]
)
def test_stop_applies_from_the_batch_start(stop_through: int, expected: Verdict) -> None:
    assert _verdict(_hint(stop_through=stop_through)) is expected


@pytest.mark.parametrize(
    ("epoch", "expected"), [(EPOCH, Verdict.CONTINUE), (EPOCH - 1, Verdict.LOST)]
)
def test_any_other_epoch_is_lost(epoch: int, expected: Verdict) -> None:
    assert _verdict(_hint(epoch=epoch)) is expected


@pytest.mark.parametrize("committed", list(CommitReason))
def test_a_committed_attempt_never_restarts(committed: CommitReason) -> None:
    assert _verdict(_hint(head=7), committed=committed) is Verdict.CONTINUE


@pytest.mark.parametrize(("head", "expected"), [(6, Verdict.CONTINUE), (7, Verdict.RESTART)])
def test_restart_needs_an_input_after_the_batch(head: int, expected: Verdict) -> None:
    assert _verdict(_hint(head=head)) is expected


@pytest.mark.parametrize(
    ("now_offset", "expected"),
    [(RESTART_WINDOW_SECONDS - 0.001, Verdict.RESTART), (RESTART_WINDOW_SECONDS, Verdict.CONTINUE)],
)
def test_restart_window_is_exclusive_at_its_end(now_offset: float, expected: Verdict) -> None:
    assert _verdict(_hint(head=7), now_offset=now_offset) is expected


@pytest.mark.parametrize(
    ("entry", "group"),
    [
        (user("u"), MergeGroup.INTERACTIVE),
        (barge("b", "r"), MergeGroup.INTERACTIVE),
        (finished("f", "t1"), MergeGroup.INTERACTIVE),
        (fired("w"), MergeGroup.BACKGROUND),
    ],
)
def test_only_a_workflow_fire_is_background(entry: WakingEntry, group: MergeGroup) -> None:
    assert merge_group(entry) is group


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (user("u"), True),
        (barge("b", "r"), True),
        (fired("w"), True),
        (finished("f", "t1", WorkOutcome.DONE), True),
        (finished("f", "t1", WorkOutcome.FAILED), True),
        (finished("f", "t1", WorkOutcome.LOST), True),
        (finished("f", "t1", WorkOutcome.CANCELLED), False),
        (stop("s"), False),
        (todo_woke("t"), False),
        (notice("n"), False),
        (started("w", "t1", 1), False),
        (asked("a", "t1", "ap"), False),
        (decided("d", "ap"), False),
        (opened("o"), False),
        (settled("r", ["u"], 1), False),
    ],
)
def test_needs_reply(entry: Entry, expected: bool) -> None:
    assert needs_reply(entry) is expected


def _msg(seq: int, entry_id: str) -> VisibleEntry:
    return VisibleEntry(seq=seq, id=entry_id, is_user_message=True)


def _reply(seq: int, entry_id: str) -> VisibleEntry:
    return VisibleEntry(seq=seq, id=entry_id, is_user_message=False)


def test_quote_target_is_none_for_a_reply_directly_after_its_only_message() -> None:
    assert quote_target(["u1"], 2, [_msg(1, "u1")]) is None


def test_quote_target_is_none_for_a_reply_after_two_answered_messages_back_to_back() -> None:
    assert quote_target(["u1", "u2"], 3, [_msg(1, "u1"), _msg(2, "u2")]) is None


def test_quote_target_quotes_the_original_request_on_a_late_result() -> None:
    visible = [_msg(1, "u1"), _msg(3, "u3"), _reply(4, "r3")]
    assert quote_target(["u1", "wf6"], 7, visible) == "u1"


def test_quote_target_quotes_the_message_when_an_earlier_reply_sits_between() -> None:
    assert quote_target(["u1"], 3, [_msg(1, "u1"), _reply(2, "r0")]) == "u1"


def test_quote_target_is_none_when_no_user_message_was_answered() -> None:
    assert quote_target(["wf2", "r0"], 4, [_msg(1, "u1"), _reply(2, "r0")]) is None


def test_quote_target_ignores_visible_entries_at_or_after_the_reply() -> None:
    assert quote_target(["u1"], 2, [_msg(1, "u1"), _reply(2, "r1"), _msg(3, "u3")]) is None


def test_quote_target_picks_the_newest_answered_message() -> None:
    visible = [_msg(1, "u1"), _msg(2, "u2"), _reply(3, "r2"), _msg(4, "u4"), _reply(5, "r4")]
    assert quote_target(["u1", "u4"], 6, visible) == "u4"
