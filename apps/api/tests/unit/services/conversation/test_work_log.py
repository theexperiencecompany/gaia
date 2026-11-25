"""work_log: background work's entries on the conversation log, and what each write hands back."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.agents.core.background.executor_queue import build_lock_value
from app.constants.cache import EXECUTOR_ALIVE_GIVE_UP_SECONDS, EXECUTOR_BUSY_PREFIX
from app.constants.chat import ARTIFACT_CARD
from app.constants.conversation import (
    STEP_DRAIN_GRACE_SECONDS,
    WORK_ENDED_KEY_PREFIX,
    WORK_ENDED_TTL_SECONDS,
    WORK_LOST_REPORT,
)
from app.constants.db import MONGO_TRANSIENT_RETRY_ATTEMPTS
from app.db.mongodb.retry import TRANSIENT_MONGO_RETRY
from app.models.agent_config import StepTurnRef
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import (
    Entry,
    StopBy,
    StopRequested,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.work_cancel_models import WorkCancelled
from app.services.conversation import work_log
from app.services.conversation.log import accept
from app.services.conversation.ports import Appended
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.work_log import (
    Continuing,
    WorkReport,
    approvals_awaited_by,
    record_approval_requested,
    record_gaia_stop,
    record_work_carried,
    record_work_finished,
    record_work_lost,
    record_work_started,
    work_of_run,
)
from app.utils.errors import ConversationStoreError
from app.workers.config.worker_settings import ARQ_BACKSTOP_GRACE_SECONDS
from shared.py.conversation_wire import ImageData, ToolDataEntry
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import asked, stop, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Runtime,
)


@pytest.fixture
def rt() -> Runtime:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    return runtime


async def step_answering(rt: Runtime, *message_ids: str) -> StepTurnRef:
    """Log the messages and claim the step that answers them, as the comms run holds it."""
    for message_id in message_ids:
        await accept(rt.ports, CONVERSATION, USER, user(message_id))
    claim = await rt.log.claim(CONVERSATION, USER)
    assert claim is not None
    return {
        "epoch": claim.epoch,
        "batch_start": 1,
        "cause_through": len(message_ids),
        "answers": list(message_ids),
        "asked": True,
    }


async def stored_ids(rt: Runtime) -> list[str]:
    return [logged.entry.id for logged in await rt.entries()]


async def test_started_work_is_logged_with_the_step_it_answers_and_published(
    rt: Runtime,
) -> None:
    step = await step_answering(rt, "u1", "u2")
    rt.frames.published.clear()
    rt.frames.conversations.clear()
    assert await record_work_started(step, CONVERSATION, USER, "t1", handoff="call-1")
    expected = WorkStarted(
        id="work:t1", task_id="t1", cause_through=2, answers=("u1", "u2"), handoff="call-1"
    )
    stored = (await rt.entries())[-1]
    assert stored.entry == expected
    assert rt.frames.published[0] == EntryFrame(seq=stored.seq, at=stored.at, entry=expected)
    assert set(rt.frames.conversations) == {CONVERSATION}


async def test_work_handed_to_a_run_the_log_never_had_is_refused(rt: Runtime) -> None:
    step = await step_answering(rt, "u1")
    async with captured_wide_event() as event:
        assert not await record_work_started(step, CONVERSATION, USER, "t2", joins="unlogged-run")
    assert await stored_ids(rt) == ["u1"]
    assert event["warnings"] == [
        {
            "msg": "work not started: the conversation log refused its WorkStarted",
            "conversation_id": CONVERSATION,
            "task_id": "t2",
            "joins": "unlogged-run",
            "reason": "EntryRejected",
            "error_type": "EntryRejected",
            "error": "task_not_live",
        }
    ]


async def test_work_a_stop_refuses_never_dispatches_even_when_it_joins_a_run(
    rt: Runtime,
) -> None:
    step = await step_answering(rt, "u1")
    await accept(rt.ports, CONVERSATION, USER, stop("s1"))
    async with captured_wide_event() as event:
        assert not await record_work_started(step, CONVERSATION, USER, "t2", joins="t0")
    assert [w["reason"] for w in event["warnings"]] == ["EntryRejected"]


async def test_work_under_a_lost_claim_never_dispatches_even_when_it_joins_a_run(
    rt: Runtime,
) -> None:
    step = await step_answering(rt, "u1")
    step["epoch"] += 1
    async with captured_wide_event() as event:
        assert not await record_work_started(step, CONVERSATION, USER, "t2", joins="t0")
    assert [w["reason"] for w in event["warnings"]] == ["ClaimLost"]


async def test_finished_work_is_logged_with_its_report_under_the_users_conversation(
    rt: Runtime,
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    shown: ToolDataEntry = {"tool_name": "weather", "data": {"city": "Pune"}}
    image = ImageData(url="https://img", prompt="a map")
    report = WorkReport(
        text="done it",
        tool_data=[shown],
        note="checked",
        nothing_for_user=True,
        image=image,
        awaits_decision=True,
    )
    await record_work_finished(
        CONVERSATION, USER, "t1", WorkOutcome.DONE, report, continued_by_decision=True
    )
    assert (await rt.entries())[-1].entry == WorkFinished(
        id="work:t1:finished",
        task_id="t1",
        outcome=WorkOutcome.DONE,
        report="done it",
        tool_data=(shown,),
        note="checked",
        nothing_for_user=True,
        image=image,
        continued_by_decision=True,
        awaits_decision=True,
    )


CARD: ToolDataEntry = {"tool_name": "weather", "data": {"city": "Pune"}}
IMAGE = ImageData(url="https://img", prompt="a map")
ENDED_KEY = f"{WORK_ENDED_KEY_PREFIX}{CONVERSATION}:t1"
FILE_CARD: ToolDataEntry = {
    "tool_name": ARTIFACT_CARD,
    "data": {"event": "upsert", "path": "report.csv"},
}


@dataclass
class Refusals:
    """The finishes the log was asked to append, and whether each found its work marked ended."""

    asked: list[WorkFinished] = field(default_factory=list)
    marked_ended: list[bool] = field(default_factory=list)


@pytest.fixture
async def live(rt: Runtime, fake_redis: fakeredis.aioredis.FakeRedis) -> AsyncIterator[Runtime]:
    """Return the runtime with work t1 running, and no wait between its store retries."""
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    with patch.object(TRANSIENT_MONGO_RETRY, "sleep", AsyncMock()):
        yield rt


def refuse(
    rt: Runtime,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
    refusing: Callable[[WorkFinished, int], Exception | None],
) -> Refusals:
    """Make the log refuse each WorkFinished that refusing, given the entry and its attempt, returns an error for."""
    seen = Refusals()
    append = rt.log.append

    async def refusing_append(conversation_id: str, user_id: str, entry: Entry) -> Appended:
        if isinstance(entry, WorkFinished):
            seen.asked.append(entry)
            seen.marked_ended.append(bool(await fake_redis.exists(ENDED_KEY)))
            if (error := refusing(entry, len(seen.asked))) is not None:
                raise error
        return await append(conversation_id, user_id, entry)

    monkeypatch.setattr(rt.log, "append", refusing_append)
    return seen


def unreachable() -> ConversationStoreError:
    return ConversationStoreError(message="conversation store log append failed")


def too_large() -> ConversationStoreError:
    return ConversationStoreError(message="conversation store log append failed", too_large=True)


async def finish(report: WorkReport) -> None:
    await record_work_finished(CONVERSATION, USER, "t1", WorkOutcome.DONE, report)


async def test_a_finish_the_store_refused_while_unreachable_is_retried_and_saved_whole(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    seen = refuse(
        live, monkeypatch, fake_redis, lambda _, attempt: unreachable() if attempt <= 3 else None
    )

    async with captured_wide_event() as event:
        await finish(WorkReport("done it", [CARD], image=IMAGE))

    saved = (await live.entries())[-1].entry
    assert saved == WorkFinished(
        id="work:t1:finished",
        task_id="t1",
        outcome=WorkOutcome.DONE,
        report="done it",
        tool_data=(CARD,),
        image=IMAGE,
    )
    assert seen.asked == [saved] * 4
    # Its run is still alive while it saves, so nothing is marked for the sweep until it gives up.
    assert seen.marked_ended == [False] * 4
    assert not await fake_redis.exists(ENDED_KEY)
    assert "errors" not in event


async def test_a_finish_too_large_for_the_store_is_saved_with_only_its_file_cards(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Regression for #1947 review: dropping every card also dropped the link to a document the work made."""
    seen = refuse(
        live,
        monkeypatch,
        fake_redis,
        lambda entry, _: too_large() if CARD in entry.tool_data else None,
    )

    async with captured_wide_event() as event:
        await finish(WorkReport("done it", [CARD, FILE_CARD, CARD], note="checked", image=IMAGE))

    saved = (await live.entries())[-1].entry
    assert saved == WorkFinished(
        id="work:t1:finished",
        task_id="t1",
        outcome=WorkOutcome.DONE,
        report="done it",
        tool_data=(FILE_CARD,),
        note="checked",
        image=IMAGE,
    )
    assert [len(entry.tool_data) for entry in seen.asked] == [3, 1]
    assert not await fake_redis.exists(ENDED_KEY)
    assert event["warnings"][-1] == {
        "msg": "work finish too large; saved with only its file cards",
        "conversation_id": CONVERSATION,
        "task_id": "t1",
        "cards_dropped": 2,
        "error_type": "ConversationStoreError",
    }
    assert "errors" not in event


async def test_a_finish_refused_through_every_retry_keeps_its_cards_and_stays_unsaved(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Regression for #1947 review: an outage dropped the cards, though the store never said they were the problem."""
    refused = unreachable()
    seen = refuse(
        live, monkeypatch, fake_redis, lambda entry, _: refused if entry.tool_data else None
    )

    with pytest.raises(ConversationStoreError) as raised:
        await finish(WorkReport("done it", [CARD]))

    assert raised.value is refused
    assert [len(entry.tool_data) for entry in seen.asked] == [1] * MONGO_TRANSIENT_RETRY_ATTEMPTS
    assert not any(isinstance(logged.entry, WorkFinished) for logged in await live.entries())


async def test_a_retry_that_turns_out_too_large_stops_retrying_and_keeps_only_file_cards(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    def refusing(entry: WorkFinished, attempt: int) -> Exception | None:
        if not entry.tool_data:
            return None
        return unreachable() if attempt == 1 else too_large()

    seen = refuse(live, monkeypatch, fake_redis, refusing)

    await finish(WorkReport("done it", [CARD]))

    assert [len(entry.tool_data) for entry in seen.asked] == [1, 1, 0]


async def test_a_lean_finish_the_store_cannot_reach_is_tried_again_from_the_whole_one(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    def refusing(entry: WorkFinished, attempt: int) -> Exception | None:
        if entry.tool_data:
            return too_large()
        return unreachable() if attempt == 2 else None

    seen = refuse(live, monkeypatch, fake_redis, refusing)

    await finish(WorkReport("done it", [CARD]))

    assert [len(entry.tool_data) for entry in seen.asked] == [1, 0, 1, 0]
    assert (await live.entries())[-1].entry == WorkFinished(
        id="work:t1:finished", task_id="t1", outcome=WorkOutcome.DONE, report="done it"
    )


async def test_a_finish_never_saved_raises_and_is_marked_ended_for_the_sweep(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    refused = unreachable()
    seen = refuse(live, monkeypatch, fake_redis, lambda *_: refused)

    async with captured_wide_event() as event:
        with pytest.raises(ConversationStoreError) as raised:
            await finish(WorkReport("done it", [CARD]))

    assert raised.value is refused
    assert len(seen.asked) == MONGO_TRANSIENT_RETRY_ATTEMPTS
    assert not any(seen.marked_ended)
    assert not any(isinstance(logged.entry, WorkFinished) for logged in await live.entries())
    assert await fake_redis.get(ENDED_KEY) == "1"
    assert await fake_redis.ttl(ENDED_KEY) == WORK_ENDED_TTL_SECONDS
    assert event["errors"] == [
        {
            "msg": "work finish not saved",
            "conversation_id": CONVERSATION,
            "task_id": "t1",
            "error_type": "ConversationStoreError",
            "too_large": False,
        }
    ]


@pytest.mark.parametrize(
    ("report", "files"),
    [(WorkReport("done it", image=IMAGE), 0), (WorkReport("done it", [FILE_CARD]), 1)],
    ids=["no_cards", "only_file_cards"],
)
async def test_a_finish_too_large_with_nothing_to_drop_raises_at_once_and_is_marked_ended(
    live: Runtime,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
    report: WorkReport,
    files: int,
) -> None:
    refused = too_large()
    seen = refuse(live, monkeypatch, fake_redis, lambda *_: refused)

    async with captured_wide_event() as event:
        with pytest.raises(ConversationStoreError) as raised:
            await finish(report)

    assert raised.value is refused
    assert [len(entry.tool_data) for entry in seen.asked] == [files]
    assert await fake_redis.exists(ENDED_KEY)
    assert event["errors"][0]["too_large"] is True


async def test_a_finish_the_store_never_answers_is_given_up_on_at_its_deadline(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Regression for #1947 review: each store call could wait out its own 30 s, with nothing bounding the save."""
    waiting: list[str] = []

    async def never_answers(conversation_id: str, user_id: str, entry: Entry) -> Appended:
        try:
            await asyncio.Event().wait()
        finally:
            waiting.append("cancelled")
        raise AssertionError("unreachable")

    monkeypatch.setattr(live.log, "append", never_answers)
    # Nothing to wait for before the append, so the deadline is spent on the store alone.
    monkeypatch.setattr(work_log, "reconcile_artifacts", AsyncMock(return_value=()))
    monkeypatch.setattr(work_log, "WORK_FINISH_SAVE_SECONDS", 0)

    async with captured_wide_event() as event:
        with pytest.raises(TimeoutError):
            await finish(WorkReport("done it", [CARD]))

    assert waiting == ["cancelled"]
    assert await fake_redis.exists(ENDED_KEY)
    assert (event["errors"][0]["error_type"], event["errors"][0]["too_large"]) == (
        "TimeoutError",
        False,
    )


def test_the_finish_saves_budget_fits_a_shutdown_and_a_timed_out_jobs_cleanup() -> None:
    assert work_log.WORK_FINISH_SAVE_SECONDS < STEP_DRAIN_GRACE_SECONDS
    assert work_log.WORK_FINISH_SAVE_SECONDS < ARQ_BACKSTOP_GRACE_SECONDS
    assert work_log.WORK_FINISH_SAVE_SECONDS < EXECUTOR_ALIVE_GIVE_UP_SECONDS


async def test_a_finish_never_saved_raises_what_the_store_said_when_it_cannot_be_marked(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    refused = unreachable()
    refuse(live, monkeypatch, fake_redis, lambda *_: refused)
    monkeypatch.setattr(fake_redis, "set", AsyncMock(side_effect=RedisConnectionError("down")))

    async with captured_wide_event() as event:
        with pytest.raises(ConversationStoreError) as raised:
            await finish(WorkReport("done it", [CARD]))

    assert raised.value is refused
    assert event["errors"][-1] == {
        "msg": "work finish not marked ended; the sweep will call it lost",
        "conversation_id": CONVERSATION,
        "task_id": "t1",
        "error_type": "ConnectionError",
    }


async def test_a_finish_that_fails_outside_the_store_is_not_retried_and_is_marked_ended(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    seen = refuse(live, monkeypatch, fake_redis, lambda *_: RuntimeError("frames down"))

    with pytest.raises(RuntimeError):
        await finish(WorkReport("done it", [CARD]))

    assert len(seen.asked) == 1
    assert await fake_redis.exists(ENDED_KEY)


async def _never() -> tuple[ToolDataEntry, ...]:
    await asyncio.Event().wait()
    return ()


@pytest.mark.parametrize(
    ("reconcile", "raised"),
    [
        (AsyncMock(side_effect=ServerSelectionTimeoutError("no primary")), PyMongoError),
        (lambda *_: _never(), TimeoutError),
    ],
    ids=["driver_error", "hangs_past_the_deadline"],
)
async def test_a_finish_whose_file_cards_cannot_be_read_is_unsaved_never_lost_with_its_server(
    live: Runtime,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
    reconcile: Callable[..., Awaitable[tuple[ToolDataEntry, ...]]],
    raised: type[Exception],
) -> None:
    """Regression for #1947 review: the registry read ran before the deadline and the mark, so its failure read as a dead server."""
    with monkeypatch.context() as during_the_finish:
        during_the_finish.setattr(work_log, "reconcile_artifacts", reconcile)
        during_the_finish.setattr(work_log, "WORK_FINISH_SAVE_SECONDS", 0)
        with pytest.raises(raised):
            await finish(WorkReport("done it", [CARD]))

    assert await record_work_lost(CONVERSATION, USER, "t1") is WorkOutcome.FAILED
    ended = (await live.entries())[-1].entry
    assert isinstance(ended, WorkFinished)
    assert ended.report != WORK_LOST_REPORT


async def test_a_finish_that_lands_after_its_deadline_is_the_works_one_ending(
    live: Runtime, monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Motor runs the driver call in a thread, which a cancelled await does not stop: the write can still land."""
    append = live.log.append
    landing: list[asyncio.Task[Appended]] = []

    async def lands_late(conversation_id: str, user_id: str, entry: Entry) -> Appended:
        landing.append(asyncio.ensure_future(append(conversation_id, user_id, entry)))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(live.log, "append", lands_late)
    # Nothing to wait for before the append, so the deadline is spent on the store alone.
    monkeypatch.setattr(work_log, "reconcile_artifacts", AsyncMock(return_value=()))
    monkeypatch.setattr(work_log, "WORK_FINISH_SAVE_SECONDS", 0)

    with pytest.raises(TimeoutError):
        await finish(WorkReport("done it", [CARD]))
    await asyncio.gather(*landing)

    finished = [e.entry for e in await live.entries() if isinstance(e.entry, WorkFinished)]
    assert [(f.id, f.outcome) for f in finished] == [("work:t1:finished", WorkOutcome.DONE)]
    # No longer live, so the sweep has nothing of it to end a second time.
    assert (await live.log.state(CONVERSATION, USER)).work == ()


async def test_work_no_process_runs_is_lost_under_its_own_id_so_a_late_result_is_never_its_duplicate(
    live: Runtime, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    # Another task's unsaved finish, and this task's in another conversation, say nothing about t1.
    await fake_redis.set(f"{WORK_ENDED_KEY_PREFIX}{CONVERSATION}:t2", "1")
    await fake_redis.set(f"{WORK_ENDED_KEY_PREFIX}c2:t1", "1")

    assert await record_work_lost(CONVERSATION, USER, "t1") is WorkOutcome.LOST

    assert (await live.entries())[-1].entry == WorkFinished(
        id="work:t1:lost", task_id="t1", outcome=WorkOutcome.LOST, report=WORK_LOST_REPORT
    )


async def test_work_whose_own_process_ended_it_unsaved_is_failed_as_unsaved_never_lost(
    live: Runtime, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    await fake_redis.set(ENDED_KEY, "1")

    assert await record_work_lost(CONVERSATION, USER, "t1") is WorkOutcome.FAILED

    assert (await live.entries())[-1].entry == WorkFinished(
        id="work:t1:lost",
        task_id="t1",
        outcome=WorkOutcome.FAILED,
        report="The background work ended, but its result could not be saved, so it cannot be shown.",
    )


async def test_work_ended_by_the_sweep_gets_the_cards_of_files_it_left_behind(
    live: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    left: ToolDataEntry = {"tool_name": "artifact", "data": {"path": "report.csv"}}
    reconcile = AsyncMock(return_value=(left,))
    monkeypatch.setattr(work_log, "reconcile_artifacts", reconcile)

    await record_work_lost(CONVERSATION, USER, "t1")

    reconcile.assert_awaited_once_with(USER, CONVERSATION, ())
    saved = (await live.entries())[-1].entry
    assert isinstance(saved, WorkFinished)
    assert saved.tool_data == (left,)


async def test_work_that_carries_on_ended_work_names_it_and_answers_nothing_new(
    rt: Runtime,
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t2", Continuing("t1"))
    assert (await rt.entries())[-1].entry == WorkStarted(
        id="work:t2", task_id="t2", cause_through=1, cause_from=1, continues="t1"
    )


async def test_carried_work_with_no_cause_is_caused_by_everything_logged(rt: Runtime) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    await accept(rt.ports, CONVERSATION, USER, user("u2"))
    assert await record_work_carried(CONVERSATION, USER, "t1", detached=True, exclusive=True)
    assert (await rt.entries())[-1].entry == WorkStarted(
        id="work:t1", task_id="t1", cause_through=2, cause_from=2, detached=True, exclusive=True
    )


async def test_carried_work_answering_a_cause_names_it(rt: Runtime) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    cause = (await accept(rt.ports, CONVERSATION, USER, user("u2"))).appended.logged
    await accept(rt.ports, CONVERSATION, USER, user("u3"))
    assert await record_work_carried(CONVERSATION, USER, "t1", cause, detached=True, exclusive=True)
    assert (await rt.entries())[-1].entry == WorkStarted(
        id="work:t1",
        task_id="t1",
        cause_through=2,
        cause_from=2,
        answers=("u2",),
        detached=True,
        exclusive=True,
    )


async def test_started_work_begins_where_the_steps_batch_begins(rt: Runtime) -> None:
    step = await step_answering(rt, "u1", "u2")
    step["batch_start"] = 2
    assert await record_work_started(step, CONVERSATION, USER, "t1")
    started = (await rt.entries())[-1].entry
    assert isinstance(started, WorkStarted)
    assert started.cause_from == 2


async def test_finished_work_adds_the_cards_its_conversations_files_still_need(
    rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: ToolDataEntry = {"tool_name": "weather", "data": {"city": "Pune"}}
    missed: ToolDataEntry = {"tool_name": "artifact", "data": {"event": "remove", "path": "a.txt"}}

    async def reconcile(
        user_id: str, conversation_id: str, cards: Sequence[ToolDataEntry]
    ) -> tuple[ToolDataEntry, ...]:
        return (
            (missed,)
            if (user_id, conversation_id, [*cards]) == (USER, CONVERSATION, [shown])
            else ()
        )

    monkeypatch.setattr(work_log, "reconcile_artifacts", reconcile)
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    report = WorkReport(text="done it", tool_data=[shown])
    await record_work_finished(CONVERSATION, USER, "t1", WorkOutcome.DONE, report)
    finished = (await rt.entries())[-1].entry
    assert isinstance(finished, WorkFinished)
    assert finished.tool_data == (shown, missed)


async def test_carried_work_a_stop_refuses_is_reported_and_never_dispatches(
    rt: Runtime,
) -> None:
    cause = (await accept(rt.ports, CONVERSATION, USER, user("u1"))).appended.logged
    await accept(rt.ports, CONVERSATION, USER, stop("s1"))
    async with captured_wide_event() as event:
        assert not await record_work_carried(CONVERSATION, USER, "t1", cause)
    assert await stored_ids(rt) == ["u1", "s1"]
    assert event["warnings"] == [
        {
            "msg": "carried work not started: the conversation log refused its WorkStarted",
            "conversation_id": CONVERSATION,
            "task_id": "t1",
            "reason": "cause_stopped",
            "error_type": "EntryRejected",
            "error": "cause_stopped",
        }
    ]


@pytest.fixture
async def busy_lock(fake_redis: fakeredis.aioredis.FakeRedis) -> fakeredis.aioredis.FakeRedis:
    return fake_redis


async def test_a_run_on_its_own_detached_stream_is_its_own_work(
    rt: Runtime, busy_lock: fakeredis.aioredis.FakeRedis
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "stream-1", detached=True)
    assert await work_of_run(CONVERSATION, USER, "stream-1") == "stream-1"


async def test_a_run_belongs_to_the_logged_work_holding_the_conversation(
    rt: Runtime, busy_lock: fakeredis.aioredis.FakeRedis
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    assert (await rt.entries())[-1].entry == WorkStarted(
        id="work:t1", task_id="t1", cause_through=1
    )
    await busy_lock.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", build_lock_value("s9", "t1"))
    assert await work_of_run(CONVERSATION, USER, "s9") == "t1"


@pytest.mark.parametrize("holder", [None, build_lock_value("s9", "not-logged")])
async def test_a_run_with_no_logged_work_is_refused(
    rt: Runtime, busy_lock: fakeredis.aioredis.FakeRedis, holder: str | None
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    if holder is not None:
        await busy_lock.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", holder)
    with pytest.raises(LookupError) as raised:
        await work_of_run(CONVERSATION, USER, "s9")
    assert str(raised.value) == f"run s9 is no logged work in conversation {CONVERSATION}"


async def test_gaias_stop_covers_what_came_before_its_batch_and_cancels_that_work(
    rt: Runtime,
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t0")
    asked = (await accept(rt.ports, CONVERSATION, USER, user("u2"))).appended.logged
    claim = await rt.log.claim(CONVERSATION, USER)
    assert claim is not None
    step: StepTurnRef = {
        "epoch": claim.epoch,
        "batch_start": asked.seq,
        "cause_through": asked.seq,
        "answers": ["u2"],
        "asked": True,
    }
    rt.frames.conversations.clear()
    rt.effects.addressed.clear()
    cancelled = await record_gaia_stop(step, CONVERSATION, USER, "x")
    assert cancelled == WorkCancelled(pending_task_ids=["t0"])
    assert rt.effects.addressed == [(CONVERSATION, USER)]
    assert (await rt.entries())[-1].entry == StopRequested(
        id="stop:x", by=StopBy.GAIA, covers_through=asked.seq - 1
    )
    assert set(rt.frames.conversations) == {CONVERSATION}


async def test_gaias_stop_with_nothing_running_cancels_nothing(rt: Runtime) -> None:
    step = await step_answering(rt, "u1")
    assert await record_gaia_stop(step, CONVERSATION, USER, "x") == WorkCancelled()
    assert [call.name for call in rt.effects.calls if call.name == "cancel_work"] == []


async def test_live_work_lists_only_the_approvals_its_own_tasks_wait_on(rt: Runtime) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    for task_id in ("t1", "t2"):
        assert await record_work_carried(CONVERSATION, USER, task_id)
    for task_id, approval_id in (("t1", "b"), ("t1", "a"), ("t2", "c")):
        await record_approval_requested(
            CONVERSATION, USER, asked(f"ask:{approval_id}", task_id, approval_id)
        )
    assert await approvals_awaited_by(CONVERSATION, USER, {"t1"}) == ["a", "b"]
    assert await approvals_awaited_by(CONVERSATION, USER, {"t3"}) == []


async def test_work_under_a_claim_the_step_no_longer_holds_is_refused_and_logs_nothing(
    rt: Runtime,
) -> None:
    step = await step_answering(rt, "u1")
    step["epoch"] += 1

    assert not await record_work_started(step, CONVERSATION, USER, "task-1")
    assert await stored_ids(rt) == ["u1"]
