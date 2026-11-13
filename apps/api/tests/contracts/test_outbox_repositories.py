"""Contract tests for the outbox repositories, on real Mongo: the compare-and-set and unique inserts the state machine rests on."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.outbox import ITEMS_COLLECTION, MESSAGES_COLLECTION
from app.db.mongodb.indexes import create_outbox_indexes
from app.db.repositories.outbox_items import OutboxItemsRepository
from app.db.repositories.outbox_messages import OutboxMessagesRepository
from app.models.outbox_models import OutboxMessageDocument
from app.models.ownership_models import DeliveryPolicy
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    Initiative,
    ItemState,
    MessageState,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
    UrgencyClass,
)

USER = "6812f0b3c9a14e2b7d5a91cc"
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
EXPIRES = T0 + timedelta(days=90)


@pytest.fixture
async def repos(
    raw_collection: AsyncIOMotorCollection, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[OutboxItemsRepository, OutboxMessagesRepository]]:
    database = raw_collection.database
    suffix = raw_collection.name
    names = {
        ITEMS_COLLECTION: f"{ITEMS_COLLECTION}_{suffix}",
        MESSAGES_COLLECTION: f"{MESSAGES_COLLECTION}_{suffix}",
    }
    monkeypatch.setattr(
        "app.db.repositories.base.get_async_collection", lambda name: database[names[name]]
    )
    monkeypatch.setattr(
        "app.db.mongodb.indexes.get_async_collection", lambda name: database[names[name]]
    )
    await create_outbox_indexes()
    yield OutboxItemsRepository(), OutboxMessagesRepository()
    for name in names.values():
        await database[name].drop()


def _report(report_id: str, *, subject: str = "s1", minutes: int = 0) -> NoticeReport:
    return NoticeReport(
        report_id=report_id,
        recipient=USER,
        producer=ProducerKind.REMINDER,
        subject=Subject(kind=SubjectKind.REMINDER, id=subject, label="L"),
        occurred_at=T0 + timedelta(minutes=minutes),
        initiative=Initiative.USER_SCHEDULED,
        delivery_policy=DeliveryPolicy(),
        outcome=NoticeOutcome.INFO,
        facts=["f"],
    )


async def _queued(items: OutboxItemsRepository, report: NoticeReport) -> None:
    await items.insert_if_new(report, expires_at=EXPIRES)
    queued = await items.queue(
        USER, report.report_id, urgency=UrgencyClass.ROUTINE, mode=ComposeMode.ANSWER
    )
    assert queued is not None


def _message(attempt: str) -> OutboxMessageDocument:
    return OutboxMessageDocument(
        user_id=USER,
        compose_attempt_id=attempt,
        report_ids=["a"],
        mode=ComposeMode.ANSWER,
        max_class=UrgencyClass.ROUTINE,
        parts=["hi"],
        destination="in_app",
        destination_basis="no_chat_app",
        conversation_id="c",
        recorded_in=["c"],
        expires_at=EXPIRES,
    )


async def test_a_report_is_stored_once_and_the_second_insert_finds_it(repos) -> None:
    items, _ = repos

    first = await items.insert_if_new(_report("a"), expires_at=EXPIRES)
    again = await items.insert_if_new(_report("a"), expires_at=EXPIRES)

    assert (first.created, again.created) == (True, False)
    assert again.item.id == first.item.id
    assert await items.count_for_user(USER) == 1


async def test_two_flushers_claiming_one_queued_item_get_it_once(repos) -> None:
    items, _ = repos
    await _queued(items, _report("a"))

    won = await asyncio.gather(
        *(items.claim_queued_for_subject(USER, "s1", f"attempt-{n}") for n in range(8))
    )

    assert sorted(len(claimed) for claimed in won) == [0] * 7 + [1]
    item = await items.get_by_report(USER, "a")
    assert item is not None and item.state is ItemState.COMPOSING


async def test_two_inserts_of_one_compose_attempt_have_one_winner(repos) -> None:
    _, messages = repos

    results = await asyncio.gather(*(messages.insert_attempt(_message("x")) for _ in range(8)))

    assert sorted(results) == [False] * 7 + [True]


async def test_a_replace_supersedes_older_unsent_reports_and_yields_to_a_newer_one(repos) -> None:
    items, _ = repos
    await _queued(items, _report("old", minutes=0))
    await items.insert_if_new(_report("new", minutes=5), expires_at=EXPIRES)
    await items.insert_if_new(_report("late", minutes=-5), expires_at=EXPIRES)

    assert await items.apply_replace(_report("new", minutes=5)) is True
    assert await items.apply_replace(_report("late", minutes=-5)) is False

    stored = [await items.get_by_report(USER, report_id) for report_id in ("late", "old", "new")]
    states = {i.report_id: i.state for i in stored if i is not None}
    assert states == {
        "late": ItemState.SUPERSEDED,
        "old": ItemState.SUPERSEDED,
        "new": ItemState.RECEIVED,
    }


async def test_a_settled_item_cannot_be_moved_again(repos) -> None:
    items, _ = repos
    await items.insert_if_new(_report("a"), expires_at=EXPIRES)
    assert await items.drop(USER, "a", DropReason.NOTHING_NEW) is not None

    assert await items.drop(USER, "a", DropReason.CANCELLED) is None
    assert (
        await items.queue(USER, "a", urgency=UrgencyClass.ROUTINE, mode=ComposeMode.ANSWER) is None
    )


async def test_the_send_steps_only_move_items_that_are_in_the_step_before(repos) -> None:
    items, _ = repos
    await _queued(items, _report("a"))
    [claimed] = await items.claim_queued_for_subject(USER, "s1", "att")

    assert await items.finish_send(USER, "att", ItemState.SENT) == 0
    assert await items.begin_send(USER, "att") == 1
    assert await items.begin_send(USER, "att") == 0
    assert await items.release_composing(USER, "att") == 0
    assert await items.finish_send(USER, "att", ItemState.SENT) == 1
    assert claimed.report_id == "a"


async def test_a_released_attempt_returns_its_items_to_the_queue(repos) -> None:
    items, _ = repos
    await _queued(items, _report("a"))
    await items.claim_queued_for_subject(USER, "s1", "att")

    assert await items.release_composing(USER, "att") == 1

    [again] = await items.claim_queued_for_subject(USER, "s1", "att-2")
    assert again.compose_attempt_id == "att-2"


async def test_a_message_settles_once_and_recent_sent_lists_newest_first(repos) -> None:
    _, messages = repos
    for attempt in ("one", "two"):
        await messages.insert_attempt(_message(attempt))
    sent_one = T0
    sent_two = T0 + timedelta(minutes=1)
    assert await messages.finish_send(USER, "one", MessageState.SENT, sent_at=sent_one)
    assert await messages.finish_send(USER, "two", MessageState.SENT, sent_at=sent_two)
    assert not await messages.finish_send(USER, "two", MessageState.FAILED)

    recent = await messages.recent_sent(USER, limit=5)

    assert [m.compose_attempt_id for m in recent] == ["two", "one"]


def _of_series(report_id: str, series: str | None, *, minutes: int) -> NoticeReport:
    report = _report(report_id, subject=report_id, minutes=minutes)
    subject = report.subject.model_copy(update={"series": series})
    return report.model_copy(update={"subject": subject})


async def _settle(items: OutboxItemsRepository, report: NoticeReport, state: ItemState) -> None:
    if state is ItemState.DROPPED:
        await items.insert_if_new(report, expires_at=EXPIRES)
        assert await items.drop(USER, report.report_id, DropReason.NOTHING_NEW) is not None
        return
    await _queued(items, report)
    attempt = f"attempt-{report.report_id}"
    claimed = await items.claim_queued_for_subject(USER, report.subject.id, attempt)
    assert len(claimed) == 1
    await items.begin_send(USER, attempt)
    await items.finish_send(USER, attempt, ItemState.SENT)


async def test_the_last_told_or_quiet_items_of_a_series_come_newest_first_before_an_instant(
    repos,
) -> None:
    items, _ = repos
    await _settle(items, _of_series("old", "todo:t1", minutes=0), ItemState.SENT)
    await _settle(items, _of_series("quiet", "todo:t1", minutes=10), ItemState.DROPPED)
    await _settle(items, _of_series("sent", "todo:t1", minutes=20), ItemState.SENT)
    await _settle(items, _of_series("later", "todo:t1", minutes=40), ItemState.SENT)

    found = await items.list_settled_of_series(
        USER, "todo:t1", before=T0 + timedelta(minutes=30), limit=2
    )

    assert [item.report_id for item in found] == ["sent", "quiet"]


async def test_a_series_reads_only_its_own_settled_items(repos) -> None:
    items, _ = repos
    await _settle(items, _of_series("mine", "todo:t1", minutes=0), ItemState.SENT)
    await _settle(items, _of_series("theirs", "todo:t2", minutes=1), ItemState.SENT)
    await _settle(items, _of_series("alone", None, minutes=2), ItemState.SENT)
    await _queued(items, _of_series("untold", "todo:t1", minutes=3))

    found = await items.list_settled_of_series(
        USER, "todo:t1", before=T0 + timedelta(hours=1), limit=10
    )

    assert [item.report_id for item in found] == ["mine"]


async def test_the_series_read_is_served_by_its_index(repos) -> None:
    items, _ = repos
    await _settle(items, _of_series("a", "todo:t1", minutes=0), ItemState.SENT)
    collection = items._raw_collection()

    plan = await collection.find(
        {
            "user_id": USER,
            "report.subject.series": "todo:t1",
            "report.occurred_at": {"$lt": T0},
        }
    ).explain()

    assert "COLLSCAN" not in str(plan["queryPlanner"]["winningPlan"])
