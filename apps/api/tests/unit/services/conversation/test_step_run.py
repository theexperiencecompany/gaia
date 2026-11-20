"""One attempt's run, scenario by scenario: a run that cannot start, a claim lost mid-run, store failures, joiners and the run's end."""

import asyncio

import pytest

from app.agents.core.comms_ledger import named
from app.models.conversation_frame_models import ResponseEvent, RetractFrame
from app.models.conversation_log_models import (
    CommsPhase,
    Entry,
    LoggedEntry,
    PreemptHint,
    Reply,
    ReplySettled,
    StepClaim,
    StopBy,
    UserMessage,
)
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    Answered,
    Appended,
    CancelReason,
    Finished,
    ModelOutput,
    Replied,
    Silent,
    Streamed,
)
from app.services.conversation.step import advance
from app.utils.hot_path import after_first_text
from shared.py.conversation_wire import ReplyOutcome
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import fired, stop, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Absorbed,
    Action,
    Cancelled,
    Close,
    Do,
    Fail,
    Forgetful,
    Runtime,
    ScriptedRun,
    Started,
)

LOST = Cancelled(CancelReason.LOST)


def text(chunk: str) -> Streamed:
    return Streamed(payload=ResponseEvent(response=chunk))


async def send(rt: Runtime, *entries: Entry) -> None:
    for entry in entries:
        await accept(rt.ports, CONVERSATION, USER, entry)


def arrive(rt: Runtime, *entries: Entry) -> Action:
    async def action() -> None:
        await send(rt, *entries)

    return action


async def run(rt: Runtime) -> None:
    await advance(rt.ports, CONVERSATION, USER)


async def replies(rt: Runtime) -> list[Reply]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, Reply)]


async def settles(rt: Runtime) -> list[ReplySettled]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, ReplySettled)]


def lose_the_claim_at(rt: Runtime, point: str) -> None:
    """At the first call named point, let the holder lapse and another step take the claim."""
    taken: list[bool] = []

    async def take_over(at: str) -> None:
        if at == point and not taken:
            taken.append(True)
            await rt.lapse()
            assert await rt.log.claim(CONVERSATION, USER) is not None

    rt.log.pause = take_over


async def test_a_run_that_cannot_start_fails_its_inputs_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()

    async def cannot_start(*_args: object, **_kwargs: object) -> ScriptedRun:
        raise RuntimeError("model down")

    monkeypatch.setattr(rt.runner, "start", cannot_start)
    await send(rt, user("u1"))
    async with captured_wide_event() as event:
        await run(rt)
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.FAILED, ("u1",))
    ]
    assert [(error["error"], error["error_type"]) for error in event["errors"]] == [
        ("model down", "RuntimeError")
    ]


async def test_an_attempt_is_thinking_once_its_run_starts() -> None:
    rt = Runtime()
    phases: list[CommsPhase] = []

    async def note_phase() -> None:
        phases.append((await rt.log.state(CONVERSATION, USER)).comms)

    rt.runner.script([Do(note_phase), Finished(Replied("hi"))])
    await send(rt, user("u1"))
    await run(rt)
    assert phases == [CommsPhase.THINKING]


async def test_a_claim_lost_before_anything_showed_withdraws_the_attempt() -> None:
    rt = Runtime()
    rt.runner.script([text("hello")])
    await send(rt, user("u1"))
    lose_the_claim_at(rt, "append_fenced")
    await run(rt)
    assert rt.runner.calls[-1] == LOST
    assert RetractFrame(attempt_id="1.1") in rt.frames.published
    assert [item.entry.id for item in await rt.entries()] == ["u1"]


async def test_a_claim_lost_after_the_reply_showed_leaves_it_to_the_next_holder() -> None:
    rt = Runtime()
    rt.runner.script([text("a"), Do(arrive(rt, user("u2"))), ModelOutput(True), text("b")])
    await send(rt, user("u1"))
    lose_the_claim_at(rt, "amend")
    await run(rt)
    assert rt.runner.calls[-1] == LOST
    assert not [frame for frame in rt.frames.published if isinstance(frame, RetractFrame)]
    assert [reply.text for reply in await replies(rt)] == ["a"]


async def test_a_store_failure_mid_attempt_ends_the_shown_reply_and_fails_every_open_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    rt.runner.script([text("a"), Do(arrive(rt, user("u2"))), ModelOutput(True), text("b")])
    await send(rt, user("u1"))
    hint = rt.log.hint

    async def fail_once_u2_was_handed(conversation_id: str, user_id: str) -> PreemptHint:
        if Absorbed((3,)) in rt.runner.calls:
            raise RuntimeError("store down")
        return await hint(conversation_id, user_id)

    monkeypatch.setattr(rt.log, "hint", fail_once_u2_was_handed)
    async with captured_wide_event() as event:
        await run(rt)
    assert LOST in rt.runner.calls
    assert [(item.outcome, item.answers) for item in await settles(rt)][:2] == [
        (ReplyOutcome.INTERIM, ()),
        (ReplyOutcome.FAILED, ("u1", "u2")),
    ]
    assert [error["error"] for error in event["errors"]] == ["store down"]


async def test_a_settle_that_fails_part_way_is_finished_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    rt.runner.script([text("hi"), Finished(Replied("hi"))])
    await send(rt, user("u1"))
    append_fenced = rt.log.append_fenced
    failed: list[bool] = []

    async def fail_the_first_settle(claim: StepClaim, entry: Entry) -> Appended:
        if isinstance(entry, ReplySettled) and not failed:
            failed.append(True)
            raise RuntimeError("store down")
        return await append_fenced(claim, entry)

    monkeypatch.setattr(rt.log, "append_fenced", fail_the_first_settle)
    async with captured_wide_event() as event:
        await run(rt)
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.FAILED, ("u1",))
    ]
    assert [error["error"] for error in event["errors"]] == ["store down"]


async def test_what_streams_after_the_answer_settled_is_skipped_until_the_follow_ups() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            text("done"),
            Answered(Replied("done")),
            text(" and more"),
            Finished(Replied("done", follow_up_actions=("Book it",))),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    [reply] = await replies(rt)
    assert (reply.text, reply.follow_up_actions) == ("done", ("Book it",))


async def test_a_message_after_another_groups_input_never_joins_the_run() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            ModelOutput(False),
            Do(arrive(rt, fired("wf1"), user("u2"))),
            text("a"),
            ModelOutput(True),
            Finished(Replied("a")),
        ],
        [Finished(Replied("for wf1"))],
        [Finished(Replied("for u2"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert not [call for call in rt.runner.calls if isinstance(call, Absorbed)]
    assert [item.answers for item in await settles(rt)] == [("u1",), ("wf1",), ("u2",)]


async def test_a_message_after_a_stop_never_joins_the_run() -> None:
    rt = Runtime()
    own_stop = stop("s", covers_through=0, by=StopBy.GAIA)
    rt.runner.script(
        [
            ModelOutput(False),
            Do(arrive(rt, own_stop, user("u2"))),
            text("a"),
            ModelOutput(True),
            Finished(Replied("a")),
        ],
        [Finished(Replied("for u2"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert not [call for call in rt.runner.calls if isinstance(call, Absorbed)]
    assert [item.answers for item in await settles(rt)] == [("u1",), ("u2",)]


async def test_the_first_text_releases_the_writes_waiting_on_it() -> None:
    rt = Runtime()
    released: list[bool] = []

    async def note_whether_released() -> None:
        try:
            await asyncio.wait_for(after_first_text(), timeout=1)
        except TimeoutError:
            released.append(False)
        else:
            released.append(True)

    rt.runner.script([text("hi"), Do(note_whether_released), Finished(Replied("hi"))])
    await send(rt, user("u1"))
    await run(rt)
    assert released == [True]


async def test_an_ended_attempt_leaves_no_ledger_for_a_late_closing_tool() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("hi"))])
    await send(rt, user("u1"))
    await run(rt)
    assert named({"configurable": {"comms_run": f"{CONVERSATION}:1.1"}}, [1]) is None


async def test_a_run_crashing_once_its_answer_left_a_message_owed_fails_it_with_no_second_run() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [Forgetful(), Answered(Silent()), Fail(RuntimeError("model down"))],
        [Finished(Replied("late"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), LOST]
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.FAILED, ("u1",))
    ]


async def test_the_second_run_is_told_exactly_the_messages_still_owed_one_per_line() -> None:
    rt = Runtime()
    rt.runner.script(
        [Forgetful(), Close(seqs=(1,)), Finished(Silent())],
        [Close(), Finished(Silent())],
    )
    await send(rt, user("u1"), user("u2"), user("u3"))
    await run(rt)
    _, again = rt.runner.calls
    assert isinstance(again, Started) and again.note is not None
    assert '#2 "text of u2"\n#3 "text of u3"' in again.note
    assert "text of u1" not in again.note


async def test_a_store_failure_after_the_answer_settled_adds_no_failed_reply_under_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    rt.runner.script(
        [
            text("done"),
            Answered(Replied("done")),
            Finished(Replied("done", follow_up_actions=("Book it",))),
        ]
    )
    await send(rt, user("u1"))
    amend = rt.log.amend

    async def fail_the_follow_ups(claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
        if isinstance(entry, Reply) and entry.follow_up_actions:
            raise RuntimeError("store down")
        return await amend(claim, entry)

    monkeypatch.setattr(rt.log, "amend", fail_the_follow_ups)
    await run(rt)
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.ANSWERED, ("u1",))
    ]
    assert [reply.text for reply in await replies(rt)] == ["done"]
