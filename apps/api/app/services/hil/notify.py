"""Wake a user who is not watching when an approval is waiting.

The approval's entry in the conversation log is its record: open clients render
it off the events stream and a bot's conversation follower asks about it. What
is left is the phone, so the notification goes to push alone, keyed by the
approval so a replayed gate pushes once.
"""

from app.constants.notifications import APPROVAL_PUSH_CATEGORY, CHANNEL_TYPE_PUSH
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    notification_id,
)
from app.services.notification_service import notification_service


async def notify_approval_pending(
    user_id: str,
    conversation_id: str,
    approval_id: str,
    summary: str,
) -> None:
    """Push the pending approval to the user's phones, with approve and deny actions."""
    await notification_service.notify(
        NotificationRequest(
            id=notification_id(user_id, "approval", approval_id),
            user_id=user_id,
            source=NotificationSourceEnum.APPROVAL,
            channels=[ChannelConfig(channel_type=CHANNEL_TYPE_PUSH)],
            content=NotificationContent(title="GAIA needs your approval", body=summary),
            metadata={
                "type": APPROVAL_PUSH_CATEGORY,
                "conversation_id": conversation_id,
                "approval_id": approval_id,
            },
        )
    )
