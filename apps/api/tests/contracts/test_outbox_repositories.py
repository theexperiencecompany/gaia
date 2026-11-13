"""Contract tests for the outbox repositories, on real Mongo: the compare-and-set and unique inserts the state machine rests on."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.outbox import ITEMS_COLLECTION, MESSAGES_COLLECTION
from app.constants.outbox_attention import ATTENTION_SETTINGS_COLLECTION
from app.constants.outbox_judge import ATTENTION_PROFILES_COLLECTION
from app.db.mongodb.indexes import create_outbox_indexes
from app.db.repositories.attention_profiles import AttentionProfilesRepository
from app.db.repositories.outbox_items import OutboxItemsRepository
from app.db.repositories.outbox_messages import OutboxMessagesRepository
from app.models.attention_profile_models import ProfileAnswer
from app.models.outbox_models import OutboxMessageDocument
from app.models.ownership_models import DeliveryPolicy
from app.services.outbox.judge_models import ItemJudgement, Relevance, Sensitivity
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
from tests._harness.judge import verdict

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
        ATTENTION_PROFILES_COLLECTION: f"{ATTENTION_PROFILES_COLLECTION}_{suffix}",
        ATTENTION_SETTINGS_COLLECTION: f"{ATTENTION_SETTINGS_COLLECTION}_{suffix}",
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


def _message(attempt: str, *, conversation_id: str = "c") -> OutboxMessageDocument:
    return OutboxMessageDocument(
        user_id=USER,
        compose_attempt_id=attempt,
        report_ids=["a"],
        mode=ComposeMode.ANSWER,
        max_class=UrgencyClass.ROUTINE,
        parts=["hi"],
        destination="in_app",
        destination_basis="no_chat_app",
        conversation_id=conversation_id,
        recorded_in=[conversation_id],
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


async def test_recent_sent_in_lists_only_what_was_sent_to_that_conversation(repos) -> None:
    _, messages = repos
    for attempt, conversation in (("here", "tg-dm"), ("there", "web-1")):
        await messages.insert_attempt(_message(attempt, conversation_id=conversation))
        assert await messages.finish_send(USER, attempt, MessageState.SENT, sent_at=T0)

    recent = await messages.recent_sent_in(USER, "tg-dm", limit=5)

    assert [m.compose_attempt_id for m in recent] == ["here"]


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


def _judgement(**verdict_fields: object) -> ItemJudgement:
    return ItemJudgement(
        verdict=verdict(**verdict_fields),
        raised_interrupt=bool(verdict_fields.get("urgency") is UrgencyClass.INTERRUPT),
        sensitivity=Sensitivity.FINANCE,
    )


async def test_the_judgement_is_kept_on_the_item_it_queued_and_reads_back_whole(repos) -> None:
    items, _ = repos
    await items.insert_if_new(_report("a"), expires_at=EXPIRES)
    kept = _judgement(deliver_by=T0 + timedelta(hours=2), topics=["money"], reason="card declined")

    queued = await items.queue(
        USER, "a", urgency=UrgencyClass.TIMELY, mode=ComposeMode.UNSOLICITED, judgement=kept
    )

    stored = await items.get_by_report(USER, "a")
    assert queued is not None and stored is not None
    assert stored.judgement == kept
    assert stored.urgency is UrgencyClass.TIMELY


async def test_the_judgement_is_kept_on_an_item_recorded_and_not_alerted(repos) -> None:
    items, _ = repos
    await items.insert_if_new(_report("a"), expires_at=EXPIRES)
    kept = _judgement(relevance=Relevance.MOOT, not_worth_probability=0.9)

    await items.drop(USER, "a", DropReason.MOOT, judgement=kept)

    stored = await items.get_by_report(USER, "a")
    assert stored is not None
    assert (stored.state, stored.drop_reason) == (ItemState.DROPPED, DropReason.MOOT)
    assert stored.judgement == kept


async def test_an_item_no_judge_was_asked_about_has_no_judgement(repos) -> None:
    items, _ = repos
    await _queued(items, _report("a"))

    stored = await items.get_by_report(USER, "a")

    assert stored is not None and stored.judgement is None


async def test_interrupts_the_judge_raised_are_counted_since_a_cutoff_for_this_user_only(
    repos,
) -> None:
    items, _ = repos
    for report_id, urgency in (("i1", UrgencyClass.INTERRUPT), ("i2", UrgencyClass.INTERRUPT)):
        await items.insert_if_new(_report(report_id), expires_at=EXPIRES)
        await items.queue(
            USER,
            report_id,
            urgency=urgency,
            mode=ComposeMode.INTERRUPT,
            judgement=_judgement(urgency=urgency),
        )
    await items.insert_if_new(_report("calm"), expires_at=EXPIRES)
    await items.queue(
        USER, "calm", urgency=UrgencyClass.ROUTINE, mode=ComposeMode.ANSWER, judgement=_judgement()
    )

    now = datetime.now(UTC)

    assert await items.count_raised_interrupts_since(USER, now - timedelta(hours=1)) == 2
    assert await items.count_raised_interrupts_since(USER, now + timedelta(hours=1)) == 0
    assert await items.count_raised_interrupts_since("someone-else", now - timedelta(hours=1)) == 0


async def test_unsettled_items_exclude_the_one_asked_about_and_anything_settled(repos) -> None:
    items, _ = repos
    await items.insert_if_new(_report("received"), expires_at=EXPIRES)
    await _queued(items, _report("queued", subject="s2"))
    await items.insert_if_new(_report("done", subject="s3"), expires_at=EXPIRES)
    await items.drop(USER, "done", DropReason.NOTHING_NEW)

    others = await items.list_unsettled(USER, exclude_report_id="received", limit=10)

    assert [item.report_id for item in others] == ["queued"]


async def test_waits_are_the_items_the_judge_told_to_wait_newest_first(repos) -> None:
    items, _ = repos
    for report_id, run in (("w1", "workflow:a"), ("w2", "todo:b")):
        await items.insert_if_new(_report(report_id, subject=report_id), expires_at=EXPIRES)
        await items.queue(
            USER,
            report_id,
            urgency=UrgencyClass.ROUTINE,
            mode=ComposeMode.UNSOLICITED,
            judgement=_judgement(wait_for_run=run),
        )
    await _queued(items, _report("plain", subject="plain"))

    waits = await items.list_waits(USER, limit=5)

    assert [item.report_id for item in waits] == ["w2", "w1"]


async def test_settled_items_of_an_owner_conversation_are_what_its_hit_rate_reads(repos) -> None:
    items, _ = repos
    owned = _report("sent").model_copy(
        update={
            "subject": Subject(
                kind=SubjectKind.TODO_RUN, id="sent", label="L", owner_conversation_id="chat-1"
            )
        }
    )
    skipped = owned.model_copy(
        update={
            "report_id": "skipped",
            "subject": owned.subject.model_copy(update={"id": "skipped"}),
            "occurred_at": T0 + timedelta(minutes=1),
        }
    )
    for report in (owned, skipped):
        await items.insert_if_new(report, expires_at=EXPIRES)
    await items.drop(USER, "skipped", DropReason.NOTHING_NEW)
    await items.queue(USER, "sent", urgency=UrgencyClass.ROUTINE, mode=ComposeMode.ANSWER)
    [claimed] = await items.claim_queued_for_subject(USER, "sent", "att")
    await items.begin_send(USER, "att")
    await items.finish_send(USER, "att", ItemState.SENT)

    settled = await items.list_settled_for_owner(USER, "chat-1", limit=10)

    assert [(i.report_id, i.state) for i in settled] == [
        ("skipped", ItemState.DROPPED),
        ("sent", ItemState.SENT),
    ]
    assert claimed.report_id == "sent"
    assert await items.list_settled_for_owner(USER, "chat-2", limit=10) == []


async def test_what_was_sent_since_a_cutoff_is_the_ledger_window(repos) -> None:
    _, messages = repos
    for attempt, at in (("old", T0 - timedelta(hours=30)), ("new", T0 - timedelta(hours=1))):
        await messages.insert_attempt(_message(attempt))
        await messages.finish_send(USER, attempt, MessageState.SENT, sent_at=at)
    await messages.insert_attempt(_message("unsent"))

    window = await messages.sent_since(USER, T0 - timedelta(hours=24), limit=5)

    assert [m.compose_attempt_id for m in window] == ["new"]


@pytest.fixture
async def profiles(repos) -> AttentionProfilesRepository:
    return AttentionProfilesRepository()


SEED = [ProfileAnswer(q="Weekends?", a="Keep work out.")]


async def test_a_users_profile_is_seeded_the_first_time_it_is_read(profiles) -> None:
    first = await profiles.get_or_seed(USER, SEED)

    assert (first.user_id, first.version, first.answers) == (USER, 1, SEED)


async def test_a_later_read_returns_the_stored_profile_not_a_fresh_seed(profiles) -> None:
    await profiles.get_or_seed(USER, SEED)

    again = await profiles.get_or_seed(USER, [ProfileAnswer(q="other", a="seed")])

    assert again.answers == SEED


async def test_concurrent_first_reads_agree_on_one_profile(profiles) -> None:
    seeds = [[ProfileAnswer(q=f"q{n}", a="a")] for n in range(8)]

    read = await asyncio.gather(*(profiles.get_or_seed(USER, seed) for seed in seeds))

    assert len({tuple(p.answers) for p in read}) == 1
    assert await profiles.count_for_user(USER) == 1


async def test_profiles_are_per_user(profiles) -> None:
    await profiles.get_or_seed(USER, SEED)

    other = await profiles.get_or_seed("another-user", [ProfileAnswer(q="q", a="a")])

    assert other.answers == [ProfileAnswer(q="q", a="a")]
