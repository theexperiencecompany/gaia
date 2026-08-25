from typing import Annotated, Any, Literal, NotRequired, TypeAlias, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.log_tags import LogTag
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
    NotificationView,
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

# A NotificationView serialized with ``model_dump(mode="json")`` — the stream/tool
# payload must stay JSON-shaped (see ToolData.data), so views are dumped, not
# passed on as models. json mode matters: the default python mode leaves enum
# *members* in the dict, which LangChain then stringifies into the ToolMessage as
# ``<NotificationStatus.DELIVERED: 'delivered'>`` instead of ``'delivered'``.
SerializedNotification: TypeAlias = dict[str, Any]


# ---------------------------------------------------------------------------
# Tool return shapes. Plain TypedDicts, not models: LangChain stringifies the
# returned object into the ToolMessage the LLM reads, so the runtime value must
# stay the exact dict it is today. ``error`` is ``NotRequired`` because the
# success paths omit it entirely.
# ---------------------------------------------------------------------------


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


class SentNotificationResult(TypedDict):
    """``send_notification`` on success — also the ``send_notification_data``
    stream payload that renders the "notification sent" chat card."""

    success: Literal[True]
    notification_id: str
    title: str
    message: str
    notification_type: str
    status: str
    delivered_channels: list[str]


class SendNotificationFailure(TypedDict):
    """``send_notification`` when validation or delivery setup failed."""

    error: str
    success: Literal[False]


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

        # The stream/tool payload must stay JSON-shaped (see ToolData.data), so the
        # views are dumped back to dicts here rather than handed over as models.
        serialized = [n.model_dump(mode="json") for n in notifications]

        # Stream to frontend with notification list UI
        writer = get_stream_writer()
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
        matching_notifications: list[NotificationView] = []

        for notification in notifications:
            content = notification.content
            if query_lower in content.title.lower() or query_lower in content.body.lower():
                matching_notifications.append(notification)

        # Apply limit
        serialized = [n.model_dump(mode="json") for n in matching_notifications[:limit]]

        # Stream to frontend with notification list UI
        writer = get_stream_writer()
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
        log.error(f"{LogTag.TOOL} Error marking notifications as read", error_type=type(e).__name__)
        return {"error": str(e), "success": False}


@tool
@with_rate_limiting("notification_operations")
@with_doc(SEND_NOTIFICATION)
async def send_notification(
    config: RunnableConfig,
    message: Annotated[str, "Notification body text: keep it concise and actionable"],
    title: Annotated[
        str,
        "Short, specific title summarizing the update (e.g. 'Reminder', 'Task completed', "
        "'Build failed'). Always write a meaningful title, never a generic app name.",
    ],
    channels: Annotated[
        list[str],
        "Channel names to target ('whatsapp', 'telegram', 'discord', 'slack', 'inapp'). "
        "REQUIRED: pass exactly the channel(s) the user named. If the user did not name a "
        "channel, ASK them which channel(s) they want before calling this tool. Never guess "
        "and never broadcast to channels the user did not ask for.",
    ],
    notification_type: Annotated[
        NotificationType | None,
        "Notification type: 'info', 'success', 'warning', or 'error'",
    ] = NotificationType.INFO,
) -> SentNotificationResult | SendNotificationFailure:
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

        # Channels must be explicit: an empty list would auto-inject every
        # user-enabled channel in the orchestrator, which over-notifies. Force
        # the agent to name channels (and to ask the user when they didn't).
        if not channels:
            return {
                "error": (
                    "channels is required: specify which channel(s) to notify "
                    f"({', '.join(ALL_AUTO_INJECTED_CHANNELS)}). If the user did not name a "
                    "channel, ask them which one(s) they want before sending."
                ),
                "success": False,
            }

        # Unknown channel names would otherwise be accepted and silently skipped
        # at delivery, so reject them here where the LLM can read the error and
        # self-correct.
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

        result: SentNotificationResult = {
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
        log.error(f"{LogTag.TOOL} Error sending notification", error_type=type(e).__name__)
        return {"error": str(e), "success": False}


@tool
@with_rate_limiting("notification_operations")
@with_doc(GET_NOTIFICATION_PREFERENCES)
async def get_notification_preferences(
    config: RunnableConfig,
) -> NotificationPreferencesResult:
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
    send_notification,
    get_notification_preferences,
]
