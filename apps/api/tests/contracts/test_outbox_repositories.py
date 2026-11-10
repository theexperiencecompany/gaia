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
from app.services.outbox.models import (
    ComposeMode,
    DeliveryPolicy,
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
    [item] = await items.list_for_subject(USER, "s1")
    assert item.state is ItemState.COMPOSING


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

    states = {i.report_id: i.state for i in await items.list_for_subject(USER, "s1")}
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
