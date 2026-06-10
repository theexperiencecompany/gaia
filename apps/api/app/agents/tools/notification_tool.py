from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.notifications import ALL_AUTO_INJECTED_CHANNELS, CHANNEL_TYPE_INAPP
from app.decorators import with_doc, with_rate_limiting
from app.models.notification.notification_models import (
    BulkActions,
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.services.notification_service import notification_service
from app.templates.docstrings.notification_tool_docs import (
    GET_NOTIFICATION_COUNT,
    GET_NOTIFICATION_PREFERENCES,
    GET_NOTIFICATIONS,
    MARK_NOTIFICATIONS_READ,
    SEARCH_NOTIFICATIONS,
    SEND_NOTIFICATION,
)
from app.utils.chat_utils import get_user_id_from_config
from app.utils.notification.channel_preferences import fetch_channel_preferences
from shared.py.wide_events import log


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATIONS)
async def get_notifications(
    config: RunnableConfig,
    status: Annotated[
        NotificationStatus | None, "Filter by notification status"
    ] = NotificationStatus.DELIVERED,
    notification_type: Annotated[NotificationType | None, "Filter by notification type"] = None,
    source: Annotated[NotificationSourceEnum | None, "Filter by notification source"] = None,
    limit: Annotated[int, "Maximum number of notifications to return"] = 50,
    offset: Annotated[int, "Number of notifications to skip for pagination"] = 0,
) -> dict[str, Any]:
    """Get user notifications with filtering options."""
    try:
        log.set(tool={"name": "get_notifications", "action": "get"})
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "notifications": []}

        # Get notifications with all filters
        notifications = await notification_service.get_user_notifications(
            user_id=user_id,
            status=status,
            notification_type=notification_type,
            source=source,
            limit=limit,
            offset=offset,
        )

        # Stream to frontend with notification list UI
        writer = get_stream_writer()
        writer({"notification_data": {"notifications": notifications}})

        return {"notifications": notifications}

    except Exception as e:
        log.error(f"Error getting notifications: {e!s}")
        return {"error": str(e), "notifications": []}


@tool
@with_rate_limiting("notification_operations")
@with_doc(SEARCH_NOTIFICATIONS)
async def search_notifications(
    config: RunnableConfig,
    query: Annotated[str, "Search query to match against notification titles and content"],
    status: Annotated[NotificationStatus | None, "Filter by notification status"] = None,
    limit: Annotated[int, "Maximum number of results to return"] = 20,
) -> dict[str, Any]:
    """Search notifications by content."""
    try:
        log.set(tool={"name": "search_notifications", "action": "search"})
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "notifications": []}

        if not query.strip():
            return {"error": "Search query cannot be empty", "notifications": []}

        # Get notifications for searching
        notifications = await notification_service.get_user_notifications(
            user_id=user_id,
            status=status,
            limit=100,
            offset=0,
        )

        # Simple text search
        query_lower = query.lower()
        matching_notifications = []

        for notification in notifications:
            content = notification.get("content", {})
            title = content.get("title", "")
            body = content.get("body", "")

            if query_lower in title.lower() or query_lower in body.lower():
                matching_notifications.append(notification)

        # Apply limit
        matching_notifications = matching_notifications[:limit]

        # Stream to frontend with notification list UI
        writer = get_stream_writer()
        writer({"notification_data": {"notifications": matching_notifications}})

        return {"notifications": matching_notifications}

    except Exception as e:
        log.error(f"Error searching notifications: {e!s}")
        return {"error": str(e), "notifications": []}


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATION_COUNT)
async def get_notification_count(
    config: RunnableConfig,
    status: Annotated[NotificationStatus | None, "Filter by notification status"] = None,
) -> dict[str, Any]:
    """Get count of notifications."""
    try:
        log.set(tool={"name": "get_notification_count", "action": "count"})
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "count": 0}

        total_count = await notification_service.get_user_notifications_count(
            user_id=user_id, status=status
        )

        return {"count": total_count}

    except Exception as e:
        log.error(f"Error getting notification count: {e!s}")
        return {"error": str(e), "count": 0}


@tool
@with_rate_limiting("notification_operations")
@with_doc(MARK_NOTIFICATIONS_READ)
async def mark_notifications_read(
    config: RunnableConfig,
    notification_ids: Annotated[list[str], "List of notification IDs to mark as read"],
) -> dict[str, Any]:
    """Mark one or more notifications as read."""
    try:
        log.set(tool={"name": "mark_notifications_read", "action": "mark_read"})
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "success": False}

        if not notification_ids:
            return {"error": "No notification IDs provided", "success": False}

        # Handle single notification
        if len(notification_ids) == 1:
            single_result = await notification_service.mark_as_read(notification_ids[0], user_id)
            success = bool(single_result)
        else:
            # Handle multiple notifications
            bulk_result = await notification_service.bulk_actions(
                notification_ids=notification_ids,
                user_id=user_id,
                action=BulkActions.MARK_READ,
            )
            success = any(bulk_result.values())

        return {"success": success}

    except Exception as e:
        log.error(f"Error marking notifications as read: {e!s}")
        return {"error": str(e), "success": False}


@tool
@with_rate_limiting("notification_operations")
@with_doc(SEND_NOTIFICATION)
async def send_notification(
    config: RunnableConfig,
    message: Annotated[str, "Notification body text — keep it concise and actionable"],
    title: Annotated[
        str,
        "Short, specific title summarizing the update (e.g. 'Reminder', 'Task completed', "
        "'Build failed'). Always write a meaningful title — never a generic app name.",
    ],
    channels: Annotated[
        list[str] | None,
        "Channel names to target ('whatsapp', 'telegram', 'discord', 'slack', 'inapp'). "
        "Omit to use all user-enabled channels.",
    ] = None,
    notification_type: Annotated[
        NotificationType | None,
        "Notification type: 'info', 'success', 'warning', or 'error'",
    ] = NotificationType.INFO,
) -> dict[str, Any]:
    """Send a notification to the user on their connected channels."""
    try:
        log.set(tool={"name": "send_notification", "action": "send"})
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "success": False}

        if not message.strip():
            return {"error": "Notification message cannot be empty", "success": False}

        if not title.strip():
            return {"error": "Notification title cannot be empty", "success": False}

        resolved_title = title.strip()
        resolved_message = message.strip()
        resolved_type = notification_type or NotificationType.INFO

        # Build channel configs when specific channels are requested. Unknown
        # channel names would otherwise be accepted and silently skipped at
        # delivery, so reject them here where the LLM can read the error and
        # self-correct.
        channel_configs: list[ChannelConfig] = []
        if channels:
            unknown_channels = [ch for ch in channels if ch not in ALL_AUTO_INJECTED_CHANNELS]
            if unknown_channels:
                return {
                    "error": (
                        f"Unknown channel(s): {', '.join(unknown_channels)}. "
                        f"Valid channels: {', '.join(ALL_AUTO_INJECTED_CHANNELS)}."
                    ),
                    "success": False,
                }
            channel_configs = [ChannelConfig(channel_type=ch) for ch in channels]
        # Empty list triggers auto-injection of all user-enabled channels in the orchestrator

        request = NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_AGENT,
            type=resolved_type,
            channels=channel_configs,
            content=NotificationContent(title=resolved_title, body=resolved_message),
        )

        record = await notification_service.create_notification(request)
        if not record:
            return {"error": "Failed to create notification", "success": False}

        delivered_channels = [
            ch.channel_type
            for ch in record.channels
            if ch.status == NotificationStatus.DELIVERED and not ch.skipped
        ]

        log.set(
            tool={
                "name": "send_notification",
                "notification_id": record.id,
                "status": record.status.value,
                "delivered_channels": delivered_channels,
            }
        )

        result = {
            "success": True,
            "notification_id": record.id,
            "title": resolved_title,
            "message": resolved_message,
            "notification_type": resolved_type.value,
            "status": record.status.value,
            "delivered_channels": delivered_channels,
        }

        # Stream to frontend so the chat renders a "notification sent" card
        writer = get_stream_writer()
        writer({"send_notification_data": result})

        return result

    except Exception as e:
        log.error(f"Error sending notification: {e!s}")
        return {"error": str(e), "success": False}


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATION_PREFERENCES)
async def get_notification_preferences(
    config: RunnableConfig,
) -> dict[str, Any]:
    """Get the user's notification channel preferences."""
    try:
        log.set(tool={"name": "get_notification_preferences", "action": "get"})
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "preferences": {}}

        preferences = await fetch_channel_preferences(user_id)

        # inapp is always available regardless of per-channel preferences;
        # force it last so it can never be overridden by a stored preference.
        all_preferences = {**preferences, CHANNEL_TYPE_INAPP: True}

        return {
            "preferences": all_preferences,
            "available_channels": list(all_preferences.keys()),
            "enabled_channels": [ch for ch, enabled in all_preferences.items() if enabled],
        }

    except Exception as e:
        log.error(f"Error fetching notification preferences: {e!s}")
        return {"error": str(e), "preferences": {}}


# Export tools for registration
tools = [
    get_notifications,
    search_notifications,
    get_notification_count,
    mark_notifications_read,
    send_notification,
    get_notification_preferences,
]
