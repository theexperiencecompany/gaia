from typing import Annotated, Any, NotRequired, TypeAlias, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.decorators import with_doc, with_rate_limiting
from app.models.agent_models import current_stream_writer, get_user_id
from app.models.notification.notification_models import (
    BulkActions,
    NotificationListFilters,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    NotificationView,
)
from app.services.notification_service import notification_service
from app.templates.docstrings.notification_tool_docs import (
    GET_NOTIFICATION_COUNT,
    GET_NOTIFICATION_PREFERENCES,
    GET_NOTIFICATIONS,
    MARK_NOTIFICATIONS_READ,
    SEARCH_NOTIFICATIONS,
)
from app.utils.notification.channel_preferences import fetch_channel_preferences
from shared.py.wide_events import log

# NotificationView.model_dump(mode="json") — json mode matters: python mode
# leaves enum members in the dict, which LangChain then stringifies as
# ``<NotificationStatus.DELIVERED: 'delivered'>`` instead of ``'delivered'``.
SerializedNotification: TypeAlias = dict[str, Any]


# Tool return shapes are plain TypedDicts, not models: LangChain stringifies
# the returned object into the ToolMessage the LLM reads.


class NotificationListResult(TypedDict):
    """``get_notifications`` / ``search_notifications``."""

    notifications: list[SerializedNotification]
    error: NotRequired[str]


class NotificationCountResult(TypedDict):
    """``get_notification_count``."""

    count: int
    error: NotRequired[str]


class MarkReadResult(TypedDict):
    """``mark_notifications_read``."""

    success: bool
    error: NotRequired[str]


class NotificationPreferencesResult(TypedDict):
    """``get_notification_preferences``. The channel lists are absent on the
    error path, which returns only ``error`` and an empty ``preferences``."""

    preferences: dict[str, bool]
    available_channels: NotRequired[list[str]]
    enabled_channels: NotRequired[list[str]]
    error: NotRequired[str]


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
) -> NotificationListResult:
    """Get user notifications with filtering options."""
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_notifications", "action": "get"})

        # Get notifications with all filters
        notifications = await notification_service.get_user_notifications(
            user_id,
            filters=NotificationListFilters(
                status=status,
                notification_type=notification_type,
                source=source,
                limit=limit,
                offset=offset,
            ),
        )

        # The stream/tool payload must stay JSON-shaped (see ToolData.data), so the
        # views are dumped back to dicts here rather than handed over as models.
        serialized = [n.model_dump(mode="json") for n in notifications]

        # Stream to frontend with notification list UI
        writer = current_stream_writer()
        writer({"notification_data": {"notifications": serialized}})

        return {"notifications": serialized}

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error getting notifications", error_type=type(e).__name__)
        return {"error": str(e), "notifications": []}


@tool
@with_rate_limiting("notification_operations")
@with_doc(SEARCH_NOTIFICATIONS)
async def search_notifications(
    config: RunnableConfig,
    query: Annotated[str, "Search query to match against notification titles and content"],
    status: Annotated[NotificationStatus | None, "Filter by notification status"] = None,
    limit: Annotated[int, "Maximum number of results to return"] = 20,
) -> NotificationListResult:
    """Search notifications by content."""
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "search_notifications", "action": "search"})

        if not query.strip():
            return {"error": "Search query cannot be empty", "notifications": []}

        # Get notifications for searching
        notifications = await notification_service.get_user_notifications(
            user_id,
            filters=NotificationListFilters(status=status, limit=100),
        )

        # Simple text search
        query_lower = query.lower()
        matching_notifications: list[NotificationView] = []

        for notification in notifications:
            content = notification.content
            if query_lower in content.title.lower() or query_lower in content.body.lower():
                matching_notifications.append(notification)

        # Apply limit
        serialized = [n.model_dump(mode="json") for n in matching_notifications[:limit]]

        # Stream to frontend with notification list UI
        writer = current_stream_writer()
        writer({"notification_data": {"notifications": serialized}})

        return {"notifications": serialized}

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error searching notifications", error_type=type(e).__name__)
        return {"error": str(e), "notifications": []}


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATION_COUNT)
async def get_notification_count(
    config: RunnableConfig,
    status: Annotated[NotificationStatus | None, "Filter by notification status"] = None,
) -> NotificationCountResult:
    """Get count of notifications."""
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_notification_count", "action": "count"})

        total_count = await notification_service.get_user_notifications_count(
            user_id=user_id, status=status
        )

        return {"count": total_count}

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error getting notification count", error_type=type(e).__name__)
        return {"error": str(e), "count": 0}


@tool
@with_rate_limiting("notification_operations")
@with_doc(MARK_NOTIFICATIONS_READ)
async def mark_notifications_read(
    config: RunnableConfig,
    notification_ids: Annotated[list[str], "List of notification IDs to mark as read"],
) -> MarkReadResult:
    """Mark one or more notifications as read."""
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "mark_notifications_read", "action": "mark_read"})

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
        log.error(f"{LogTag.TOOL} Error marking notifications as read", error_type=type(e).__name__)
        return {"error": str(e), "success": False}


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATION_PREFERENCES)
async def get_notification_preferences(
    config: RunnableConfig,
) -> NotificationPreferencesResult:
    """Get the user's notification channel preferences."""
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_notification_preferences", "action": "get"})

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
        log.error(
            f"{LogTag.TOOL} Error fetching notification preferences", error_type=type(e).__name__
        )
        return {"error": str(e), "preferences": {}}


# Export tools for registration
tools = [
    get_notifications,
    search_notifications,
    get_notification_count,
    mark_notifications_read,
    get_notification_preferences,
]
