"""A fired static reminder is one report to the outbox, which words and routes it.

The reminder task never sends: it submits a NoticeReport whose id names the
occurrence, so a second fire of the same occurrence is the same report.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.reminder_models import AgentType, ReminderModel, StaticReminderPayload
from app.models.scheduler_models import TaskOutcome
from app.services.outbox.models import (
    DeliveryTiming,
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    SubjectKind,
)
from app.tasks.reminder_tasks import execute_reminder_by_agent
from app.utils.occurrence import occurrence_stamp
from shared.py.wide_events import log

MODULE = "app.tasks.reminder_tasks"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
REMINDER_ID = "6812f0b3c9a14e2b7d5a91dd"
FIRES_AT = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def paying_user():
    with patch(f"{MODULE}.is_paid", AsyncMock(return_value=True)):
        yield


def _reminder(**overrides: object) -> ReminderModel:
    fields: dict[str, object] = {
        "_id": REMINDER_ID,
        "user_id": USER_ID,
        "agent": "static",
        "payload": StaticReminderPayload(title="Water the plants", body="Now"),
        "scheduled_at": FIRES_AT,
        "source_conversation_id": "conv-1",
        **overrides,
    }
    return ReminderModel.model_validate(fields)


async def _submitted(reminder: ReminderModel) -> NoticeReport:
    with patch(f"{MODULE}.submit", new_callable=AsyncMock) as submit:
        outcome = await execute_reminder_by_agent(reminder)
    assert outcome is TaskOutcome.EXECUTED
    submit.assert_awaited_once()
    report = submit.await_args.args[0]
    assert isinstance(report, NoticeReport)
    return report


async def test_a_fire_submits_one_notice_the_user_set_themselves() -> None:
    report = await _submitted(_reminder())

    assert report.producer is ProducerKind.REMINDER
    assert report.recipient == USER_ID
    assert report.outcome is NoticeOutcome.INFO
    assert report.initiative is Initiative.USER_SCHEDULED
    assert report.delivery_policy.timing is DeliveryTiming.AT_TIME
    assert report.delivery_policy.may_wake is True
    assert report.occurred_at == FIRES_AT
    assert report.facts == ["Water the plants", "Now"]


async def test_the_subject_names_the_occurrence_and_the_chat_that_set_it() -> None:
    report = await _submitted(_reminder())

    assert report.subject.kind is SubjectKind.REMINDER
    assert report.subject.id == f"{REMINDER_ID}:{occurrence_stamp(FIRES_AT)}"
    assert report.subject.owner_conversation_id == "conv-1"
    assert report.subject.label == "Water the plants"


async def test_the_same_occurrence_is_the_same_report_and_the_next_is_another() -> None:
    first = await _submitted(_reminder())
    again = await _submitted(_reminder())
    next_day = await _submitted(_reminder(scheduled_at=datetime(2026, 11, 11, 9, 0, tzinfo=UTC)))

    assert first.report_id == again.report_id == f"rem:{first.subject.id}"
    assert next_day.report_id != first.report_id


async def test_a_reminder_set_outside_a_chat_has_no_owner_conversation() -> None:
    report = await _submitted(_reminder(source_conversation_id=None))

    assert report.subject.owner_conversation_id is None


async def test_an_untitled_reminder_is_labelled_and_says_its_body() -> None:
    report = await _submitted(
        _reminder(payload=StaticReminderPayload(title="", body="Call the bank"))
    )

    assert report.subject.label == "Reminder"
    assert report.facts == ["Call the bank"]


async def test_a_failed_submit_fails_the_reminder_loudly_naming_the_user() -> None:
    log.reset()
    with patch(f"{MODULE}.submit", AsyncMock(side_effect=RuntimeError("queue down"))):
        with pytest.raises(RuntimeError, match="queue down"):
            await execute_reminder_by_agent(_reminder())

    assert log.get()["errors"] == [
        {
            "msg": "Failed to execute reminder",
            "reminder_id": REMINDER_ID,
            "user_id": USER_ID,
            "error_type": "RuntimeError",
            "error": "queue down",
        }
    ]


async def test_a_payload_that_is_not_a_static_reminder_is_refused() -> None:
    with patch(f"{MODULE}.submit", new_callable=AsyncMock) as submit:
        with pytest.raises(ValueError, match="Invalid payload type"):
            await execute_reminder_by_agent(_reminder(payload={"not": "a static payload"}))

    submit.assert_not_awaited()


async def test_a_reminder_with_no_id_is_refused_and_named_in_the_wide_event() -> None:
    """With no id to search by, user_id and agent type are the operator's only handles on this failure."""
    reminder = _reminder()
    reminder.id = None
    log.reset()

    with (
        patch(f"{MODULE}.is_paid", new_callable=AsyncMock) as is_active,
        patch(f"{MODULE}.submit", new_callable=AsyncMock) as submit,
    ):
        with pytest.raises(ValueError, match="has no ID, skipping execution"):
            await execute_reminder_by_agent(reminder)

    assert log.get()["errors"] == [
        {
            "msg": "Reminder has no ID, skipping execution",
            "agent": AgentType.STATIC,
            "user_id": USER_ID,
        }
    ]
    is_active.assert_not_awaited()
    submit.assert_not_awaited()
