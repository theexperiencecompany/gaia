from typing import Annotated, Any, Dict, List, Optional

from app.config.loggers import chat_logger as logger
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.notification_tool_docs import (
    GET_NOTIFICATION_COUNT,
    GET_NOTIFICATIONS,
    MARK_NOTIFICATIONS_READ,
    SEARCH_NOTIFICATIONS,
)
from app.models.notification.notification_models import (
    BulkActions,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.services.notification_service import notification_service
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.utils.chat_utils import get_user_id_from_config


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATIONS)
async def get_notifications(
    config: RunnableConfig,
    status: Annotated[
        Optional[NotificationStatus], "Filter by notification status"
    ] = NotificationStatus.DELIVERED,
    notification_type: Annotated[
        Optional[NotificationType], "Filter by notification type"
    ] = None,
    source: Annotated[
        Optional[NotificationSourceEnum], "Filter by notification source"
    ] = None,
    limit: Annotated[int, "Maximum number of notifications to return"] = 50,
    offset: Annotated[int, "Number of notifications to skip for pagination"] = 0,
) -> Dict[str, Any]:
    """Get user notifications with filtering options."""
    try:
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
        logger.error(f"Error getting notifications: {str(e)}")
        return {"error": str(e), "notifications": []}


@tool
@with_rate_limiting("notification_operations")
@with_doc(SEARCH_NOTIFICATIONS)
async def search_notifications(
    config: RunnableConfig,
    query: Annotated[
        str, "Search query to match against notification titles and content"
    ],
    status: Annotated[
        Optional[NotificationStatus], "Filter by notification status"
    ] = None,
    limit: Annotated[int, "Maximum number of results to return"] = 20,
) -> Dict[str, Any]:
    """Search notifications by content."""
    try:
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
        logger.error(f"Error searching notifications: {str(e)}")
        return {"error": str(e), "notifications": []}


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATION_COUNT)
async def get_notification_count(
    config: RunnableConfig,
    status: Annotated[
        Optional[NotificationStatus], "Filter by notification status"
    ] = None,
) -> Dict[str, Any]:
    """Get count of notifications."""
    try:
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "count": 0}

        total_count = await notification_service.get_user_notifications_count(
            user_id=user_id, status=status
        )

        return {"count": total_count}

    except Exception as e:
        logger.error(f"Error getting notification count: {str(e)}")
        return {"error": str(e), "count": 0}


@tool
@with_rate_limiting("notification_operations")
@with_doc(MARK_NOTIFICATIONS_READ)
async def mark_notifications_read(
    config: RunnableConfig,
    notification_ids: Annotated[List[str], "List of notification IDs to mark as read"],
) -> Dict[str, Any]:
    """Mark one or more notifications as read."""
    try:
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "success": False}

        if not notification_ids:
            return {"error": "No notification IDs provided", "success": False}

        # Handle single notification
        if len(notification_ids) == 1:
            single_result = await notification_service.mark_as_read(
                notification_ids[0], user_id
            )
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
        logger.error(f"Error marking notifications as read: {str(e)}")
        return {"error": str(e), "success": False}


# Export tools for registration
tools = [
    get_notifications,
    search_notifications,
    get_notification_count,
    mark_notifications_read,
]
