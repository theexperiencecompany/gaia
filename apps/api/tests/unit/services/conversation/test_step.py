"""The step itself, scenario by scenario: its heartbeat, recovery, batches, silent todo reports, workflow resets and typed approvals."""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import pytest

from app.constants.chat import ConversationSource
from app.constants.conversation import RUNNER_ALIVE_BEATS_PER_TTL, RUNNER_ALIVE_TTL_SECONDS
from app.models.conversation_frame_models import ResponseEvent
from app.models.conversation_log_models import (
    CommsPhase,
    Entry,
    Reply,
    ReplySettled,
    TodoReportForm,
    TodoWoke,
    UserMessage,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation import step
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    Finished,
    FoldPlan,
    ModelOutput,
    Reacted,
    Replied,
    Streamed,
)
from app.utils.liveness import keep_proving
from shared.py.conversation_wire import ReplyOutcome
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import asked, fired, todo_run, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Do,
    EffectCall,
    Runtime,
    Started,
)


async def send(rt: Runtime, *entries: Entry) -> None:
    for entry in entries:
        await accept(rt.ports, CONVERSATION, USER, entry)


def text(chunk: str) -> Streamed:
    return Streamed(payload=ResponseEvent(response=chunk))


async def run(rt: Runtime) -> None:
    await step.advance(rt.ports, CONVERSATION, USER)


async def settles(rt: Runtime) -> list[ReplySettled]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, ReplySettled)]


def counting_log_calls(rt: Runtime) -> Counter[str]:
    calls: Counter[str] = Counter()

    async def count(point: str) -> None:
        if not point.endswith(":done"):
            calls[point] += 1

    rt.log.pause = count
    return calls


@dataclass(frozen=True)
class _Proving:
    prove: Callable[[], Awaitable[bool]]
    every: float
    give_up_after: float
    name: str
    what: str
    context: Mapping[str, str]


def recording_heartbeats(monkeypatch: pytest.MonkeyPatch) -> list[_Proving]:
    """Record every heartbeat the step arms, still arming the real one."""
    armed: list[_Proving] = []

    def record(
        prove: Callable[[], Awaitable[bool]],
        *,
        every: float,
        give_up_after: float,
        name: str,
        what: str,
        context: Mapping[str, str],
    ) -> asyncio.Task[None]:
        armed.append(_Proving(prove, every, give_up_after, name, what, context))
        return keep_proving(
            prove, every=every, give_up_after=give_up_after, name=name, what=what, context=context
        )

    monkeypatch.setattr(step, "keep_proving", record)
    return armed


async def test_a_step_proves_its_claim_often_enough_to_never_let_it_lapse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    armed = recording_heartbeats(monkeypatch)
    proven: list[bool] = []

    async def prove_now() -> None:
        proven.append(await armed[0].prove())

    rt.runner.script([Do(prove_now), Finished(Replied("hi"))])
    await send(rt, user("u1"))
    await run(rt)
    every = RUNNER_ALIVE_TTL_SECONDS / RUNNER_ALIVE_BEATS_PER_TTL
    assert proven == [True]
    assert [(beat.every, beat.give_up_after) for beat in armed] == [
        (every, RUNNER_ALIVE_TTL_SECONDS - every)
    ]
    assert [(beat.name, beat.what, dict(beat.context)) for beat in armed] == [
        (
            "conversation_step_alive",
            "conversation step",
            {"conversation_id": CONVERSATION, "epoch": "1"},
        )
    ]
    # Released: the claim's beat no longer proves anything.
    assert await armed[0].prove() is False


async def test_a_message_landing_as_the_step_releases_rearms_the_heartbeat_and_is_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    armed = recording_heartbeats(monkeypatch)
    rt.runner.script([Finished(Replied("one"))], [Finished(Replied("two"))])
    await send(rt, user("u1"))
    landed: list[str] = []

    async def land_u2_at_release(point: str) -> None:
        if point == "release" and not landed:
            landed.append("u2")
            await send(rt, user("u2"))

    rt.log.pause = land_u2_at_release
    await run(rt)
    assert len(armed) == 2
    assert [item.answers for item in await settles(rt)] == [("u1",), ("u2",)]
    # The re-armed beat proves the same claim, which the step has now released.
    assert await armed[1].prove() is False


async def _dead_holder_left_thinking(rt: Runtime) -> None:
    """u0 got its work started and answered; then a holder set thinking and died."""
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    rt.runner.script([Do(lambda: send(rt, work)), Finished(Replied("on it"))])
    await send(rt, user("u0"))
    await run(rt)
    claim = await rt.log.claim(CONVERSATION, USER)
    assert claim is not None
    await rt.log.set_comms(claim, CommsPhase.THINKING)
    await rt.lapse()


async def test_taking_over_from_a_holder_that_died_between_attempts_only_goes_idle() -> None:
    rt = Runtime()
    await _dead_holder_left_thinking(rt)
    before = [item.entry.id for item in await rt.entries()]
    rt.frames.conversations.clear()
    await run(rt)
    assert [item.entry.id for item in await rt.entries()] == before
    assert (await rt.log.state(CONVERSATION, USER)).comms is CommsPhase.IDLE
    assert set(rt.frames.conversations) == {CONVERSATION}


async def test_a_todo_run_that_found_nothing_settles_silently_without_a_run() -> None:
    rt = Runtime()
    woke = TodoWoke(id="tw", run=todo_run(TodoReportForm.AS_WRITTEN))
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("tw",))
    # The executor runs the todo itself; only its result wakes the step.
    await send(rt, woke, work)
    done = WorkFinished(
        id="f", task_id="t1", outcome=WorkOutcome.DONE, report="nothing new", nothing_for_user=True
    )
    await send(rt, done)
    calls = counting_log_calls(rt)
    await run(rt)
    assert rt.runner.calls == []
    assert [(item.outcome, item.answers) for item in await settles(rt)][-1] == (
        ReplyOutcome.SILENT,
        ("f", "tw"),
    )
    # Served, so the next serve answers from the settled view: one hint, no second unsettled read.
    assert calls == Counter(
        claim=1, unsettled=1, state=1, read_after=2, append_fenced=2, hint=1, release=1
    )


async def test_a_workflow_fire_with_no_live_work_resets_its_threads() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("ran"))])
    await send(rt, fired("wf1"))
    await run(rt)
    assert EffectCall("reset_workflow_threads") in rt.effects.calls
    assert (CONVERSATION, "") in rt.effects.addressed


async def test_only_a_workflow_fire_resets_workflow_threads() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("hi"))])
    await send(rt, user("u1"))
    await run(rt)
    assert EffectCall("reset_workflow_threads") not in rt.effects.calls


async def test_a_workflow_fire_beside_live_work_keeps_its_threads() -> None:
    rt = Runtime()
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    # The fire lands first; the running attempt then hands work off before it is answered.
    rt.runner.script(
        [Do(lambda: send(rt, fired("wf1"), work)), Finished(Replied("on it"))],
        [Finished(Replied("ran"))],
    )
    await send(rt, user("u0"))
    await run(rt)
    assert [item.answers for item in await settles(rt)] == [("u0",), ("wf1",)]
    assert EffectCall("reset_workflow_threads") not in rt.effects.calls


async def test_a_request_live_work_still_owes_rides_every_later_run() -> None:
    rt = Runtime()
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    rt.runner.script(
        [Do(lambda: send(rt, work)), Finished(Replied("on it"))], [Finished(Replied("hi"))]
    )
    await send(rt, user("u0"))
    await run(rt)
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.owed == [frozenset(), frozenset({"u0"})]


async def test_a_fire_waiting_behind_a_message_is_neither_batched_nor_shown_to_its_run() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("hi"))], [Finished(Replied("ran"))])
    await send(rt, user("u1"), fired("wf1"))
    await run(rt)
    assert rt.runner.calls[0] == Started(batch=(1,), context=())
    assert [item.answers for item in await settles(rt)] == [("u1",), ("wf1",)]


async def test_a_typed_approval_answer_is_resolved_with_the_recent_turns_it_follows() -> None:
    rt = Runtime()
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    rt.runner.script([Do(lambda: send(rt, work)), Finished(Replied("on it"))])
    await send(rt, user("u0"))
    await run(rt)
    for turn in range(8):
        rt.runner.script([Finished(Reacted("👍") if turn == 3 else Replied(f"r{turn}"))])
        await send(rt, user(f"m{turn}"))
        await run(rt)
    rt.approvals.decision = "approve"
    typed = UserMessage(id="u6", text="yes do it", surface=ConversationSource.TELEGRAM)
    await send(rt, asked("ask", "t1", "ap1"), typed)
    entries = await rt.entries()
    [first] = [item for item in entries if item.entry.id == "u6"]
    calls = counting_log_calls(rt)
    await run(rt)
    window = [item for item in entries if first.seq - 1 - 20 < item.seq < first.seq]
    expected = [
        {"role": "user", "content": item.entry.text}
        if isinstance(item.entry, UserMessage)
        else {"role": "assistant", "content": item.entry.text}
        for item in window
        if isinstance(item.entry, UserMessage)
        or (isinstance(item.entry, Reply) and item.entry.text)
    ]
    assert rt.approvals.histories == [expected]
    assert len(expected) < len([item for item in entries if item.seq < first.seq]) // 2
    # Served, so the step looks again before releasing: nothing is left, and it lets go.
    assert (calls["unsettled"], calls["release"]) == (2, 1)


async def test_a_message_logged_during_an_attempt_is_found_by_the_next_serve() -> None:
    rt = Runtime()

    async def arrive_u2() -> None:
        await send(rt, user("u2"))

    rt.runner.script(
        [ModelOutput(False), Do(arrive_u2), text("for u1"), Finished(Replied("for u1"))],
        [Finished(Replied("for u2"))],
    )
    await send(rt, user("u1"))
    calls = counting_log_calls(rt)
    await run(rt)
    assert [item.answers for item in await settles(rt)] == [("u1",), ("u2",)]
    # The hint shows u2 past the settled view, so the second serve reads it rather than releasing.
    assert calls == Counter(
        append=1,
        claim=1,
        unsettled=2,
        set_comms=2,
        hint=5,
        read_after=6,
        state=4,
        append_fenced=4,
        amend=1,
        pinned=2,
        release=1,
    )


async def test_a_message_landing_just_after_a_settle_is_served_without_releasing_first() -> None:
    rt = Runtime()
    rt.runner.script([text("hi"), Finished(Replied("hi"))], [Finished(Replied("for u2"))])
    await send(rt, user("u1"))
    hints: list[str] = []
    releases: list[str] = []

    async def land_u2_at_the_third_hint(point: str) -> None:
        if point == "release":
            releases.append(point)
        if point == "hint":
            hints.append(point)
            # Two verdicts read the hint during the attempt; the third is the next serve's.
            if len(hints) == 3:
                await send(rt, user("u2"))

    rt.log.pause = land_u2_at_the_third_hint
    await run(rt)
    assert [item.answers for item in await settles(rt)] == [("u1",), ("u2",)]
    assert releases == ["release"]


_FOLD = FoldPlan(thread=("log:u0",), messages=())


async def test_a_settled_turn_asks_for_a_history_fold_and_never_plans_one_itself() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("hi"))])
    rt.runner.fold_plans = [_FOLD]
    await send(rt, user("u0"))
    await run(rt)
    assert rt.effects.folds == [(CONVERSATION, USER)]
    assert rt.runner.fold_plans == [_FOLD]


async def test_a_history_fold_writes_under_the_claim_then_answers_what_arrived() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("hi"))])
    rt.runner.fold_plans = [_FOLD]
    await send(rt, user("u0"))
    await step.fold_history(rt.ports, CONVERSATION, USER)
    assert [plan for _, plan in rt.runner.applied] == [_FOLD]
    assert [item.answers for item in await settles(rt)] == [("u0",)]
    # Released once caught up: the next step can claim it.
    assert await rt.log.claim(CONVERSATION, USER) is not None


async def test_a_history_fold_is_planned_keeping_what_is_owed_and_pinned() -> None:
    rt = Runtime()
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    rt.runner.script([Do(lambda: send(rt, work)), Finished(Replied("on it"))])
    await send(rt, user("u0").model_copy(update={"pinned": True}))
    await run(rt)
    await step.fold_history(rt.ports, CONVERSATION, USER)
    [(conversation_id, user_id, kept)] = rt.runner.fold_asks
    assert (conversation_id, user_id, kept.owed) == (CONVERSATION, USER, frozenset({"u0"}))
    assert [item.entry.id for item in kept.pinned] == ["u0"]


async def test_a_history_fold_records_that_it_was_applied() -> None:
    rt = Runtime()
    rt.runner.fold_plans = [_FOLD]
    async with captured_wide_event() as event:
        await step.fold_history(rt.ports, CONVERSATION, USER)
    assert event["history_fold"] == {"applied": True}


async def test_a_history_fold_with_nothing_arrived_asks_for_no_further_fold() -> None:
    rt = Runtime()
    rt.runner.fold_plans = [_FOLD]
    await step.fold_history(rt.ports, CONVERSATION, USER)
    assert [plan for _, plan in rt.runner.applied] == [_FOLD]
    assert rt.effects.folds == []


async def test_a_history_fold_whose_step_is_taken_over_ends_quietly() -> None:
    rt = Runtime()

    async def take_over() -> None:
        await rt.lapse()
        assert await rt.log.claim(CONVERSATION, USER) is not None

    rt.runner.script([Do(take_over), text("hi"), Finished(Replied("hi"))])
    rt.runner.fold_plans = [_FOLD]
    await send(rt, user("u0"))
    await step.fold_history(rt.ports, CONVERSATION, USER)
    assert [plan for _, plan in rt.runner.applied] == [_FOLD]
    assert await settles(rt) == []


async def test_a_history_fold_never_writes_while_a_turn_holds_the_step() -> None:
    rt = Runtime()
    rt.runner.fold_plans = [_FOLD]
    await send(rt, user("u0"))
    assert await rt.log.claim(CONVERSATION, USER) is not None
    await step.fold_history(rt.ports, CONVERSATION, USER)
    assert rt.runner.applied == []


async def test_a_pinned_message_rides_every_later_run() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("hi"))], [Finished(Replied("again"))])
    await send(rt, user("u0").model_copy(update={"pinned": True}))
    await run(rt)
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.pinned == [("u0",), ("u0",)]
