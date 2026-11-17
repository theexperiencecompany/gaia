"""The lifecycle fold over generated logs agrees with the legacy state fields it will replace."""

from hypothesis import given, strategies as st

from app.models.conversation_lifecycle_models import (
    Lifecycles,
    RunAwaitingApproval,
    RunParked,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ConversationState,
    Entry,
    LiveWork,
    Transition,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.lifecycle import views
from app.services.conversation.reducer import reduce
from shared.py.approvals import ApprovalDecider, ApprovalOutcome
from shared.py.conversation_wire import ReplyOutcome
from tests.unit.services.conversation.log_helpers import (
    EMPTY,
    asked,
    barge,
    finished,
    fired,
    logged,
    notice,
    opened,
    settled,
    stop,
    todo_woke,
    user,
)

FOLDED = EMPTY.model_copy(update={"lifecycles": Lifecycles()})


def _ghost(item: LiveWork) -> bool:
    """Return whether legacy keeps item live with nothing left to wait on: a parked run whose approval was cancelled."""
    return item.ended and not item.pending_approvals


def _decision(
    entry_id: str, approval_id: str, outcome: ApprovalOutcome, note: str | None
) -> ApprovalDecided:
    decider = (
        ApprovalDecider.USER
        if outcome in {ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED}
        else None
    )
    return ApprovalDecided(
        id=entry_id, approval_id=approval_id, outcome=outcome, decider=decider, feedback=note
    )


def _next_entry(
    data: st.DataObject, state: ConversationState, seq: int, ids: dict[int, str]
) -> Entry:
    """Draw an entry reduce accepts at seq; a settle names exactly the user messages it rides past, as the step does."""
    entry_id = f"e{seq}"
    live = [item.task_id for item in state.work]
    pending = list(state.asking)
    closed_users = [ids[s] for s in ids if s not in state.unsettled_waking]
    options: list[st.SearchStrategy[Entry]] = [
        st.booleans().map(lambda voice: user(entry_id, voice=voice)),
        (st.none() | st.integers(0, seq - 1)).map(lambda covers: stop(entry_id, covers)),
        st.just(barge(entry_id, "r1")),
        st.just(todo_woke(entry_id)),
        st.just(notice(entry_id)),
        st.tuples(
            st.sampled_from([*pending, "ap_gone"]),
            st.sampled_from(list(ApprovalOutcome)),
            st.none() | st.just("make it high priority"),
        ).map(lambda drawn: _decision(entry_id, *drawn)),
        st.tuples(
            st.sampled_from([*live, "t_gone"]), st.sampled_from(list(WorkOutcome)), st.booleans()
        ).map(lambda drawn: finished(entry_id, drawn[0], drawn[1], continued_by_decision=drawn[2])),
    ]
    if not state.unsettled_fires and not state.work:
        options.append(st.just(fired(entry_id)))
    if state.stopped_through + 1 <= seq - 1:
        options.append(
            st.tuples(
                st.integers(state.stopped_through + 1, seq - 1),
                st.lists(st.sampled_from(closed_users), max_size=2)
                if closed_users
                else st.just([]),
                st.sampled_from([None, *live]),
                st.booleans(),
            ).map(
                lambda drawn: WorkStarted(
                    id=entry_id,
                    task_id=f"t{seq}",
                    cause_through=drawn[0],
                    answers=tuple(drawn[1]),
                    joins=drawn[2],
                    detached=drawn[3],
                )
            )
        )
    if live:
        options.append(st.sampled_from(live).map(lambda task: asked(entry_id, task, f"ap{seq}")))
    if state.open_reply is None:
        options.append(st.just(opened(entry_id, f"r{seq}")))
    elif (state.open_reply_seq or seq) > 1:
        open_reply = state.open_reply
        throughs = st.integers(1, (state.open_reply_seq or seq) - 1)
        outcomes = st.sampled_from(
            [ReplyOutcome.ANSWERED, ReplyOutcome.SILENT, ReplyOutcome.FAILED]
        )

        def _settle(drawn: tuple[int, ReplyOutcome]) -> Entry:
            through, outcome = drawn
            named = [ids[s] for s in state.unsettled_waking if s <= through and s in ids]
            return settled(entry_id, named or ["x"], through, reply_id=open_reply, outcome=outcome)

        options.append(st.tuples(throughs, outcomes).map(_settle))
    return data.draw(st.one_of(options))


def _assert_agrees(state: ConversationState) -> None:
    lifecycles = state.lifecycles
    assert lifecycles is not None
    work = [item for item in state.work if not _ghost(item)]
    assert [run.task_id for run in lifecycles.runs] == [item.task_id for item in work]
    for item, run in zip(work, lifecycles.runs, strict=True):
        assert run.joined == item.joined
        assert run.answers == item.answers
        assert isinstance(run.status, RunParked) is (item.ended and bool(item.pending_approvals))
        assert isinstance(run.status, RunAwaitingApproval) is (
            not item.ended and bool(item.pending_approvals)
        )
    assert views.asking(lifecycles) == state.asking
    attempt = lifecycles.attempt
    assert (attempt and attempt.reply_id) == state.open_reply
    assert (attempt and attempt.seq) == state.open_reply_seq
    assert views.unsettled_waking(lifecycles) == state.unsettled_waking
    assert [
        (result.task_id, result.cause_from, result.cause_through, result.answers)
        for result in views.finished_work(lifecycles)
    ] == [(w.task_id, w.cause_from, w.cause_through, w.answers) for w in state.finished_work]
    ghost_answers = {a for item in state.work if _ghost(item) for a in item.answers}
    assert views.owed_answers(lifecycles) | ghost_answers == state.owed_answers
    if len(work) == len(state.work):
        assert views.display(lifecycles) == state.display


@given(st.data())
def test_the_lifecycles_agree_with_the_legacy_fields_on_every_prefix(data: st.DataObject) -> None:
    state = FOLDED
    ids: dict[int, str] = {}
    for _ in range(data.draw(st.integers(1, 40))):
        seq = state.head + 1
        entry = _next_entry(data, state, seq, ids)
        result = reduce(state, logged(seq, entry))
        assert isinstance(result, Transition), (entry, result)
        state = result.state
        if entry.kind == "user_message":
            ids[seq] = entry.id
        _assert_agrees(state)


def test_a_head_folded_before_lifecycles_keeps_none() -> None:
    result = reduce(EMPTY, logged(1, user("u1")))
    assert isinstance(result, Transition)
    assert result.state.lifecycles is None


def test_a_parked_run_whose_last_approval_is_cancelled_ends_with_it() -> None:
    entries: list[Entry] = [
        user("u1"),
        WorkStarted(id="w", task_id="t", cause_through=1),
        asked("a", "t", "ap"),
        finished("f", "t", continued_by_decision=True),
        _decision("d", "ap", ApprovalOutcome.CANCELLED, None),
    ]
    state = FOLDED
    for seq, entry in enumerate(entries, start=1):
        result = reduce(state, logged(seq, entry))
        assert isinstance(result, Transition)
        state = result.state
    assert state.lifecycles is not None
    assert state.lifecycles.runs == ()
    assert [item.task_id for item in state.work] == ["t"]  # legacy keeps a run nothing can end


def test_a_run_that_ends_with_its_approval_open_takes_the_approval_with_it() -> None:
    entries: list[Entry] = [
        user("u1"),
        WorkStarted(id="w", task_id="t", cause_through=1),
        asked("a", "t", "ap"),
        finished("f", "t"),
    ]
    state = FOLDED
    for seq, entry in enumerate(entries, start=1):
        result = reduce(state, logged(seq, entry))
        assert isinstance(result, Transition)
        state = result.state
    assert state.lifecycles is not None
    assert state.lifecycles.approvals == ()
    assert views.asking(state.lifecycles) == ()
