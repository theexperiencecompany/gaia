"""The Updates feed: how an outbox item reads as a row, and which items each filter asks the repository for."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.agents import OutcomeState
from app.constants.outbox_attention import HoldReason
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.task_report_models import TaskReport
from app.models.updates_models import UpdateFilter, UpdateOutcome
from app.services.outbox import updates
from app.services.outbox.models import (
    ComposeMode,
    DropReason,
    Initiative,
    ItemHold,
    ItemState,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.system_notices import system_notice

USER = "6812f0b3c9a14e2b7d5a91cc"
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _notice(outcome: NoticeOutcome = NoticeOutcome.INFO) -> NoticeReport:
    return system_notice(
        user_id=USER,
        producer=ProducerKind.ACCOUNT,
        subject_kind=SubjectKind.ACCOUNT,
        kind="memory_ready",
        key=USER,
        label="Your memory",
        outcome=outcome,
        facts=["Memories were organized."],
    )


def _run(outcome: OutcomeState) -> RunReport:
    return RunReport(
        report_id=f"ask:{outcome.value}",
        recipient=USER,
        producer=ProducerKind.EXECUTOR,
        subject=Subject(
            kind=SubjectKind.ASK, id="t1", label="Send the invoice", owner_conversation_id="chat-1"
        ),
        occurred_at=T0,
        initiative=Initiative.ASKED,
        report=TaskReport(outcome=outcome),
    )


def _item(
    report: NoticeReport | RunReport,
    state: ItemState = ItemState.SENT,
    *,
    attempt: str | None = "att-1",
    created_minutes: int = 0,
    **fields: object,
) -> OutboxItemDocument:
    return OutboxItemDocument(
        user_id=USER,
        report_id=report.report_id,
        report=report,
        state=state,
        compose_attempt_id=attempt,
        expires_at=T0 + timedelta(days=90),
        created_at=T0 + timedelta(minutes=created_minutes),
        **fields,
    )


def _message(attempt: str = "att-1", parts: tuple[str, ...] = ("Done.",)) -> OutboxMessageDocument:
    return OutboxMessageDocument(
        user_id=USER,
        compose_attempt_id=attempt,
        report_ids=["x"],
        mode=ComposeMode.ANSWER,
        max_class=UrgencyClass.ROUTINE,
        parts=list(parts),
        destination="in_app",
        destination_basis="active_in_app",
        conversation_id="chat-1",
        recorded_in=["chat-1"],
        sent_at=T0 + timedelta(minutes=1),
        expires_at=T0 + timedelta(days=180),
    )


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (_run(OutcomeState.DONE), UpdateOutcome.DONE),
        (_run(OutcomeState.PARTIAL), UpdateOutcome.DONE),
        (_run(OutcomeState.NOTHING_NEW), UpdateOutcome.DONE),
        (_run(OutcomeState.NEEDS_YOU), UpdateOutcome.NEEDS_YOU),
        (_run(OutcomeState.BLOCKED), UpdateOutcome.NEEDS_YOU),
        (_run(OutcomeState.FAILED), UpdateOutcome.FAILED),
        (_run(OutcomeState.UNVERIFIED), UpdateOutcome.FAILED),
        (_notice(NoticeOutcome.INFO), UpdateOutcome.DONE),
        (_notice(NoticeOutcome.NEEDS_YOU), UpdateOutcome.NEEDS_YOU),
        (_notice(NoticeOutcome.FAILED), UpdateOutcome.FAILED),
    ],
)
def test_a_report_reads_as_done_needing_the_user_or_failed(
    report: NoticeReport | RunReport, expected: UpdateOutcome
) -> None:
    assert updates.update_outcome(report) is expected


@pytest.fixture
def repositories():
    with (
        patch.object(updates.outbox_items_repository, "list_feed", new_callable=AsyncMock) as feed,
        patch.object(
            updates.outbox_messages_repository, "list_by_attempts", new_callable=AsyncMock
        ) as messages,
    ):
        feed.return_value = []
        messages.return_value = []
        yield feed, messages


async def test_a_told_item_reads_with_the_message_the_ledger_holds_for_it(repositories) -> None:
    feed, messages = repositories
    feed.return_value = [_item(_run(OutcomeState.DONE))]
    messages.return_value = [_message(parts=("Sent it.", "Priya has it."))]

    page = await updates.read_updates(USER, UpdateFilter.ALL, before=None, limit=10)

    [row] = page.updates
    assert row.told == ["Sent it.", "Priya has it."]
    assert row.told_at == T0 + timedelta(minutes=1)
    assert row.subject_label == "Send the invoice"
    assert row.conversation_id == "chat-1"
    assert row.facts == []
    messages.assert_awaited_once_with(USER, {"att-1"})


async def test_an_item_the_composer_skipped_is_not_shown_as_told_by_its_siblings_message(
    repositories,
) -> None:
    feed, messages = repositories
    sent, skipped = _notice(), _notice().model_copy(update={"report_id": "sys:other"})
    feed.return_value = [
        _item(sent),
        _item(skipped, ItemState.DROPPED, drop_reason=DropReason.COMPOSE_SKIPPED),
    ]
    messages.return_value = [_message()]

    page = await updates.read_updates(USER, UpdateFilter.ALL, before=None, limit=10)

    told, not_told = page.updates
    assert told.told == ["Done."]
    assert (not_told.told, not_told.drop_reason) == (None, DropReason.COMPOSE_SKIPPED)
    assert not_told.facts == ["Memories were organized."]


async def test_a_held_item_says_when_it_is_told(repositories) -> None:
    feed, _ = repositories
    until = T0 + timedelta(hours=3)
    feed.return_value = [
        _item(
            _notice(),
            ItemState.HELD,
            attempt=None,
            hold=ItemHold(reason=HoldReason.CHECKIN, until=until, since=T0),
        )
    ]

    page = await updates.read_updates(USER, UpdateFilter.HELD, before=None, limit=10)

    assert page.updates[0].held_until == until


async def test_a_sent_item_whose_ledger_message_is_gone_fails_loudly(repositories) -> None:
    feed, _ = repositories
    feed.return_value = [_item(_notice())]

    with pytest.raises(ValueError, match="has no ledger message"):
        await updates.read_updates(USER, UpdateFilter.ALL, before=None, limit=10)


async def test_a_full_page_hands_back_the_cursor_of_its_last_row_and_a_short_one_does_not(
    repositories,
) -> None:
    feed, _ = repositories
    first = _item(_notice(), ItemState.DROPPED, attempt=None, created_minutes=9)
    last = _item(
        _notice().model_copy(update={"report_id": "sys:b"}),
        ItemState.DROPPED,
        attempt=None,
        created_minutes=4,
    )
    feed.return_value = [first, last]

    full = await updates.read_updates(USER, UpdateFilter.ALL, before=None, limit=2)
    short = await updates.read_updates(USER, UpdateFilter.ALL, before=None, limit=3)

    assert full.next_before == T0 + timedelta(minutes=4)
    assert short.next_before is None


@pytest.mark.parametrize(
    ("update_filter", "states", "outcomes", "excluded"),
    [
        (UpdateFilter.HELD, {ItemState.HELD}, None, {"progress"}),
        (UpdateFilter.NEEDS_YOU, "listed", {"needs_you", "blocked"}, {"progress"}),
        (UpdateFilter.FAILED, "listed", {"failed", "unverified"}, {"progress"}),
        (
            UpdateFilter.DONE,
            "listed",
            None,
            {"needs_you", "blocked", "failed", "unverified", "progress"},
        ),
        (UpdateFilter.ALL, "listed", None, {"progress"}),
    ],
)
async def test_each_filter_asks_the_repository_for_its_own_states_and_outcomes(
    repositories, update_filter, states, outcomes, excluded
) -> None:
    feed, _ = repositories

    await updates.read_updates(USER, update_filter, before=T0, limit=5)

    kwargs = feed.await_args.kwargs
    assert kwargs["states"] == (
        frozenset(ItemState) - {ItemState.SUPERSEDED} if states == "listed" else states
    )
    assert kwargs["outcomes"] == outcomes
    assert set(kwargs["excluded_outcomes"]) == excluded
    assert (kwargs["before"], kwargs["limit"]) == (T0, 5)


async def test_unseen_updates_are_the_items_told_since_the_instant_without_progress(
    repositories,
) -> None:
    with patch.object(
        updates.outbox_items_repository, "count_told_since", new_callable=AsyncMock
    ) as count:
        count.return_value = 3

        unseen = await updates.count_unseen_updates(USER, T0)

    assert unseen.count == 3
    count.assert_awaited_once_with(USER, T0, excluded_outcomes={"progress"})
