"""work_log: background work's entries on the conversation log, and what each write hands back."""

import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_queue import build_lock_value
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.models.agent_config import StepTurnRef
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import (
    StopBy,
    StopRequested,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.work_cancel_models import WorkCancelled
from app.services.conversation.log import accept
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.work_log import (
    WorkReport,
    approvals_awaited_by,
    record_approval_requested,
    record_gaia_stop,
    record_work_carried,
    record_work_finished,
    record_work_started,
    work_of_run,
)
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


async def test_work_handed_to_a_run_the_log_never_had_goes_ahead_unlogged(rt: Runtime) -> None:
    step = await step_answering(rt, "u1")
    async with captured_wide_event() as event:
        assert await record_work_started(step, CONVERSATION, USER, "t2", joins="unlogged-run")
    assert await stored_ids(rt) == ["u1"]
    assert event["warnings"] == [
        {
            "msg": "work not started: the conversation log refused its WorkStarted",
            "conversation_id": CONVERSATION,
            "task_id": "t2",
            "joins": "unlogged-run",
            "reason": "EntryRejected",
            "handed_over_unlogged": True,
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
    assert [(w["reason"], w["handed_over_unlogged"]) for w in event["warnings"]] == [
        ("EntryRejected", False)
    ]


async def test_work_under_a_lost_claim_never_dispatches_even_when_it_joins_a_run(
    rt: Runtime,
) -> None:
    step = await step_answering(rt, "u1")
    step["epoch"] += 1
    async with captured_wide_event() as event:
        assert not await record_work_started(step, CONVERSATION, USER, "t2", joins="t0")
    assert [(w["reason"], w["handed_over_unlogged"]) for w in event["warnings"]] == [
        ("ClaimLost", False)
    ]


async def test_finished_work_is_logged_with_its_report_under_the_users_conversation(
    rt: Runtime,
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    shown: ToolDataEntry = {"tool_name": "weather", "data": {"city": "Pune"}}
    image = ImageData(url="https://img", prompt="a map")
    report = WorkReport(
        text="done it", tool_data=[shown], note="checked", nothing_for_user=True, image=image
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
    )


async def test_lost_work_is_logged_under_its_own_id_so_a_late_result_is_never_its_duplicate(
    rt: Runtime,
) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    assert await record_work_carried(CONVERSATION, USER, "t1")
    await record_work_finished(CONVERSATION, USER, "t1", WorkOutcome.LOST, WorkReport(text=""))
    assert (await rt.entries())[-1].entry == WorkFinished(
        id="work:t1:lost", task_id="t1", outcome=WorkOutcome.LOST, report=""
    )


async def test_carried_work_with_no_cause_is_caused_by_everything_logged(rt: Runtime) -> None:
    await accept(rt.ports, CONVERSATION, USER, user("u1"))
    await accept(rt.ports, CONVERSATION, USER, user("u2"))
    assert await record_work_carried(CONVERSATION, USER, "t1", detached=True, exclusive=True)
    assert (await rt.entries())[-1].entry == WorkStarted(
        id="work:t1", task_id="t1", cause_through=2, detached=True, exclusive=True
    )


async def test_carried_work_answering_a_cause_names_it(rt: Runtime) -> None:
    cause = (await accept(rt.ports, CONVERSATION, USER, user("u1"))).appended.logged
    await accept(rt.ports, CONVERSATION, USER, user("u2"))
    assert await record_work_carried(CONVERSATION, USER, "t1", cause, detached=True, exclusive=True)
    assert (await rt.entries())[-1].entry == WorkStarted(
        id="work:t1", task_id="t1", cause_through=1, answers=("u1",), detached=True, exclusive=True
    )


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
