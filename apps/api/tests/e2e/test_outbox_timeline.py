"""The outbox as a user lives it: events on a clock, asserted on the ledger rows they leave.

Scenarios from the outbound-layer catalogue that need no holds: B3, B4, B8, B9, B16 and the
record-is-not-alert and one-destination rules. Needs USE_REAL_SERVICES=1 (real Mongo for the
two outbox collections); the model, transports, thread and clock are doubled (see the harness).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

from app.constants.agents import OutcomeState
from app.models.chat_models import ConversationSource
from app.models.task_report_models import TaskReport
from app.services.outbox.deliver import flush_subject
from app.services.outbox.models import (
    ComposeResult,
    DeliveryPolicy,
    DeliveryTiming,
    DropReason,
    Initiative,
    ItemState,
    MessageState,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    SubjectMerge,
    UrgencyClass,
)
from app.services.outbox.transport.bot_queue import OutboundResult
from tests.e2e._harness.outbox_timeline import (
    T0,
    OutboxTimeline,
    World,
    outbox_timeline,
    prepare_collections,
)

pytestmark = pytest.mark.e2e

USER = "6812f0b3c9a14e2b7d5a91cc"


def _reminder(
    n: int = 1, *, owner: str | None = "web-1", minutes: float = 0, **overrides: object
) -> NoticeReport:
    fields: dict[str, object] = {
        "report_id": f"rem:r{n}:1",
        "recipient": USER,
        "producer": ProducerKind.REMINDER,
        "subject": Subject(
            kind=SubjectKind.REMINDER, id=f"r{n}:1", owner_conversation_id=owner, label="Standup"
        ),
        "occurred_at": T0 + timedelta(minutes=minutes),
        "initiative": Initiative.USER_SCHEDULED,
        "delivery_policy": DeliveryPolicy(timing=DeliveryTiming.AT_TIME, may_wake=True),
        "outcome": NoticeOutcome.INFO,
        "facts": ["Standup", "Join now"],
    }
    return NoticeReport.model_validate({**fields, **overrides})


def _run(
    report_id: str,
    outcome: OutcomeState,
    *,
    subject_id: str = "todo-1",
    merge: SubjectMerge = SubjectMerge.REPLACE,
    minutes: float = 0,
    initiative: Initiative = Initiative.SELF_INITIATED,
) -> RunReport:
    return RunReport(
        report_id=report_id,
        recipient=USER,
        producer=ProducerKind.TODO,
        subject=Subject(
            kind=SubjectKind.TODO_RUN,
            id=subject_id,
            owner_conversation_id="web-1",
            label="Inbox check",
            merge=merge,
        ),
        occurred_at=T0 + timedelta(minutes=minutes),
        initiative=initiative,
        report=TaskReport(outcome=outcome),
    )


@pytest.fixture
async def world(mongo_db) -> World:
    await prepare_collections(mongo_db)
    world = World(user_id=USER)
    world.link("telegram", "tg-1")
    world.link("whatsapp", "wa-1")
    world.priority = ["whatsapp", "telegram"]
    world.app_chat("web-1")
    world.dm("telegram", "tg-dm")
    world.dm("whatsapp", "wa-dm")
    return world


@pytest.fixture
async def tl(mongo_db, world: World, fake_redis) -> AsyncIterator[OutboxTimeline]:
    with outbox_timeline(mongo_db, world, fake_redis) as timeline:
        yield timeline
    for name in ("outbox_items", "outbox_messages"):
        await mongo_db[name].drop()


async def test_b3_a_reminder_at_2am_is_sent_at_its_time_as_an_interrupt(tl: OutboxTimeline) -> None:
    tl.clock.current = T0.replace(hour=2)
    await tl.submit(_reminder())
    await tl.drain()

    [message] = await tl.ledger()
    assert message.state is MessageState.SENT
    assert message.max_class is UrgencyClass.INTERRUPT
    assert message.mode.value == "interrupt"
    assert message.sent_at == tl.clock.current
    [event] = tl.sinks.analytics
    assert (event.producer, event.mode, event.max_class) == ("reminder", "interrupt", "interrupt")


async def test_b16_the_same_report_twice_is_one_message(tl: OutboxTimeline) -> None:
    tl.world.linked.clear()
    await tl.submit(_reminder())
    await tl.submit(_reminder())
    await tl.drain()
    await tl.submit(_reminder())
    await tl.drain()

    assert len(await tl.ledger()) == 1
    assert len(await tl.items()) == 1
    assert len(tl.sinks.ws) == 1


async def test_a_rerun_of_a_job_a_crash_left_queued_still_tells_the_user_once(
    tl: OutboxTimeline,
) -> None:
    report = _reminder()
    from app.workers.tasks.outbox_tasks import outbox_intake

    with pytest.MonkeyPatch.context() as mp:

        async def crash(*_: object, **__: object) -> None:
            raise RuntimeError("worker died")

        mp.setattr("app.services.outbox.intake.flush_subject", crash)
        with pytest.raises(RuntimeError):
            await outbox_intake({}, report.model_dump(mode="json"))
    [item] = await tl.items()
    assert item.state is ItemState.QUEUED

    await outbox_intake({}, report.model_dump(mode="json"))
    await outbox_intake({}, report.model_dump(mode="json"))

    assert len(await tl.ledger()) == 1
    assert [i.state for i in await tl.items()] == [ItemState.SENT]


async def test_b4_nothing_new_is_recorded_and_never_alerted(tl: OutboxTimeline) -> None:
    await tl.submit(_run("run-1", OutcomeState.NOTHING_NEW))
    await tl.drain()

    [item] = await tl.items()
    assert (item.state, item.drop_reason) == (ItemState.DROPPED, DropReason.NOTHING_NEW)
    assert await tl.ledger() == []
    assert tl.sinks.bot == [] and tl.sinks.ws == []


async def test_b8_a_newer_report_of_a_replace_subject_supersedes_the_one_not_yet_told(
    tl: OutboxTimeline, mongo_db
) -> None:
    older = _run("run-1", OutcomeState.PARTIAL, minutes=0, initiative=Initiative.ASKED)
    await _park_queued(tl, older)
    await tl.submit(_run("run-2", OutcomeState.DONE, minutes=5, initiative=Initiative.ASKED))
    await tl.drain()

    states = {i.report_id: i.state for i in await tl.items()}
    assert states == {"run-1": ItemState.SUPERSEDED, "run-2": ItemState.SENT}
    [message] = await tl.ledger()
    assert message.report_ids == ["run-2"]


async def test_b9_accumulating_reports_of_a_subject_are_one_message(tl: OutboxTimeline) -> None:
    first = _run("run-1", OutcomeState.DONE, merge=SubjectMerge.ACCUMULATE, minutes=0)
    await _park_queued(tl, first)
    await tl.submit(_run("run-2", OutcomeState.DONE, merge=SubjectMerge.ACCUMULATE, minutes=5))
    await tl.drain()

    [message] = await tl.ledger()
    assert sorted(message.report_ids) == ["run-1", "run-2"]
    assert tl.sinks.analytics[0].items_count == 2


async def test_record_is_not_alert_a_web_reminder_is_recorded_where_set_and_alerted_once_elsewhere(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner="web-1"))
    await tl.drain()

    [message] = await tl.ledger()
    assert message.destination == "chat_app"
    assert message.conversation_id == "tg-dm"
    assert message.recorded_in == ["tg-dm", "web-1"]
    assert [source for source, _ in tl.sinks.bot] == ["telegram"]
    assert tl.sinks.ws == []
    assert tl.world.saved.keys() == {"tg-dm", "web-1"}
    assert tl.world.unread == {"web-1"}
    assert {t for t, _, _ in tl.graph.writes} == {"tg-dm", "web-1"}


async def test_one_destination_the_active_chat_app_beats_the_priority_order(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner=None))
    await tl.drain()

    assert [source for source, _ in tl.sinks.bot] == ["telegram"]
    assert tl.sinks.ws == []


async def test_an_answer_goes_back_to_the_dm_that_asked_when_nobody_is_active(
    tl: OutboxTimeline,
) -> None:
    await tl.submit(_reminder(owner="tg-dm"))
    await tl.drain()

    [message] = await tl.ledger()
    assert message.destination_basis == "owner_chat"
    assert [source for source, _ in tl.sinks.bot] == ["telegram"]


async def test_an_app_alert_is_recorded_in_the_chat_and_pushed_to_open_clients(
    tl: OutboxTimeline,
) -> None:
    tl.world.linked.clear()
    await tl.active_on(ConversationSource.WEB)
    await tl.submit(_reminder(owner="web-1"))
    await tl.drain()

    [message] = await tl.ledger()
    assert (message.destination, message.recorded_in) == ("in_app", ["web-1"])
    assert tl.sinks.bot == []
    assert [c for c, _ in tl.sinks.ws] == ["web-1"]


async def test_the_composed_message_joins_the_thread_under_the_thread_lock_and_nothing_else_runs(
    tl: OutboxTimeline,
) -> None:
    tl.world.linked.clear()
    await tl.submit(_reminder(owner="web-1"))
    await tl.drain()

    [(thread, node, lock_held)] = tl.graph.writes
    assert (thread, node, lock_held) == ("web-1", "tools", True)
    [message] = tl.graph.threads["web-1"]
    assert message.type == "ai"


async def test_a_composer_that_drops_a_must_say_item_is_asked_again_once(
    tl: OutboxTimeline,
) -> None:
    tl.compose.script = [
        ComposeResult.model_validate(
            {
                "dispositions": [{"item_id": "rem:r1:1", "action": "skip", "reason": "x"}],
                "parts": [],
            }
        )
    ]
    await tl.submit(_reminder())
    await tl.drain()

    assert len(tl.compose.calls) == 2
    assert "broke a rule" in str(tl.compose.calls[1][-1].content)
    [message] = await tl.ledger()
    assert message.degraded is False


async def test_a_composer_that_breaks_the_contract_twice_gets_the_plain_render_sent(
    tl: OutboxTimeline,
) -> None:
    bad = ComposeResult.model_validate({"dispositions": [], "parts": []})
    tl.compose.script = [bad, bad]
    await tl.submit(_reminder())
    await tl.drain()

    [message] = await tl.ledger()
    assert message.degraded is True
    assert "Standup; Join now" in message.parts[0]
    assert tl.sinks.analytics[0].degraded is True


async def test_a_chat_app_that_refuses_the_message_fails_the_item_and_logs_it(
    tl: OutboxTimeline,
) -> None:
    tl.sinks.bot_result = OutboundResult.FAILED
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner=None))
    await tl.drain()

    [item] = await tl.items()
    assert item.state is ItemState.FAILED
    [message] = await tl.ledger()
    assert message.state is MessageState.FAILED
    assert tl.sinks.analytics == []
    assert tl.graph.writes == []


async def test_two_flushers_on_one_queued_item_send_one_message(tl: OutboxTimeline) -> None:
    await _park_queued(tl, _reminder(owner=None))

    await asyncio.gather(flush_subject(USER, "r1:1"), flush_subject(USER, "r1:1"))

    assert len(await tl.ledger()) == 1
    assert len(tl.compose.calls) == 1
    assert len(tl.sinks.bot) + len(tl.sinks.ws) == 1


async def _park_queued(tl: OutboxTimeline, report: NoticeReport | RunReport) -> None:
    """Leave a report queued but untold, as a flusher that has not run yet would."""
    from app.db.repositories.outbox_items import outbox_items_repository
    from app.services.outbox.policy import decide

    stored = await outbox_items_repository.insert_if_new(
        report, expires_at=tl.clock.now() + timedelta(days=1)
    )
    assert stored.created
    decision = decide(report)
    await outbox_items_repository.queue(
        USER, report.report_id, urgency=decision.urgency, mode=decision.mode
    )
