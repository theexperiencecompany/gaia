"""entry_outcome: an entry's outcome is final only once nothing it caused is running or unanswered."""

from collections.abc import Sequence

import pytest

from app.models.conversation_log_models import (
    Entry,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.outcome import STOPPED, EntryOutcome, await_outcome, entry_outcome
from tests.unit.services.conversation.log_helpers import (
    finished,
    fired,
    fold,
    logged,
    opened,
    settled,
    stop,
    user,
)
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    FakeClock,
    InMemoryConversationLog,
)


def _work(entry_id: str, task_id: str, cause_through: int, answers: Sequence[str]) -> WorkStarted:
    return WorkStarted(
        id=entry_id, task_id=task_id, cause_through=cause_through, answers=tuple(answers)
    )


def _reply(entry_id: str, reply_id: str, text: str) -> Reply:
    return Reply(id=entry_id, reply_id=reply_id, attempt_id=f"a-{reply_id}", text=text)


def _outcome(entries: Sequence[Entry]) -> EntryOutcome | None:
    state, _ = fold(entries)
    log: list[LoggedEntry] = [logged(seq, entry) for seq, entry in enumerate(entries, start=1)]
    return entry_outcome("wf", 1, log, state)


def test_an_entry_answered_with_no_work_is_final_with_its_reply() -> None:
    outcome = _outcome([fired("wf"), _reply("o1", "r1", "your brief"), settled("s1", ["wf"], 1)])
    assert outcome is not None
    assert (outcome.failure, outcome.text) == (None, "your brief")


def test_an_entry_is_not_final_while_the_work_it_caused_runs() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
    ]
    assert _outcome(entries) is None


def test_an_entry_is_not_final_while_its_finished_work_awaits_its_reply() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
        finished("f1", "t1"),
    ]
    assert _outcome(entries) is None


def test_the_work_reply_that_answers_it_last_is_its_outcome() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
        finished("f1", "t1"),
        _reply("o2", "t1", "here are your emails"),
        settled("s2", ["f1", "wf"], 6, reply_id="t1"),
    ]
    outcome = _outcome(entries)
    assert outcome is not None
    assert (outcome.failure, outcome.text) == (None, "here are your emails")
    assert [work.task_id for work in outcome.work] == ["t1"]


def test_failed_work_fails_the_entry_even_when_its_reply_answered() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
        finished("f1", "t1", WorkOutcome.FAILED),
        _reply("o2", "t1", "it failed"),
        settled("s2", ["f1", "wf"], 5, reply_id="t1"),
    ]
    outcome = _outcome(entries)
    assert outcome is not None
    assert outcome.failure == "work failed: report"


def test_a_failed_reply_fails_the_entry() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _reply("o1", "r1", ""),
        settled("s1", ["wf"], 1, outcome=ReplyOutcome.FAILED),
    ]
    outcome = _outcome(entries)
    assert outcome is not None
    assert outcome.failure == "server_restart"


def test_a_stop_before_any_reply_ends_the_entry_as_stopped() -> None:
    outcome = _outcome([fired("wf"), stop("x")])
    assert outcome is not None
    assert (outcome.failure, outcome.settled) == (STOPPED, None)


def test_a_reply_to_another_input_does_not_finish_the_entry() -> None:
    entries: list[Entry] = [
        user("u1"),
        fired("wf"),
        _reply("o1", "r1", "hi"),
        settled("s1", ["u1"], 1),
    ]
    state, _ = fold(entries)
    log = [logged(seq, entry) for seq, entry in enumerate(entries, start=1)]
    assert entry_outcome("wf", 2, log, state) is None


@pytest.mark.usefixtures("fake_redis")
async def test_an_outcome_read_while_the_reply_settles_still_sees_the_settle() -> None:
    log = InMemoryConversationLog(FakeClock())
    first = await log.append(CONVERSATION, USER, user("u1"))
    claim = await log.claim(CONVERSATION, USER)
    assert claim is not None
    await log.append_fenced(claim, opened("o1"))
    settling = [settled("s1", ["u1"], 1)]

    async def settle_mid_read(point: str) -> None:
        if point == "state" and settling:
            await log.append_fenced(claim, settling.pop())

    log.pause = settle_mid_read
    outcome = await await_outcome(log, CONVERSATION, USER, first.logged, timeout=1)

    assert outcome.settled is not None
    assert outcome.settled.outcome is ReplyOutcome.ANSWERED
