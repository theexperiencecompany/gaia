"""Proactive notifications for workflow runs.

These fire from the executor delivery path (``deliver_result``) once a
workflow's executor run finishes. The full result is delivered to the user's
chat as real messages by that path; the completion notification here is just a
short, human in-app heads-up (web only). They live in their own module to keep
the executor runner free of a circular import on ``workflow_tasks`` (which
imports the agent stack).
"""

from datetime import UTC, datetime

from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_INAPP, pick_workflow_done_copy
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.notification_service import notification_service
from shared.py.wide_events import log


async def send_workflow_completion_notification(
    *,
    workflow_id: str,
    workflow_title: str,
    user_id: str,
) -> None:
    """Send the in-app "workflow done" heads-up (web only).

    The workflow's actual result is delivered into the user's chat as real
    messages by the executor delivery path, so this is only a short human nudge
    in the web app: scoped to the in-app channel (no external push), no result
    payload, no "view results" link. Best-effort: never raises into the caller.
    """
    # ``salt`` only rotates the copy per run; it is never shown to the user.
    title, body = pick_workflow_done_copy(
        workflow_id, workflow_title, datetime.now(UTC).isoformat()
    )

    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.WORKFLOW_COMPLETED,
                type=NotificationType.SUCCESS,
                channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
                content=NotificationContent(title=title, body=body),
                metadata={"workflow_id": workflow_id},
            )
        )
        log.info(f"{LogTag.WORKFLOW} Workflow completion notification sent for {workflow_id}")
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Failed to send workflow completion notification for {workflow_id}: {e}"
        )


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
                    title=f"couldn't finish {workflow_title}",
                    body=(
                        f"'{workflow_title}' ran into an error and stopped partway. "
                        "nothing was lost, you can re-run it whenever you're ready."
                    ),
                ),
                metadata={"workflow_id": workflow_id},
            )
        )
        log.info(f"{LogTag.WORKFLOW} Workflow failure notification sent for {workflow_id}")
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Failed to send workflow failure notification for {workflow_id}: {e}"
        )
