"""Reminder task handlers for static reminders only."""

from app.decorators.entitlements import capture_paywall_block, is_paid
from app.models.reminder_models import (
    AgentType,
    ReminderModel,
    StaticReminderPayload,
)
from app.models.scheduler_models import TaskOutcome
from app.services.outbox.intake import submit
from app.services.outbox.models import (
    DeliveryPolicy,
    DeliveryTiming,
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)
from app.utils.occurrence import occurrence_stamp
from shared.py.wide_events import log

#: The surface name a paywalled reminder is attributed to in the funnel. Matches
#: the snake_case surface naming the bot and onboarding gates pass (the HTTP
#: middleware passes the request path instead, which is its surface).
PAYWALL_FEATURE_REMINDER = "reminder"

#: What a reminder with no title is called to the user.
UNTITLED_REMINDER_LABEL = "Reminder"


def _reminder_report(reminder: ReminderModel, payload: StaticReminderPayload) -> NoticeReport:
    """Return the report of one fire: the user set this time themselves, so it is told at that time."""
    if reminder.id is None or reminder.scheduled_at is None:
        raise ValueError("A fired reminder has an id and the time it was armed for")
    occurrence = f"{reminder.id}:{occurrence_stamp(reminder.scheduled_at)}"
    return NoticeReport(
        report_id=f"rem:{occurrence}",
        recipient=reminder.user_id,
        producer=ProducerKind.REMINDER,
        subject=Subject(
            kind=SubjectKind.REMINDER,
            id=occurrence,
            owner_conversation_id=reminder.source_conversation_id,
            label=payload.title or UNTITLED_REMINDER_LABEL,
        ),
        occurred_at=reminder.scheduled_at,
        initiative=Initiative.USER_SCHEDULED,
        delivery_policy=DeliveryPolicy(timing=DeliveryTiming.AT_TIME, may_wake=True),
        outcome=NoticeOutcome.INFO,
        facts=[segment for segment in (payload.title, payload.body) if segment],
    )


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
        if reminder.agent != AgentType.STATIC:
            raise ValueError(f"Unknown agent type: {reminder.agent}")
        if not isinstance(reminder.payload, StaticReminderPayload):
            raise ValueError("Invalid payload type for static reminder")
        await submit(_reminder_report(reminder, reminder.payload))

        log.info("Reminder executed successfully", reminder_id=reminder.id, agent=reminder.agent)
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
