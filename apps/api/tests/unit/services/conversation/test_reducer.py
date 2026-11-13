"""reduce: one test per rule, accept and reject side, then whole-log scenarios."""

import pytest

from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import (
    CancelWork,
    CommsPhase,
    ConversationState,
    DisplayState,
    Entry,
    FinishedWork,
    KickStep,
    LiveWork,
    Preempt,
    Reaction,
    Rejected,
    RejectReason,
    ReplyOutcome,
    StartAck,
    StopBy,
    Transition,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.reducer import reduce
from tests.unit.services.conversation.log_helpers import (
    asked,
    barge,
    decided,
    finished,
    fired,
    fold,
    logged,
    notice,
    opened,
    replied,
    settled,
    started,
    stop,
    todo_woke,
    user,
)


def _accept(state: ConversationState, seq: int, entry: Entry) -> Transition:
    result = reduce(state, logged(seq, entry))
    assert isinstance(result, Transition), result
    return result


def _reason(state: ConversationState, seq: int, entry: Entry) -> RejectReason:
    result = reduce(state, logged(seq, entry))
    assert isinstance(result, Rejected), result
    return result.reason


def _work(task_id: str, cause_through: int, *approvals: str) -> LiveWork:
    return LiveWork(
        task_id=task_id,
        cause_through=cause_through,
        answers=(),
        pending_approvals=frozenset(approvals),
    )


# ---- ordering ----


@pytest.mark.parametrize(
    "entry",
    [
        user("m"),
        stop("s"),
        barge("b", "r1"),
        fired("f"),
        todo_woke("t"),
        notice("n"),
        decided("d", "ap"),
        finished("w", "t9"),
        opened("o"),
        started("ws", "t1", 2),
    ],
)
def test_every_accepted_entry_sets_head_to_its_seq(entry: Entry) -> None:
    state, _ = fold([user("u1"), user("u2")])
    assert _accept(state, 3, entry).state.head == 3


@pytest.mark.parametrize("seq", [1, 2, 4, 9])
def test_entry_whose_seq_is_not_head_plus_one_is_rejected_out_of_order(seq: int) -> None:
    state, _ = fold([user("u1"), user("u2")])
    assert _reason(state, seq, user("late")) is RejectReason.OUT_OF_ORDER


# ---- UserMessage ----


@pytest.mark.parametrize(
    ("voice", "effects"),
    [(False, (KickStep(), StartAck(message_id="m"))), (True, (KickStep(),))],
)
def test_user_message_wakes_and_acks_unless_voice(voice: bool, effects: tuple[object, ...]) -> None:
    state, _ = fold([user("u1")])
    result = _accept(state, 2, user("m", voice=voice))
    assert result.state.unsettled_waking == (1, 2)
    assert result.effects == effects


def test_a_reaction_or_revision_on_a_user_message_never_changes_state() -> None:
    plain = user("m")
    decorated = plain.model_copy(
        update={"reaction": Reaction(emoji="🔥", by=ReactionBy.CHAT_MODEL), "revision": 4}
    )
    state, _ = fold([user("u1")])
    assert _accept(state, 2, plain) == _accept(state, 2, decorated)


# ---- StopRequested ----


def test_stop_without_covers_through_covers_everything_before_it() -> None:
    state, _ = fold([user("u1"), user("u2")])
    result = _accept(state, 3, stop("s"))
    assert result.state.stopped_through == 2
    assert result.state.unsettled_waking == ()
    assert result.effects == (Preempt(stop_through=2),)


def test_stop_with_covers_through_drops_only_waking_at_or_before_it() -> None:
    state, _ = fold([user("u1"), user("u2"), user("u3")])
    result = _accept(state, 4, stop("s", covers_through=2))
    assert result.state.stopped_through == 2
    assert result.state.unsettled_waking == (3,)
    assert result.effects == (Preempt(stop_through=2),)


def test_stop_never_lowers_stopped_through() -> None:
    state, _ = fold([user("u1"), user("u2"), stop("s1"), user("u4")])
    result = _accept(state, 5, stop("s2", covers_through=1))
    assert result.state.stopped_through == 2
    assert result.state.unsettled_waking == (4,)
    assert result.effects == (Preempt(stop_through=1),)


def test_stop_cancels_exactly_the_work_caused_at_or_before_it() -> None:
    state, _ = fold(
        [
            user("u1"),
            started("w1", "t1", 1),
            user("u3"),
            started("w2", "t2", 3),
            user("u5"),
            started("w3", "t3", 5),
        ]
    )
    result = _accept(state, 7, stop("s", covers_through=3))
    assert [item.task_id for item in result.state.work] == ["t3"]
    assert result.effects == (Preempt(stop_through=3), CancelWork(task_ids=("t1", "t2")))


def test_stop_leaves_work_caused_after_it_untouched_and_emits_no_cancel() -> None:
    state, _ = fold([user("u1"), user("u2"), started("w", "t1", 2)])
    result = _accept(state, 4, stop("s", covers_through=1))
    assert result.state.work == state.work
    assert result.effects == (Preempt(stop_through=1),)


@pytest.mark.parametrize("covers_through", [3, 4])
def test_stop_covering_itself_or_later_is_rejected(covers_through: int) -> None:
    state, _ = fold([user("u1"), user("u2")])
    assert (
        _reason(state, 3, stop("s", covers_through=covers_through))
        is RejectReason.STOP_COVERS_FUTURE
    )


def test_stop_leaves_comms_for_the_reply_end_to_settle() -> None:
    state, _ = fold([user("u1"), opened("o")])
    assert _accept(state, 3, stop("s")).state.comms is CommsPhase.ANSWERING


# ---- BargeIn, WorkflowFired, TodoWoke, Notice ----


def test_barge_in_on_the_open_reply_preempts_it_and_waits_for_the_users_words() -> None:
    state, _ = fold([user("u1"), opened("o", reply_id="r1")])
    result = _accept(state, 3, barge("b", "r1"))
    assert result.state.unsettled_waking == (1,)
    assert result.effects == (Preempt(barge_reply_id="r1"), KickStep())


def test_barge_in_on_a_settled_reply_kicks_the_step_to_cut_it_without_preempting() -> None:
    state, _ = fold([user("u1"), opened("o", reply_id="r1"), settled("s", ("u1",), 1)])
    result = _accept(state, 4, barge("b", "r1"))
    assert result.state.unsettled_waking == ()
    assert result.effects == (KickStep(),)


def test_workflow_fired_wakes_and_kicks_without_an_ack() -> None:
    state, _ = fold([user("u1")])
    result = _accept(state, 2, fired("f"))
    assert result.state.unsettled_waking == (1, 2)
    assert result.effects == (KickStep(),)


def test_a_fire_while_the_previous_fire_is_unanswered_is_refused() -> None:
    state, _ = fold([fired("f1", "ex_1")])
    assert _reason(state, 2, fired("f2", "ex_2")) is RejectReason.FIRE_OVERLAPS


def test_a_fire_while_work_still_runs_in_its_conversation_is_refused() -> None:
    state, _ = fold(
        [fired("f1", "ex_1"), started("w", "t1", 1), opened("o"), settled("s", ("f1",), 1)]
    )
    assert _reason(state, 5, fired("f2", "ex_2")) is RejectReason.FIRE_OVERLAPS


def test_a_fire_after_the_previous_one_was_answered_and_its_work_ended_wakes() -> None:
    state, _ = fold(
        [
            fired("f1", "ex_1"),
            started("w", "t1", 1),
            opened("o"),
            settled("s", ("f1",), 1),
            finished("d", "t1", WorkOutcome.CANCELLED),
        ]
    )
    assert _accept(state, 6, fired("f2", "ex_2")).state.unsettled_waking == (6,)


def test_a_stop_covering_a_fire_lets_the_next_fire_in() -> None:
    state, _ = fold([fired("f1", "ex_1"), stop("s")])
    assert _accept(state, 3, fired("f2", "ex_2")).state.unsettled_waking == (3,)


@pytest.mark.parametrize("entry", [todo_woke("t"), notice("n")])
def test_todo_woke_and_notice_move_only_the_head(entry: Entry) -> None:
    state, _ = fold([user("u1"), started("w", "t1", 1)])
    result = _accept(state, 3, entry)
    assert result.state == state.model_copy(update={"head": 3})
    assert result.effects == ()


# ---- WorkStarted ----


def test_work_started_appends_live_work_with_its_answers() -> None:
    state, _ = fold([user("u1"), user("u2")])
    entry = started("w", "t1", 2).model_copy(update={"answers": ("u1", "u2")})
    result = _accept(state, 3, entry)
    assert result.state.work == (
        LiveWork(
            task_id="t1", cause_through=2, answers=("u1", "u2"), pending_approvals=frozenset()
        ),
    )
    assert result.effects == ()


@pytest.mark.parametrize(("cause_through", "accepted"), [(1, False), (2, True)])
def test_work_started_is_rejected_when_its_cause_was_stopped(
    cause_through: int, accepted: bool
) -> None:
    state, _ = fold([user("u1"), stop("s"), user("u3")])
    result = reduce(state, logged(4, started("w", "t1", cause_through)))
    assert isinstance(result, Transition) is accepted
    if not accepted:
        assert result == Rejected(reason=RejectReason.CAUSE_STOPPED)


def test_work_started_is_rejected_when_the_task_is_already_live() -> None:
    state, _ = fold([user("u1"), started("w1", "t1", 1)])
    assert _reason(state, 3, started("w2", "t1", 1)) is RejectReason.TASK_ALREADY_LIVE
    assert isinstance(reduce(state, logged(3, started("w2", "t2", 1))), Transition)


def _joining(entry_id: str, task_id: str, cause_through: int, joins: str) -> WorkStarted:
    return started(entry_id, task_id, cause_through).model_copy(
        update={"answers": ("u3",), "joins": joins}
    )


def test_work_handed_to_running_work_joins_it_and_answers_with_it() -> None:
    first = started("w1", "t1", 1).model_copy(update={"answers": ("u1",)})
    state, _ = fold([user("u1"), first, user("u3")])
    result = _accept(state, 4, _joining("w2", "t2", 3, "t1"))
    assert result.state.work == (
        LiveWork(
            task_id="t1",
            cause_through=1,
            answers=("u1", "u3"),
            pending_approvals=frozenset(),
            joined=("t2",),
        ),
    )
    assert result.effects == ()


def test_work_joining_work_that_is_not_live_is_rejected() -> None:
    state, _ = fold([user("u1"), user("u2"), user("u3")])
    assert _reason(state, 4, _joining("w2", "t2", 3, "t1")) is RejectReason.TASK_NOT_LIVE


def test_a_stop_covering_joined_work_cancels_every_task_handed_to_it() -> None:
    state, _ = fold([user("u1"), started("w1", "t1", 1), user("u3"), _joining("w2", "t2", 3, "t1")])
    result = _accept(state, 5, stop("s"))
    assert CancelWork(task_ids=("t1", "t2")) in result.effects
    assert result.state.work == ()


@pytest.mark.parametrize("cause_through", [3, 5])
def test_work_started_whose_cause_is_not_before_it_is_rejected(cause_through: int) -> None:
    state, _ = fold([user("u1"), user("u2")])
    assert (
        _reason(state, 3, started("w", "t1", cause_through)) is RejectReason.CAUSE_NOT_BEFORE_WORK
    )


# ---- ApprovalRequested / ApprovalDecided ----


def test_approval_requested_adds_the_approval_to_its_task_only() -> None:
    state, _ = fold([user("u1"), started("w1", "t1", 1), started("w2", "t2", 1)])
    result = _accept(state, 4, asked("a", "t2", "ap1"))
    assert result.state.work == (_work("t1", 1), _work("t2", 1, "ap1"))
    assert result.effects == ()


def test_approval_requested_for_a_task_not_live_is_rejected() -> None:
    state, _ = fold([user("u1"), started("w1", "t1", 1)])
    assert _reason(state, 3, asked("a", "t9", "ap1")) is RejectReason.TASK_NOT_LIVE


def test_approval_decided_removes_the_approval_from_whichever_task_holds_it() -> None:
    state, _ = fold(
        [
            user("u1"),
            started("w1", "t1", 1),
            started("w2", "t2", 1),
            asked("a1", "t1", "ap1"),
            asked("a2", "t2", "ap2"),
            asked("a3", "t2", "ap3"),
        ]
    )
    result = _accept(state, 7, decided("d", "ap2"))
    assert result.state.work == (_work("t1", 1, "ap1"), _work("t2", 1, "ap3"))
    assert result.effects == ()


def test_approval_decided_with_no_holder_is_accepted_and_changes_nothing_else() -> None:
    state, _ = fold([user("u1"), started("w1", "t1", 1), asked("a", "t1", "ap1"), stop("s")])
    result = _accept(state, 5, decided("d", "ap1"))
    assert result.state == state.model_copy(update={"head": 5})
    assert result.effects == ()


# ---- WorkFinished ----


@pytest.mark.parametrize("outcome", [WorkOutcome.DONE, WorkOutcome.FAILED, WorkOutcome.LOST])
def test_live_work_finishing_removes_it_and_wakes(outcome: WorkOutcome) -> None:
    state, _ = fold(
        [user("u1"), started("w1", "t1", 1), started("w2", "t2", 1), *replied("r", ["u1"], 1)]
    )
    result = _accept(state, 6, finished("f", "t1", outcome))
    assert [item.task_id for item in result.state.work] == ["t2"]
    assert result.state.unsettled_waking == (6,)
    assert result.effects == (KickStep(),)


def test_live_work_finishing_cancelled_removes_it_without_waking() -> None:
    state, _ = fold([user("u1"), started("w", "t1", 1), *replied("r", ["u1"], 1)])
    result = _accept(state, 5, finished("f", "t1", WorkOutcome.CANCELLED))
    assert result.state.work == ()
    assert result.state.unsettled_waking == ()
    assert result.effects == ()


@pytest.mark.parametrize("outcome", list(WorkOutcome))
def test_work_finishing_after_it_was_stopped_neither_wakes_nor_kicks(outcome: WorkOutcome) -> None:
    state, _ = fold([user("u1"), started("w", "t1", 1), stop("s")])
    result = _accept(state, 4, finished("f", "t1", outcome))
    assert result.state == state.model_copy(update={"head": 4})
    assert result.effects == ()


# ---- Reply and ReplySettled ----


def test_reply_opens_comms_answering_and_settles_nothing() -> None:
    state, _ = fold([user("u1")])
    result = _accept(state, 2, opened("o", reply_id="r9"))
    assert (result.state.comms, result.state.open_reply) == (CommsPhase.ANSWERING, "r9")
    assert (result.state.settled_through, result.state.unsettled_waking) == (0, (1,))
    assert result.effects == ()


def test_a_second_reply_while_one_is_open_is_rejected() -> None:
    state, _ = fold([user("u1"), opened("o1", reply_id="r1")])
    assert _reason(state, 3, opened("o2", reply_id="r2")) is RejectReason.REPLY_ALREADY_OPEN


def test_reply_settled_sets_comms_idle_and_settles_through_its_newest_answer() -> None:
    state, _ = fold([user("u1"), user("u2"), user("u3"), opened("o")])
    result = _accept(state, 5, settled("r", ["u1", "u2"], 2))
    assert (result.state.comms, result.state.open_reply) == (CommsPhase.IDLE, None)
    assert result.state.settled_through == 2
    assert result.state.unsettled_waking == (3,)
    assert result.effects == ()


@pytest.mark.parametrize("outcome", list(ReplyOutcome))
def test_every_settled_outcome_settles(outcome: ReplyOutcome) -> None:
    state, _ = fold([user("u1"), opened("o")])
    assert _accept(state, 3, settled("r", ["u1"], 1, outcome=outcome)).state.settled_through == 1


@pytest.mark.parametrize(("open_reply", "settled_reply"), [(None, "r1"), ("r1", "r2")])
def test_reply_settled_for_a_reply_that_is_not_open_is_rejected(
    open_reply: str | None, settled_reply: str
) -> None:
    log: list[Entry] = (
        [user("u1")] if open_reply is None else [user("u1"), opened("o", reply_id=open_reply)]
    )
    state, _ = fold(log)
    result = reduce(state, logged(len(log) + 1, settled("r", ["u1"], 1, reply_id=settled_reply)))
    assert result == Rejected(reason=RejectReason.REPLY_NOT_OPEN)


def test_reply_settled_never_lowers_settled_through() -> None:
    state, _ = fold(
        [user("u1"), user("u2"), *replied("r1", ["u2"], 2), user("u5"), opened("o2", reply_id="r2")]
    )
    result = _accept(state, 7, settled("r2", ["u1"], 1, reply_id="r2"))
    assert result.state.settled_through == 2
    assert result.state.unsettled_waking == (5,)


@pytest.mark.parametrize("through", [3, 4])
def test_reply_settled_answering_itself_or_later_is_rejected(through: int) -> None:
    state, _ = fold([user("u1"), opened("o")])
    assert _reason(state, 3, settled("r", ["u1"], through)) is RejectReason.REPLY_ANSWERS_FUTURE


# ---- comms phase owned by the step ----


def test_reduce_keeps_the_thinking_phase_the_step_set_until_a_reply() -> None:
    thinking = fold([user("u1")])[0].model_copy(update={"comms": CommsPhase.THINKING})
    assert _accept(thinking, 2, user("u2")).state.comms is CommsPhase.THINKING
    assert _accept(thinking, 2, opened("o")).state.comms is CommsPhase.ANSWERING


# ---- whole-log scenarios ----


def test_two_user_messages_then_one_reply_answering_both() -> None:
    state, effects = fold([user("u1"), user("u2"), *replied("r", ["u1", "u2"], 2)])
    assert state == ConversationState(
        head=4,
        settled_through=2,
        stopped_through=0,
        unsettled_waking=(),
        comms=CommsPhase.IDLE,
        open_reply=None,
        work=(),
    )
    assert effects == [KickStep(), StartAck(message_id="u1"), KickStep(), StartAck(message_id="u2")]


def test_a_reply_to_the_first_message_then_a_second_reply() -> None:
    log: list[Entry] = [user("u1"), user("u2"), *replied("r1", ["u1"], 1, reply_id="r1")]
    first, _ = fold(log)
    assert (first.settled_through, first.unsettled_waking) == (1, (2,))
    state, _ = fold([*log, *replied("r2", ["u2"], 2, reply_id="r2")])
    assert (state.settled_through, state.unsettled_waking, state.comms) == (2, (), CommsPhase.IDLE)


def test_side_question_is_answered_while_work_stays_live() -> None:
    state, effects = fold(
        [
            user("u1"),
            started("w", "t1", 1),
            *replied("r1", ["u1"], 1, reply_id="r1"),
            user("u5"),
            *replied("r2", ["u5"], 5, reply_id="r2"),
        ]
    )
    assert state.work == (_work("t1", 1),)
    assert (state.settled_through, state.unsettled_waking) == (5, ())
    assert state.display is DisplayState.WORKING
    assert effects == [KickStep(), StartAck(message_id="u1"), KickStep(), StartAck(message_id="u5")]


def test_approval_requested_then_decided() -> None:
    log: list[Entry] = [
        user("u1"),
        started("w", "t1", 1),
        *replied("r", ["u1"], 1),
        asked("a", "t1", "ap1"),
    ]
    waiting, _ = fold(log)
    assert waiting.display is DisplayState.AWAITING_APPROVAL
    state, effects = fold([*log, decided("d", "ap1")])
    assert state.work == (_work("t1", 1),)
    assert state.display is DisplayState.WORKING
    assert effects == [KickStep(), StartAck(message_id="u1")]


def test_approval_requested_then_stop_cancels_the_waiting_task() -> None:
    state, effects = fold([user("u1"), started("w", "t1", 1), asked("a", "t1", "ap1"), stop("s")])
    assert state == ConversationState(
        head=4,
        settled_through=0,
        stopped_through=3,
        unsettled_waking=(),
        comms=CommsPhase.IDLE,
        open_reply=None,
        work=(),
    )
    assert effects[-2:] == [
        Preempt(stop_through=3),
        CancelWork(task_ids=("t1",), approval_ids=("ap1",)),
    ]


def test_result_arriving_while_a_reply_is_open_stays_waking_past_that_reply() -> None:
    log: list[Entry] = [
        user("u1"),
        started("w", "t1", 1),
        *replied("r1", ["u1"], 1, reply_id="r1"),
        user("u5"),
        opened("o", reply_id="r2"),
        finished("f", "t1"),
    ]
    during, effects = fold(log)
    assert (during.comms, during.work, during.unsettled_waking) == (
        CommsPhase.ANSWERING,
        (),
        (5, 7),
    )
    assert effects[-1] == KickStep()
    state, _ = fold([*log, settled("s2", ["u5"], 5, reply_id="r2")])
    assert (state.settled_through, state.unsettled_waking, state.comms) == (
        5,
        (7,),
        CommsPhase.IDLE,
    )


def test_stop_while_a_reply_is_open() -> None:
    state, effects = fold(
        [user("u1"), opened("o"), stop("s"), settled("r", ["u1"], 1, outcome=ReplyOutcome.STOPPED)]
    )
    assert state == ConversationState(
        head=4,
        settled_through=1,
        stopped_through=2,
        unsettled_waking=(),
        comms=CommsPhase.IDLE,
        open_reply=None,
        work=(),
    )
    assert effects == [KickStep(), StartAck(message_id="u1"), Preempt(stop_through=2)]


def test_stopped_reply_may_settle_answering_nothing() -> None:
    state, _ = fold(
        [user("u1"), opened("o"), stop("s"), settled("r", [], 1, outcome=ReplyOutcome.STOPPED)]
    )
    assert (state.comms, state.open_reply, state.settled_through) == (CommsPhase.IDLE, None, 1)


def test_work_started_after_a_stop_survives_it() -> None:
    log: list[Entry] = [
        user("u1"),
        started("w1", "t1", 1),
        stop("s"),
        user("u4"),
        started("w2", "t2", 4),
    ]
    state, effects = fold(log)
    assert state.work == (_work("t2", 4),)
    assert state.unsettled_waking == (4,)
    assert effects.count(CancelWork(task_ids=("t1",))) == 1
    assert not any(isinstance(effect, CancelWork) and "t2" in effect.task_ids for effect in effects)


def test_rebuilding_a_log_with_a_stop_gives_the_same_stop_and_work() -> None:
    log: list[Entry] = [
        user("u1"),
        started("w1", "t1", 1),
        stop("s"),
        user("u4"),
        started("w2", "t2", 4),
    ]
    first, _ = fold(log)
    second, _ = fold(log)
    assert (
        (first.stopped_through, first.work)
        == (second.stopped_through, second.work)
        == (2, (_work("t2", 4),))
    )


def test_gaia_stop_covering_up_to_its_batch_leaves_the_batch_waking() -> None:
    batch_start = 5
    state, effects = fold(
        [
            user("u1"),
            started("w", "t1", 1),
            *replied("r", ["u1"], 1),
            user("stop that"),
            stop("s", covers_through=batch_start - 1, by=StopBy.GAIA),
        ]
    )
    assert state.unsettled_waking == (batch_start,)
    assert (state.stopped_through, state.work) == (4, ())
    assert effects[-2:] == [Preempt(stop_through=4), CancelWork(task_ids=("t1",))]


def test_ten_user_messages_then_one_reply() -> None:
    ids = [f"u{n}" for n in range(1, 11)]
    state, effects = fold([*(user(entry_id) for entry_id in ids), *replied("r", ids, 10)])
    assert (state.head, state.settled_through, state.unsettled_waking) == (12, 10, ())
    assert effects == [
        effect for entry_id in ids for effect in (KickStep(), StartAck(message_id=entry_id))
    ]


def test_workflow_fire_between_two_user_messages_settles_in_order() -> None:
    log: list[Entry] = [user("u1"), fired("f"), user("u3")]
    state, effects = fold(log)
    assert state.unsettled_waking == (1, 2, 3)
    assert effects == [
        KickStep(),
        StartAck(message_id="u1"),
        KickStep(),
        KickStep(),
        StartAck(message_id="u3"),
    ]
    after_first, _ = fold([*log, *replied("r", ["u1"], 1)])
    assert after_first.unsettled_waking == (2, 3)


def test_wake_up_entry_in_the_middle_of_work_changes_nothing_until_the_work_finishes() -> None:
    log: list[Entry] = [user("u1"), started("w", "t1", 1), *replied("r", ["u1"], 1), todo_woke("t")]
    during, effects = fold(log)
    assert (during.work, during.unsettled_waking) == ((_work("t1", 1),), ())
    assert len(effects) == 2
    state, effects = fold([*log, finished("f", "t1")])
    assert (state.work, state.unsettled_waking, effects[-1]) == ((), (6,), KickStep())


# ---- causes of finished work, kept until a reply answers it ----


def test_finished_work_keeps_the_messages_that_caused_it_until_a_reply_settles_it() -> None:
    work_started = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u1",))
    log: list[Entry] = [user("u1"), work_started, *replied("r", ["u1"], 1), finished("f", "t1")]
    during, _ = fold(log)
    assert during.finished_work == (
        FinishedWork(seq=5, task_id="t1", cause_through=1, answers=("u1",)),
    )
    state, _ = fold([*log, *replied("r2", ["f", "u1"], 5, reply_id="r2")])
    assert state.finished_work == ()


def test_cancelled_work_leaves_no_finished_work_to_answer() -> None:
    log: list[Entry] = [user("u1"), started("w", "t1", 1), *replied("r", ["u1"], 1)]
    state, _ = fold([*log, finished("f", "t1", WorkOutcome.CANCELLED)])
    assert state.finished_work == ()


def test_a_stop_drops_the_finished_work_it_covers() -> None:
    log: list[Entry] = [user("u1"), started("w", "t1", 1), *replied("r", ["u1"], 1)]
    state, _ = fold([*log, finished("f", "t1"), stop("s")])
    assert (state.finished_work, state.unsettled_waking) == ((), ())


def test_a_recovered_reply_fails_without_settling_its_inputs() -> None:
    recovered = settled("s", [], 0, outcome=ReplyOutcome.FAILED)
    state, _ = fold([user("u1"), opened("o"), recovered])
    assert (state.open_reply, state.settled_through, state.unsettled_waking) == (None, 0, (1,))


def test_an_accepted_message_shows_gaia_thinking_before_a_step_picks_it_up() -> None:
    state, _ = fold([user("u1")])
    assert state.comms is CommsPhase.IDLE
    assert state.display is DisplayState.THINKING


def test_a_conversation_with_nothing_unsettled_and_no_work_is_idle() -> None:
    state, _ = fold([user("u1"), stop("s")])
    assert state.display is DisplayState.IDLE
