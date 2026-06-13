"""Proactive notifications for workflow runs.

These fire from the executor delivery path (``_deliver_bg_notification``) once a
workflow's executor run finishes, so the notification carries the real,
comms-voiced result instead of the pre-execution acknowledgment. They live in
their own module to keep the executor runner free of a circular import on
``workflow_tasks`` (which imports the agent stack).
"""

from datetime import UTC, datetime

from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.notifications import pick_workflow_done_copy
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.services.notification_service import notification_service
from app.services.user_service import get_user_by_id
from app.utils.timezone import format_local_time
from shared.py.wide_events import log


async def send_workflow_completion_notification(
    *,
    workflow_id: str,
    workflow_title: str,
    conversation_id: str,
    user_id: str,
    result_text: str,
) -> None:
    """Send the "workflow done" notification, splitting the result into bubbles.

    Best-effort: never raises into the caller.
    """
    message_parts = [p.strip() for p in result_text.split(NEW_MESSAGE_BREAKER) if p.strip()]

    # Format the completion time in the user's own timezone — a UTC stamp is
    # meaningless to someone reading this on their phone. A lookup failure must
    # never block the notification, so fall back to UTC.
    try:
        user_data = await get_user_by_id(user_id)
        user_timezone = user_data.get("timezone") if user_data else None
    except Exception:
        user_timezone = None
    formatted_time = format_local_time(datetime.now(UTC), user_timezone)
    title, body = pick_workflow_done_copy(workflow_id, workflow_title, formatted_time)

    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.WORKFLOW_COMPLETED,
                type=NotificationType.SUCCESS,
                content=NotificationContent(
                    title=title,
                    body=body,
                    actions=[
                        NotificationAction(
                            type=ActionType.REDIRECT,
                            label="View Results",
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url=f"/c/{conversation_id}",
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    ],
                    rich_content={
                        "type": "workflow_execution",
                        "messages": message_parts,
                        "workflow_id": workflow_id,
                        "conversation_id": conversation_id,
                    },
                ),
                metadata={"workflow_id": workflow_id, "conversation_id": conversation_id},
            )
        )
        log.info(f"Workflow completion notification sent for {workflow_id}")
    except Exception as e:
        log.error(f"Failed to send workflow completion notification for {workflow_id}: {e}")


async def send_workflow_failure_notification(
    *,
    workflow_id: str,
    workflow_title: str,
    user_id: str,
) -> None:
    """Send the "workflow failed" notification when the executor run errors."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.WORKFLOW_FAILED,
                type=NotificationType.ERROR,
                content=NotificationContent(
                    title=f"Workflow Failed: {workflow_title}",
                    body=(
                        f"Your workflow '{workflow_title}' encountered an error "
                        f"and could not complete."
                    ),
                ),
                metadata={"workflow_id": workflow_id},
            )
        )
        log.info(f"Workflow failure notification sent for {workflow_id}")
    except Exception as e:
        log.error(f"Failed to send workflow failure notification for {workflow_id}: {e}")
