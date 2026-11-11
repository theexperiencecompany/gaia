"""Reminder task handlers for static reminders only."""

import asyncio

from app.agents.core.background.result_delivery import deliver_message_to_conversation
from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.db.repositories.conversations import conversation_repository
from app.decorators.entitlements import capture_paywall_block, is_paid
from app.models.chat_models import ConversationSource
from app.models.reminder_models import (
    AgentType,
    ReminderModel,
    StaticReminderPayload,
)
from app.models.scheduler_models import TaskOutcome
from app.services.analytics_service import capture
from app.services.delivery.chat_channel import (
    ChatChannel,
    ProactiveTarget,
    is_active_place,
    proactive_destination,
    resolve_proactive_target,
)
from app.services.notification_service import notification_service
from app.services.platform_message_service import is_bot_platform
from app.utils.auth_utils import load_user_context
from app.utils.notification.sources import AIProactiveNotificationSource
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
    """Fire a static reminder: raise the in-app badge and deliver it to the user's platforms.

    Delivery is recorded into the conversation's langgraph thread so later turns can backtrack.
    Returns where the platform delivery routed it, or None when that delivery did not happen.
    """
    if not isinstance(reminder.payload, StaticReminderPayload):
        raise ValueError("Invalid payload type for static reminder")

    if not reminder.id:
        raise ValueError("Reminder must have an ID")

    notification = AIProactiveNotificationSource.create_reminder_notification(
        title=reminder.payload.title,
        body=reminder.payload.body,
        reminder_id=reminder.id,
        user_id=reminder.user_id,
        actions=[],
    )

    # Independent sends. The badge is pinned to in-app, so the platform send is the only one.
    _, target = await asyncio.gather(
        notification_service.create_notification(notification),
        _deliver_reminder_to_platforms(reminder),
    )

    log.info("Static reminder sent notification", reminder_id=reminder.id, user_id=reminder.user_id)
    return target


async def _lands_in_source_chat(
    target: ProactiveTarget, conversation_id: str, user_id: str
) -> bool:
    """Whether the reminder goes back into the chat it was set in: yes, unless the user is active elsewhere."""
    if not is_active_place(target):
        return True
    source = await conversation_repository.get_source(conversation_id, user_id=user_id)
    if isinstance(target, ChatChannel):
        return source is target.source
    # Web chats are stored without a source; anything not a chat app's conversation is an app chat.
    return not is_bot_platform(source)


async def _deliver_reminder_to_platforms(reminder: ReminderModel) -> ProactiveTarget | None:
    """Deliver a fired reminder to the one place the user is active, else its source chat and first chat app.

    Side channel behind the in-app badge: swallows every failure — including
    load_user_context's HTTPException on a transient error — so it never fails the
    reminder or skips the recurring re-arm. Returns the target it routed by, None when skipped or failed.
    """
    if not isinstance(reminder.payload, StaticReminderPayload) or not reminder.id:
        return None
    try:
        # Independent reads: who the user is and where they are reachable right now.
        user, target = await asyncio.gather(
            load_user_context(reminder.user_id), resolve_proactive_target(reminder.user_id)
        )
        if user is None:
            log.warning(
                "Reminder platform delivery skipped: user not found",
                reminder_id=reminder.id,
                user_id=reminder.user_id,
            )
            return None
        text = _reminder_result_text(reminder.payload)
        title = reminder.payload.title
        origin = (
            f'reminder "{title}" (id {reminder.id})' if title else f"reminder (id {reminder.id})"
        )

        delivered_source: ConversationSource | None = None
        if reminder.source_conversation_id and await _lands_in_source_chat(
            target, reminder.source_conversation_id, reminder.user_id
        ):
            delivered_source = await deliver_message_to_conversation(
                conversation_id=reminder.source_conversation_id,
                user=user,
                text=text,
                origin=origin,
            )

        await deliver_result_to_platforms(
            user=user,
            user_id=reminder.user_id,
            notification_text=text,
            origin=origin,
            target=target,
            exclude_source=delivered_source,
        )
    except Exception as e:  # side channel; the in-app badge already delivered
        log.error(
            "Reminder platform delivery failed",
            reminder_id=reminder.id,
            user_id=reminder.user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
    return target


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
