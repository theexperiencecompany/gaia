"""Invariants of reduce over randomly generated valid logs."""

from itertools import pairwise

from hypothesis import given, strategies as st

from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    Entry,
    Rejected,
    Transition,
    WorkOutcome,
)
from app.services.conversation.reducer import reduce
from tests.unit.services.conversation.log_helpers import (
    EMPTY,
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


def _next_entry(data: st.DataObject, state: ConversationState, seq: int) -> Entry:
    """Draw an entry that reduce should accept at seq."""
    entry_id = f"e{seq}"
    live = [item.task_id for item in state.work]
    pending = sorted(approval for item in state.work for approval in item.pending_approvals)
    options: list[st.SearchStrategy[Entry]] = [
        st.booleans().map(lambda voice: user(entry_id, voice=voice)),
        (st.none() | st.integers(0, seq - 1)).map(lambda covers: stop(entry_id, covers)),
        st.just(barge(entry_id, "r1")),
        st.just(todo_woke(entry_id)),
        st.just(notice(entry_id)),
        st.sampled_from([*pending, "ap_gone"]).map(lambda approval: decided(entry_id, approval)),
        st.tuples(st.sampled_from([*live, "t_gone"]), st.sampled_from(list(WorkOutcome))).map(
            lambda pair: finished(entry_id, *pair)
        ),
    ]
    if not state.unsettled_fires and not state.work:
        options.append(st.just(fired(entry_id)))
    if state.stopped_through + 1 <= seq - 1:
        causes = st.integers(state.stopped_through + 1, seq - 1)
        options.append(causes.map(lambda cause: started(entry_id, f"t{seq}", cause)))
    if live:
        options.append(st.sampled_from(live).map(lambda task: asked(entry_id, task, f"ap{seq}")))
    if state.open_reply is None:
        options.append(st.just(opened(entry_id, f"r{seq}")))
    else:
        open_reply = state.open_reply
        throughs = st.integers(1, seq - 1)
        options.append(
            throughs.map(lambda through: settled(entry_id, ["x"], through, reply_id=open_reply))
        )
    return data.draw(st.one_of(options))


def _assert_invariants(state: ConversationState) -> None:
    assert state.settled_through <= state.head
    assert state.stopped_through <= state.head
    task_ids = [item.task_id for item in state.work]
    assert len(task_ids) == len(set(task_ids))
    waking = state.unsettled_waking
    assert all(a < b for a, b in pairwise(waking))
    assert all(seq > max(state.settled_through, state.stopped_through) for seq in waking)
    assert set(state.unsettled_fires) <= set(waking)
    assert state.comms is not CommsPhase.THINKING
    assert (state.comms is CommsPhase.ANSWERING) == (state.open_reply is not None)


def _valid_log(data: st.DataObject) -> list[Entry]:
    entries: list[Entry] = []
    state = EMPTY
    for _ in range(data.draw(st.integers(1, 40))):
        seq = state.head + 1
        entry = _next_entry(data, state, seq)
        result = reduce(state, logged(seq, entry))
        assert isinstance(result, Transition), (entry, result)
        state = result.state
        entries.append(entry)
    return entries


def _fold(entries: list[Entry]) -> ConversationState:
    state = EMPTY
    for seq, entry in enumerate(entries, start=1):
        result = reduce(state, logged(seq, entry))
        assert isinstance(result, Transition)
        state = result.state
    return state


@given(st.data())
def test_every_state_of_a_valid_log_keeps_the_invariants(data: st.DataObject) -> None:
    state = EMPTY
    for seq, entry in enumerate(_valid_log(data), start=1):
        result = reduce(state, logged(seq, entry))
        assert isinstance(result, Transition)
        state = result.state
        _assert_invariants(state)


@given(st.data())
def test_reduce_is_deterministic(data: st.DataObject) -> None:
    entries = _valid_log(data)
    state = _fold(entries[:-1])
    last = logged(len(entries), entries[-1]) if entries else None
    if last is not None:
        assert reduce(state, last) == reduce(state, last)


@given(st.data())
def test_folding_the_same_log_twice_gives_equal_states(data: st.DataObject) -> None:
    entries = _valid_log(data)
    assert _fold(entries) == _fold(entries)


@given(st.data())
def test_a_rejected_entry_leaves_the_state_unchanged(data: st.DataObject) -> None:
    state = _fold(_valid_log(data))
    snapshot = state.model_copy(deep=True)
    seq = data.draw(st.integers(1, state.head + 3))
    candidates: list[Entry] = [
        user("x"),
        stop("x", state.head + 1),
        started("x", "t_new", max(1, state.stopped_through)),
        *(started("x", item.task_id, item.cause_through) for item in state.work),
        asked("x", "t_never", "ap"),
        settled("x", ["x"], state.head + 1),
        opened("x"),
    ]
    entry = data.draw(st.sampled_from(candidates))
    result = reduce(state, logged(seq, entry))
    if isinstance(result, Rejected):
        assert state == snapshot
