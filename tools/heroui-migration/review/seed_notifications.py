"""Write the review user's notifications through the API's own notification storage.

There is no create-notification endpoint, so seed.mjs runs this inside the API
environment: uv run --group backend python seed_notifications.py <user_id> <seeded_at_iso>
"""

import asyncio
from datetime import datetime, timedelta
import sys

from app.db.mongodb.collections import get_async_collection
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelDeliveryStatus,
    NotificationAction,
    NotificationContent,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    RedirectConfig,
)
from app.utils.notification.storage import MongoDBNotificationStorage

NOTIFICATIONS: list[tuple[str, str, NotificationSourceEnum, NotificationType, bool, int]] = [
    # title, body, source, type, read, minutes before the seed
    (
        "Your morning digest is ready",
        "4 threads need a reply today. Priya asked about the design review.",
        NotificationSourceEnum.BACKGROUND_JOB,
        NotificationType.INFO,
        False,
        20,
    ),
    (
        "Added a todo from your email",
        "Book flights for the offsite, due tomorrow.",
        NotificationSourceEnum.AI_TODO_ADDED,
        NotificationType.SUCCESS,
        False,
        95,
    ),
    (
        "Calendar conflict on Friday",
        "Design review overlaps with the team lunch at 1 pm.",
        NotificationSourceEnum.AI_CALENDAR_EVENT,
        NotificationType.WARNING,
        True,
        300,
    ),
    (
        "Weekly review failed to run",
        "Gmail needs to be reconnected before the workflow can read your inbox.",
        NotificationSourceEnum.AI_AGENT,
        NotificationType.ERROR,
        True,
        1500,
    ),
]


async def seed(user_id: str, seeded_at: datetime) -> None:
    """Replace the user's notifications with the fixed review set."""
    await get_async_collection("notifications").delete_many({"user_id": user_id})
    storage = MongoDBNotificationStorage()
    for index, (title, body, source, kind, read, minutes) in enumerate(NOTIFICATIONS):
        created = seeded_at - timedelta(minutes=minutes)
        notification_id = f"5eed0000-0000-4000-9000-{index:012d}"
        actions = [
            NotificationAction(
                id=f"{notification_id}-open",
                type=ActionType.REDIRECT,
                label="Open",
                style=ActionStyle.PRIMARY,
                config=ActionConfig(redirect=RedirectConfig(url="/todos", open_in_new_tab=False)),
            )
        ]
        request = NotificationRequest(
            id=notification_id,
            user_id=user_id,
            source=source,
            type=kind,
            content=NotificationContent(title=title, body=body, actions=actions),
            created_at=created,
        )
        await storage.save_notification(
            NotificationRecord(
                id=notification_id,
                user_id=user_id,
                status=NotificationStatus.READ if read else NotificationStatus.DELIVERED,
                created_at=created,
                delivered_at=created,
                read_at=created + timedelta(minutes=5) if read else None,
                channels=[
                    ChannelDeliveryStatus(
                        channel_type="inapp",
                        status=NotificationStatus.DELIVERED,
                        delivered_at=created,
                    )
                ],
                original_request=request,
                updated_at=created,
            )
        )
    print(f"seeded {len(NOTIFICATIONS)} notifications for {user_id}")


if __name__ == "__main__":
    asyncio.run(seed(sys.argv[1], datetime.fromisoformat(sys.argv[2])))
