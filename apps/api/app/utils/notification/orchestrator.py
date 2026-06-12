import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.constants.notifications import (
    ALL_AUTO_INJECTED_CHANNELS,
    CHANNEL_TYPE_INAPP,
    DEFAULT_CHANNEL_PREFERENCES,
)
from app.core.websocket_manager import websocket_manager
from app.models.notification.notification_models import (
    ActionResult,
    BulkActions,
    ChannelDeliveryStatus,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.utils.notification.actions import (
    ActionHandler,
    ApiCallActionHandler,
    ModalActionHandler,
    RedirectActionHandler,
)
from app.utils.notification.channel_preferences import fetch_channel_preferences
from app.utils.notification.channels import (
    ChannelAdapter,
    DiscordChannelAdapter,
    InAppChannelAdapter,
    SlackChannelAdapter,
    TelegramChannelAdapter,
    WhatsAppChannelAdapter,
)
from app.utils.notification.storage import (
    MongoDBNotificationStorage,
)
from shared.py.wide_events import log


class NotificationOrchestrator:
    """Core notification engine: creation, multi-channel delivery, actions,
    bulk operations, and status management."""

    def __init__(self, storage=None) -> None:
        self.storage = storage or MongoDBNotificationStorage()
        self.channel_adapters: dict[str, ChannelAdapter] = {}
        self.action_handlers: dict[str, ActionHandler] = {}

        # Register default components
        self._register_default_components()

    # INITIALIZATION & REGISTRATION METHODS
    def _register_default_components(self) -> None:
        """Register default adapters, handlers, and sources"""
        # Channel adapters
        self.register_channel_adapter(InAppChannelAdapter())
        self.register_channel_adapter(TelegramChannelAdapter())
        self.register_channel_adapter(DiscordChannelAdapter())
        self.register_channel_adapter(WhatsAppChannelAdapter())
        self.register_channel_adapter(SlackChannelAdapter())

        # Action handlers
        self.register_action_handler(ApiCallActionHandler())
        self.register_action_handler(RedirectActionHandler())
        self.register_action_handler(ModalActionHandler())

    def register_channel_adapter(self, adapter: ChannelAdapter) -> None:
        """Register a new channel adapter"""
        self.channel_adapters[adapter.channel_type] = adapter
        log.info(f"Registered channel adapter: {adapter.channel_type}")

    def register_action_handler(self, handler: ActionHandler) -> None:
        """Register a new action handler"""
        self.action_handlers[handler.action_type] = handler
        log.info(f"Registered action handler: {handler.action_type}")

    # NOTIFICATION CREATION & MANAGEMENT
    async def create_notification(self, request: NotificationRequest) -> NotificationRecord | None:
        """Create, store, and deliver a new notification."""
        channels_requested = [ch.channel_type for ch in request.channels]
        log.set(
            notification={
                "id": request.id,
                "user_id": request.user_id,
                "notification_type": request.type.value if request.type else None,
                "source": request.source,
                "title": request.content.title if request.content else None,
                "body_preview": (request.content.body or "")[:80] if request.content else None,
                "channels": channels_requested,
                "operation": "create_notification",
            }
        )
        log.info(f"Creating notification {request.id} for user {request.user_id}")

        # Create notification record
        notification_record = NotificationRecord(
            id=request.id,
            user_id=request.user_id,
            status=NotificationStatus.PENDING,
            created_at=request.created_at,
            original_request=request,
        )

        # Save to storage
        await self.storage.save_notification(notification_record)

        # Deliver the notification
        await self._deliver_notification(notification_record)

        return notification_record

    # NOTIFICATION DELIVERY SYSTEM
    async def _deliver_notification(self, notification: NotificationRecord) -> None:
        """Deliver a notification through all configured channels."""
        log.info(f"Delivering notification {notification.id}")

        delivery_tasks = []
        explicitly_requested = {ch.channel_type for ch in notification.original_request.channels}
        for channel_config in notification.original_request.channels:
            adapter = self.channel_adapters.get(channel_config.channel_type)
            if adapter and adapter.can_handle(notification.original_request):
                task = self._deliver_via_channel(notification, adapter)
                delivery_tasks.append(task)

        # Auto-inject channels only when no explicit channels were requested.
        # inapp is always available; telegram/discord respect user preferences.
        if not explicitly_requested:
            channel_prefs = await self._get_channel_prefs(notification.user_id)
            for platform in ALL_AUTO_INJECTED_CHANNELS:
                if platform != CHANNEL_TYPE_INAPP and not channel_prefs.get(platform, True):
                    log.info(
                        f"Skipping {platform} delivery for {notification.user_id}: disabled by preference"
                    )
                    continue
                adapter = self.channel_adapters.get(platform)
                if adapter and adapter.can_handle(notification.original_request):
                    delivery_tasks.append(self._deliver_via_channel(notification, adapter))

        # Execute all deliveries concurrently
        if delivery_tasks:
            delivery_results = await asyncio.gather(*delivery_tasks, return_exceptions=True)

            # Process delivery results
            channel_statuses = []
            for result in delivery_results:
                if isinstance(result, ChannelDeliveryStatus):
                    channel_statuses.append(result)
                elif isinstance(result, Exception):
                    log.error(f"Delivery failed: {result}")

            # Compute overall status: DELIVERED only if at least one channel
            # actually succeeded (i.e. not failed and not skipped).
            delivered_channels = [
                s
                for s in channel_statuses
                if s.status == NotificationStatus.DELIVERED and not s.skipped
            ]
            overall_status = (
                NotificationStatus.DELIVERED if delivered_channels else NotificationStatus.FAILED
            )
            log.set(
                notification={
                    "id": notification.id,
                    "user_id": notification.user_id,
                    "delivery_status": overall_status.value,
                    "channels_attempted": [s.channel_type for s in channel_statuses],
                    "channels_delivered": [s.channel_type for s in delivered_channels],
                    "operation": "deliver_notification",
                }
            )
            now = datetime.now(UTC)

            # Update the notification record with delivery results
            await self.storage.update_notification(
                notification.id,
                {
                    "channels": [status.model_dump() for status in channel_statuses],
                    "status": overall_status.value,
                    "delivered_at": now if overall_status == NotificationStatus.DELIVERED else None,
                },
            )

            # Update the local notification object for broadcasting
            notification.channels = channel_statuses
            notification.status = overall_status
            notification.delivered_at = (
                now if overall_status == NotificationStatus.DELIVERED else None
            )

            # Broadcast real-time update to user
            await websocket_manager.broadcast_to_user(
                notification.user_id,
                {
                    "type": "notification.delivered",
                    "notification": await self._serialize_notification(notification),
                },
            )

    async def _get_channel_prefs(self, user_id: str) -> dict:
        """Fetch user's notification channel preferences from DB.

        On a transient read failure, fall back to the SAME defaults a user with
        no stored preference gets (``DEFAULT_CHANNEL_PREFERENCES`` — all enabled),
        not "all disabled". An opt-out lives in a stored document; an unreadable
        document means the preference is *unknown*, and treating unknown as
        opted-out silently drops notifications the user asked for and makes
        delivery non-deterministic across transient DB blips. Erring toward
        delivery (one stray message during a rare outage) beats chronically
        dropping reminders.
        """
        try:
            return await fetch_channel_preferences(user_id)
        except Exception as e:
            log.warning(f"Failed to fetch channel prefs for {user_id}, using defaults: {e}")
            return dict(DEFAULT_CHANNEL_PREFERENCES)

    async def _deliver_via_channel(
        self, notification: NotificationRecord, adapter: ChannelAdapter
    ) -> ChannelDeliveryStatus:
        """Deliver a notification via a specific channel adapter."""
        try:
            content = await adapter.transform(notification.original_request)
            return await adapter.deliver(content, notification.user_id)
        except Exception as e:
            log.error(f"Channel delivery failed: {e}")
            return ChannelDeliveryStatus(
                channel_type=adapter.channel_type,
                status=NotificationStatus.PENDING,
                error_message=str(e),
            )

    # ACTION EXECUTION SYSTEM
    async def execute_action(
        self,
        notification_id: str,
        action_id: str,
        user_id: str,
        request: Request | None,
    ) -> ActionResult:
        """Execute a notification action."""
        log.set(
            action_id=action_id,
            notification_id=notification_id,
            user_id=user_id,
            operation="execute_action",
        )
        log.info(f"Executing action {action_id} for notification {notification_id}")

        # Get notification
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return ActionResult(
                success=False, message="Notification not found", error_code="NOT_FOUND"
            )

        # Find action
        action = notification.get_action_by_id(action_id)
        if not action:
            return ActionResult(
                success=False, message="Action not found", error_code="ACTION_NOT_FOUND"
            )

        # Check if action can be executed
        if not action.is_executable():
            return ActionResult(
                success=False,
                message=(
                    "Action has already been executed" if action.executed else "Action is disabled"
                ),
                error_code=("ACTION_ALREADY_EXECUTED" if action.executed else "ACTION_DISABLED"),
            )

        # Get handler
        handler = self.action_handlers.get(action.type.value)
        if not handler or not handler.can_handle(action):
            return ActionResult(
                success=False,
                message=f"No handler available for action type: {action.type}",
                error_code="NO_HANDLER",
            )

        # Execute the action
        result = await handler.execute(action, notification, user_id, request=request)

        # If action was successful, mark it as executed
        if result.success:
            notification.mark_action_as_executed(action_id)

            # Update the notification in storage with the executed action
            await self.storage.update_notification(
                notification_id,
                {
                    "original_request": notification.original_request.model_dump(),
                    "updated_at": notification.updated_at,
                },
            )

        # Update notification if needed (additional updates from handler)
        if result.update_notification:
            await self.storage.update_notification(notification_id, result.update_notification)
            log.info(f"Broadcasting notification {notification.id} to user {notification.user_id}")
            # Broadcast update to user via websocket
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "notification.updated",
                    "notification_id": notification_id,
                    "updates": result.update_notification,
                },
            )

        return result

    # NOTIFICATION STATUS MANAGEMENT
    async def mark_as_read(self, notification_id: str, user_id: str) -> NotificationRecord | None:
        """Mark a notification as read."""
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return None

        log.info(f"Marking notification {notification_id} as read for user {user_id}")

        await self.storage.update_notification(
            notification_id,
            {
                "status": NotificationStatus.READ.value,
                "read_at": datetime.now(UTC),
            },
        )

        # Get the updated notification
        updated_notification = await self.storage.get_notification(notification_id, user_id)

        # Broadcast update via websocket
        await websocket_manager.broadcast_to_user(
            user_id, {"type": "notification.read", "notification_id": notification_id}
        )

        return updated_notification

    async def archive_notification(self, notification_id: str, user_id: str) -> bool:
        """Archive a notification."""
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return False

        log.info(f"Archiving notification {notification_id} for user {user_id}")

        await self.storage.update_notification(
            notification_id,
            {
                "status": NotificationStatus.ARCHIVED.value,
                "archived_at": datetime.now(UTC),
            },
        )

        return True

    # NOTIFICATION RETRIEVAL & QUERIES
    async def get_user_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
        channel_type: str | None = None,
        notification_type: NotificationType | None = None,
        source: NotificationSourceEnum | None = None,
    ) -> list[dict[str, Any]]:
        """Get a user's notifications with optional filtering and pagination."""
        notifications = await self.storage.get_user_notifications(
            user_id, status, limit, offset, channel_type, notification_type, source
        )
        return [await self._serialize_notification(n) for n in notifications]

    async def get_notification(self, notification_id: str, user_id: str) -> dict[str, Any] | None:
        """Get a specific notification by ID for a user."""
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return None
        return await self._serialize_notification(notification)

    # BULK OPERATIONS
    async def bulk_actions(
        self, notification_ids: list[str], user_id: str, action: BulkActions
    ) -> dict[str, bool]:
        """Perform a bulk action across notifications, returning per-ID success."""
        results = {}

        for notification_id in notification_ids:
            try:
                if action == BulkActions.MARK_READ:
                    result = await self.mark_as_read(notification_id, user_id)
                    success = result is not None
                elif action == BulkActions.ARCHIVE:
                    success = await self.archive_notification(notification_id, user_id)
                else:
                    success = False

                results[notification_id] = success
            except Exception as e:
                log.error(f"Bulk action failed for {notification_id}: {e}")
                results[notification_id] = False

        return results

    # UTILITY & SERIALIZATION METHODS
    async def _serialize_notification(self, notification: NotificationRecord) -> dict[str, Any]:
        """Serialize a notification record for API responses."""
        return {
            "id": notification.id,
            "user_id": notification.user_id,
            "status": notification.status.value,
            "created_at": notification.created_at.isoformat(),
            "delivered_at": (
                notification.delivered_at.isoformat() if notification.delivered_at else None
            ),
            "read_at": (notification.read_at.isoformat() if notification.read_at else None),
            "content": {
                "title": notification.original_request.content.title,
                "body": notification.original_request.content.body,
                "actions": [
                    {
                        "id": action.id,
                        "type": action.type.value,
                        "label": action.label,
                        "style": action.style.value,
                        "requires_confirmation": action.requires_confirmation,
                        "confirmation_message": action.confirmation_message,
                        "config": action.config.model_dump() if action.config else None,
                        "executed": action.executed,
                        "executed_at": (
                            action.executed_at.isoformat() if action.executed_at else None
                        ),
                        "disabled": action.disabled,
                    }
                    for action in (notification.original_request.content.actions or [])
                ],
            },
            "source": notification.original_request.source,
            "type": notification.original_request.type.value,
            "metadata": notification.original_request.metadata,
            "channels": [
                {
                    "channel_type": ch.channel_type,
                    "status": ch.status.value,
                    "skipped": ch.skipped,
                    "delivered_at": (ch.delivered_at.isoformat() if ch.delivered_at else None),
                    "error_message": ch.error_message,
                }
                for ch in notification.channels
            ],
        }
