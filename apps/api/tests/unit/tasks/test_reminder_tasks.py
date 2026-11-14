"""Unit tests for the static reminder task handlers (app.tasks.reminder_tasks).

Pins the payload validation, the one notification a fired reminder becomes and the
analytics naming where it went. What reaches the user, and that a retry sends
nothing twice, is proven in tests/integration/real/test_notify_pipeline_real.py.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import notification_id
from app.models.reminder_models import AgentType, ReminderModel, StaticReminderPayload
from app.services.delivery.chat_channel import ChatChannel, InApp, ProactiveTarget
from app.tasks.reminder_tasks import (
    _execute_static_reminder,
    _reminder_result_text,
    execute_reminder_by_agent,
)
from app.utils.notification.orchestrator import Notified
from shared.py.analytics import UserId
from shared.py.analytics.catalog.delivery import ProactiveDestinationBasis, ProactiveDestinationKind
from shared.py.analytics.catalog.reminders import ReminderCompleted
from shared.py.wide_events import log

MODULE = "app.tasks.reminder_tasks"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
REMINDER_ID = "6812f0b3c9a14e2b7d5a91dd"

TELEGRAM_ACTIVE = ChatChannel(
    source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
)
TELEGRAM_BY_ORDER = ChatChannel(
    source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="priority"
)


@pytest.fixture(autouse=True)
def notify() -> Iterator[AsyncMock]:
    """Route every reminder to the first chat app unless a test says otherwise."""
    with patch(
        f"{MODULE}.notification_service.notify",
        AsyncMock(return_value=Notified(record=MagicMock(), target=TELEGRAM_BY_ORDER)),
    ) as sent:
        yield sent


def _reminder(**overrides) -> ReminderModel:
    payload = overrides.pop("payload", StaticReminderPayload(title="Water the plants", body="Now"))
    return ReminderModel.model_validate(
        {"_id": REMINDER_ID, "user_id": USER_ID, "agent": "static", "payload": payload, **overrides}
    )


async def test_invalid_payload_type_raises() -> None:
    reminder = _reminder(payload={"not": "a static payload"})

    with pytest.raises(ValueError, match="Invalid payload type"):
        await _execute_static_reminder(reminder)


async def test_reminder_without_id_raises() -> None:
    reminder = _reminder()
    reminder.id = None

    with pytest.raises(ValueError, match="must have an ID"):
        await _execute_static_reminder(reminder)


async def test_a_fired_reminder_is_one_notification_keyed_by_its_occurrence(
    notify: AsyncMock,
) -> None:
    await _execute_static_reminder(_reminder(occurrence_count=3, source_conversation_id="conv-1"))

    (request,) = notify.await_args.args
    assert request.id == notification_id(USER_ID, "reminder", REMINDER_ID, "3")
    assert request.content.title == "Water the plants"
    assert request.message == "**Water the plants**\nNow"
    assert request.conversation_id == "conv-1"
    # Routed by the pipeline, not pinned by the producer.
    assert request.channels == []


@pytest.mark.parametrize(
    ("routed_to", "destination", "basis"),
    [
        (TELEGRAM_BY_ORDER, "chat_app", "priority"),
        (TELEGRAM_ACTIVE, "chat_app", "recent_activity"),
        (InApp(reason="active_in_app"), "in_app", "active_in_app"),
        (InApp(reason="no_chat_app"), "in_app", "no_chat_app"),
    ],
)
async def test_reminder_completion_names_where_it_was_routed(
    notify: AsyncMock,
    routed_to: ProactiveTarget,
    destination: ProactiveDestinationKind,
    basis: ProactiveDestinationBasis,
) -> None:
    """A reminder kept in the app for a recently active web user is measurable, not silent."""
    notify.return_value = Notified(record=MagicMock(), target=routed_to)

    with (
        patch("app.tasks.reminder_tasks.capture") as mock_capture,
        patch("app.tasks.reminder_tasks.log.info"),
    ):
        await execute_reminder_by_agent(_reminder())

    mock_capture.assert_called_once_with(
        UserId(USER_ID),
        ReminderCompleted(
            reminder_id=REMINDER_ID,
            agent="static",
            destination=destination,
            destination_basis=basis,
        ),
    )


async def test_reminder_failure_does_not_capture() -> None:
    reminder = _reminder()

    with (
        patch(
            "app.tasks.reminder_tasks.notification_service.notify",
            new_callable=AsyncMock,
            side_effect=RuntimeError("notify down"),
        ),
        patch("app.tasks.reminder_tasks.capture") as mock_capture,
        patch("app.tasks.reminder_tasks.log.info"),
    ):
        with pytest.raises(RuntimeError, match="notify down"):
            await execute_reminder_by_agent(reminder)

    mock_capture.assert_not_called()


async def test_a_failed_reminder_names_the_user_it_failed_for() -> None:
    """Without user_id, an incident can't tell whether one account or the provider is broken."""
    log.reset()
    with (
        patch(
            "app.tasks.reminder_tasks.notification_service.notify",
            new_callable=AsyncMock,
            side_effect=RuntimeError("notify down"),
        ),
        patch(f"{MODULE}.capture"),
    ):
        with pytest.raises(RuntimeError, match="notify down"):
            await execute_reminder_by_agent(_reminder())

    assert log.get()["errors"] == [
        {
            "msg": "Failed to execute reminder",
            "reminder_id": REMINDER_ID,
            "user_id": USER_ID,
            "error_type": "RuntimeError",
            "error": "notify down",
        }
    ]


async def test_a_reminder_with_no_id_is_refused_and_named_in_the_wide_event() -> None:
    """With no id to search by, user_id and agent type are the operator's only handles on this failure."""
    reminder = _reminder()
    reminder.id = None
    log.reset()

    with (
        patch(f"{MODULE}.is_paid", new_callable=AsyncMock) as is_active,
        patch(
            "app.tasks.reminder_tasks.notification_service.notify",
            new_callable=AsyncMock,
        ) as create,
        patch(f"{MODULE}.capture") as mock_capture,
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
    create.assert_not_awaited()
    mock_capture.assert_not_called()


class TestReminderResultText:
    """GAIA voices bold title then body with one blank segment dropped; asserted exactly so a changed marker or separator is caught."""

    def test_title_and_body(self) -> None:
        assert _reminder_result_text(StaticReminderPayload(title="Take pills", body="2 now")) == (
            "**Take pills**\n2 now"
        )

    def test_title_only(self) -> None:
        assert _reminder_result_text(StaticReminderPayload(title="Take pills", body="")) == (
            "**Take pills**"
        )

    def test_body_only_has_no_bold_and_no_leading_newline(self) -> None:
        assert _reminder_result_text(StaticReminderPayload(title="", body="2 now")) == "2 now"

    def test_both_empty(self) -> None:
        assert _reminder_result_text(StaticReminderPayload(title="", body="")) == ""
