"""Reminder task handlers for static reminders only."""

from app.decorators.entitlements import capture_paywall_block, is_paid
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    notification_id,
)
from app.models.reminder_models import (
    AgentType,
    ReminderModel,
    StaticReminderPayload,
)
from app.models.scheduler_models import TaskOutcome
from app.services.analytics_service import capture
from app.services.delivery.chat_channel import ProactiveTarget, proactive_destination
from app.services.notification_service import notification_service
from shared.py.analytics import UserId
from shared.py.analytics.catalog.reminders import ReminderCompleted
from shared.py.wide_events import log

#: The surface name a paywalled reminder is attributed to in the funnel. Matches
#: the snake_case surface naming the bot and onboarding gates pass (the HTTP
#: middleware passes the request path instead, which is its surface).
PAYWALL_FEATURE_REMINDER = "reminder"


def _reminder_result_text(payload: StaticReminderPayload) -> str:
    """Format the reminder body as GAIA would voice it into a chat: bold title, then body."""
    segments = [
        seg for seg in (f"**{payload.title}**" if payload.title else "", payload.body) if seg
    ]
    return "\n".join(segments)


async def _execute_static_reminder(reminder: ReminderModel) -> ProactiveTarget | None:
    """Fire a static reminder through the one notify pipeline; return where routing found the user.

    The id is the reminder's occurrence, so a retried job sends nothing twice.
    """
    if not isinstance(reminder.payload, StaticReminderPayload):
        raise ValueError("Invalid payload type for static reminder")

    if not reminder.id:
        raise ValueError("Reminder must have an ID")

    notified = await notification_service.notify(
        NotificationRequest(
            id=notification_id(
                reminder.user_id, "reminder", reminder.id, str(reminder.occurrence_count)
            ),
            user_id=reminder.user_id,
            source=NotificationSourceEnum.AI_REMINDER,
            priority=1,
            content=NotificationContent(title=reminder.payload.title, body=reminder.payload.body),
            metadata={"reminder_id": reminder.id},
            conversation_id=reminder.source_conversation_id,
            message=_reminder_result_text(reminder.payload),
        )
    )
    log.info("Static reminder sent notification", reminder_id=reminder.id, user_id=reminder.user_id)
    return notified.target


async def execute_reminder_by_agent(
    reminder: ReminderModel,
) -> TaskOutcome:
    """Execute a static reminder task; the only agent type handled here is STATIC."""
    log.info("Executing reminder", reminder_id=reminder.id, agent=reminder.agent)

    if not reminder.id:
        log.error(
            "Reminder has no ID, skipping execution",
            agent=reminder.agent,
            user_id=reminder.user_id,
        )
        raise ValueError(f"Reminder {reminder.id} has no ID, skipping execution.")

    # The scheduler pauses a blocked recurring reminder, so this fires once per job.
    if not await is_paid(reminder.user_id):
        log.warning(
            "Reminder skipped — subscription required",
            reminder_id=reminder.id,
            user_id=reminder.user_id,
        )
        # Same event every HTTP/bot paywall block fires; this gate skips instead
        # of going through require_active_subscription, so without it the funnel
        # could not see reminders lost to the wall.
        capture_paywall_block(reminder.user_id, PAYWALL_FEATURE_REMINDER)
        return TaskOutcome.ENTITLEMENT_BLOCKED

    try:
        if reminder.agent == AgentType.STATIC:
            target = await _execute_static_reminder(reminder)
        else:
            raise ValueError(f"Unknown agent type: {reminder.agent}")

        log.info("Reminder executed successfully", reminder_id=reminder.id, agent=reminder.agent)
        capture(
            UserId(reminder.user_id),
            ReminderCompleted(
                reminder_id=reminder.id,
                agent=reminder.agent.value,
                **proactive_destination(target),
            ),
        )
        return TaskOutcome.EXECUTED
    except Exception as e:
        log.error(
            "Failed to execute reminder",
            reminder_id=reminder.id,
            user_id=reminder.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise
