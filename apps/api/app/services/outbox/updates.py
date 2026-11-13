"""The Updates feed: a page of what GAIA told or only recorded, read off the outbox ledger.

An item carries the facts and where it stands; a told item also carries the message the
ledger holds for it. Items a newer report replaced are not listed, and neither is progress,
which only ever said where a run was on its way.
"""

from datetime import datetime

from app.constants.agents import OutcomeState
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.updates_models import (
    UnseenUpdates,
    UpdateFilter,
    UpdateOutcome,
    UpdateRow,
    UpdatesResponse,
)
from app.services.outbox.models import (
    NEEDS_YOU_OUTCOMES,
    ItemState,
    NoticeOutcome,
    NoticeReport,
    OutboxReport,
    RunReport,
    facts_of,
)

_FAILED = frozenset({OutcomeState.FAILED.value, OutcomeState.UNVERIFIED.value})
_PROGRESS = frozenset({NoticeOutcome.PROGRESS.value})

_LISTED_STATES = frozenset(ItemState) - {ItemState.SUPERSEDED}


def _outcome_value(report: OutboxReport) -> str:
    match report:
        case RunReport(report=task_report):
            return task_report.outcome.value if task_report.outcome else ""
        case NoticeReport(outcome=outcome):
            return outcome.value


def update_outcome(report: OutboxReport) -> UpdateOutcome:
    """Return how the report left what it is about: it needs the user, failed, only informs, or is done."""
    value = _outcome_value(report)
    if value in NEEDS_YOU_OUTCOMES:
        return UpdateOutcome.NEEDS_YOU
    if value in _FAILED:
        return UpdateOutcome.FAILED
    if value == NoticeOutcome.INFO.value:
        return UpdateOutcome.INFO
    return UpdateOutcome.DONE


def _row(item: OutboxItemDocument, message: OutboxMessageDocument | None) -> UpdateRow:
    report = item.report
    if item.created_at is None:
        raise ValueError(f"outbox item {item.report_id} was stored without a creation time")
    return UpdateRow(
        report_id=item.report_id,
        subject_kind=report.subject.kind,
        subject_label=report.subject.label,
        outcome=UpdateOutcome.DONE if item.resolved_at is not None else update_outcome(report),
        state=item.state,
        drop_reason=item.drop_reason,
        facts=facts_of(report),
        display=report.display if isinstance(report, NoticeReport) else None,
        told=message.parts if message is not None else None,
        held_until=item.hold.until
        if item.hold is not None and item.state is ItemState.HELD
        else None,
        conversation_id=report.subject.owner_conversation_id,
        occurred_at=report.occurred_at,
        told_at=message.sent_at if message is not None else None,
        resolved_at=item.resolved_at,
        created_at=item.created_at,
    )


async def _told_messages(
    user_id: str, items: list[OutboxItemDocument]
) -> dict[str, OutboxMessageDocument]:
    """Return the ledger message of each sent item, by compose attempt."""
    attempts = {
        item.compose_attempt_id
        for item in items
        if item.state is ItemState.SENT and item.compose_attempt_id is not None
    }
    if not attempts:
        return {}
    messages = await outbox_messages_repository.list_by_attempts(user_id, attempts)
    return {message.compose_attempt_id: message for message in messages}


def _told(
    item: OutboxItemDocument, messages: dict[str, OutboxMessageDocument]
) -> OutboxMessageDocument | None:
    """Return the message that told the item; a skipped item shares its attempt with the ones told, and was not."""
    if item.state is not ItemState.SENT or item.compose_attempt_id is None:
        return None
    message = messages.get(item.compose_attempt_id)
    if message is None:
        raise ValueError(f"sent outbox item {item.report_id} has no ledger message")
    return message


async def read_updates(
    user_id: str, update_filter: UpdateFilter, *, before: datetime | None, limit: int
) -> UpdatesResponse:
    """Return a page of the user's updates, newest first, narrowed by the filter."""
    match update_filter:
        case UpdateFilter.HELD:
            states, outcomes, excluded = {ItemState.HELD}, None, _PROGRESS
        case UpdateFilter.NEEDS_YOU:
            states, outcomes, excluded = _LISTED_STATES, NEEDS_YOU_OUTCOMES, _PROGRESS
        case UpdateFilter.FAILED:
            states, outcomes, excluded = _LISTED_STATES, _FAILED, _PROGRESS
        case UpdateFilter.DONE:
            states, outcomes, excluded = (
                _LISTED_STATES,
                None,
                NEEDS_YOU_OUTCOMES | _FAILED | _PROGRESS,
            )
        case UpdateFilter.ALL:
            states, outcomes, excluded = _LISTED_STATES, None, _PROGRESS
    items = await outbox_items_repository.list_feed(
        user_id,
        states=states,
        outcomes=outcomes,
        excluded_outcomes=excluded,
        before=before,
        limit=limit,
    )
    messages = await _told_messages(user_id, items)
    rows = [_row(item, _told(item, messages)) for item in items]
    return UpdatesResponse(
        updates=rows,
        next_before=rows[-1].created_at if len(rows) == limit else None,
    )


async def count_unseen_updates(user_id: str, since: datetime) -> UnseenUpdates:
    """Return how many updates were told to the user since the instant."""
    told = await outbox_items_repository.count_told_since(
        user_id, since, excluded_outcomes=_PROGRESS
    )
    return UnseenUpdates(count=told)
