"""The one notification a finished workflow run sends.

It lives in its own module to keep the executor runner free of a circular
import on workflow_tasks (which imports the agent stack).
"""

from datetime import UTC, datetime

from app.constants.notifications import pick_workflow_done_copy
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    RedirectConfig,
    notification_id,
)
from app.services.analytics_service import capture
from app.services.delivery.chat_channel import proactive_destination
from app.services.notification_service import notification_service
from shared.py.analytics import UserId
from shared.py.analytics.catalog.workflows import WorkflowResultDelivered


async def notify_workflow_result(
    *,
    workflow_id: str,
    workflow_title: str,
    execution_id: str,
    conversation_id: str,
    user_id: str,
    result_text: str,
) -> None:
    """Tell the user a run finished: the inbox gets a short heads-up, a chat app the result itself.

    Keyed by the execution, so a retried run delivery sends nothing twice.
    """
    # ``salt`` only rotates the copy per run; it is never shown to the user.
    title, body = pick_workflow_done_copy(
        workflow_id, workflow_title, datetime.now(UTC).isoformat()
    )
    notified = await notification_service.notify(
        NotificationRequest(
            id=notification_id(user_id, "workflow_result", execution_id),
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
            ),
            metadata={"workflow_id": workflow_id, "conversation_id": conversation_id},
            message=result_text,
        )
    )
    capture(
        UserId(user_id),
        WorkflowResultDelivered(
            workflow_id=workflow_id,
            outcome="delivered"
            if notified.record.status is NotificationStatus.DELIVERED
            else "undelivered",
            platform=notified.chat_app.value if notified.chat_app else None,
            **proactive_destination(notified.target),
        ),
    )
