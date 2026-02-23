import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config.loggers import app_logger as logger
from app.constants.notifications import (
    DEFAULT_CHANNEL_PREFERENCES,
    EXTERNAL_NOTIFICATION_CHANNELS,
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
from app.utils.notification.channels import (
    ChannelAdapter,
    DiscordChannelAdapter,
    InAppChannelAdapter,
    TelegramChannelAdapter,
)
from app.db.mongodb.collections import users_collection
from app.utils.notification.storage import (
    MongoDBNotificationStorage,
)
from bson import ObjectId
from fastapi import Request


class NotificationOrchestrator:
    """
    Core notification orchestration engine.

    This class manages the complete lifecycle of notifications including:
    - Creation and validation
    - Delivery through multiple channels
    - Action execution
    - Bulk operations
    - Status management
    """

    def __init__(self, storage=None) -> None:
        self.storage = storage or MongoDBNotificationStorage()
        self.channel_adapters: Dict[str, ChannelAdapter] = {}
        self.action_handlers: Dict[str, ActionHandler] = {}

        # Register default components
        self._register_default_components()

    # INITIALIZATION & REGISTRATION METHODS
    def _register_default_components(self) -> None:
        """Register default adapters, handlers, and sources"""
        # Channel adapters
        self.register_channel_adapter(InAppChannelAdapter())
        self.register_channel_adapter(TelegramChannelAdapter())
        self.register_channel_adapter(DiscordChannelAdapter())

        # Action handlers
        self.register_action_handler(ApiCallActionHandler())
        self.register_action_handler(RedirectActionHandler())
        self.register_action_handler(ModalActionHandler())

    def register_channel_adapter(self, adapter: ChannelAdapter) -> None:
        """Register a new channel adapter"""
        self.channel_adapters[adapter.channel_type] = adapter
        logger.info(f"Registered channel adapter: {adapter.channel_type}")

    def register_action_handler(self, handler: ActionHandler) -> None:
        """Register a new action handler"""
        self.action_handlers[handler.action_type] = handler
        logger.info(f"Registered action handler: {handler.action_type}")

    # NOTIFICATION CREATION & MANAGEMENT
    async def create_notification(
        self, request: NotificationRequest
    ) -> NotificationRecord | None:
        """
        Create and process a new notification.

        Args:
            request: The notification request containing all notification data

        Returns:
            NotificationRecord if created successfully, None if duplicate
        """
        logger.info(f"Creating notification {request.id} for user {request.user_id}")

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
        """
        Deliver notification through all configured channels.

        Args:
            notification: The notification record to deliver
        """
        logger.info(f"Delivering notification {notification.id}")

        delivery_tasks = []
        explicitly_requested = {
            ch.channel_type for ch in notification.original_request.channels
        }
        for channel_config in notification.original_request.channels:
            adapter = self.channel_adapters.get(channel_config.channel_type)
            if adapter and adapter.can_handle(notification.original_request):
                task = self._deliver_via_channel(notification, adapter)
                delivery_tasks.append(task)

        # Auto-inject Telegram and Discord if not already in the channel list
        channel_prefs = await self._get_channel_prefs(notification.user_id)
        for platform in EXTERNAL_NOTIFICATION_CHANNELS:
            if platform in explicitly_requested:
                continue
            if not channel_prefs.get(platform, True):
                logger.info(
                    f"Skipping {platform} delivery for {notification.user_id}: disabled by preference"
                )
                continue
            adapter = self.channel_adapters.get(platform)
            if adapter and adapter.can_handle(notification.original_request):
                delivery_tasks.append(self._deliver_via_channel(notification, adapter))

        # Execute all deliveries concurrently
        if delivery_tasks:
            delivery_results = await asyncio.gather(
                *delivery_tasks, return_exceptions=True
            )

            # Process delivery results
            channel_statuses = []
            for result in delivery_results:
                if isinstance(result, ChannelDeliveryStatus):
                    channel_statuses.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Delivery failed: {result}")

            # Compute overall status: DELIVERED only if at least one channel
            # actually succeeded (i.e. not failed and not skipped).
            delivered_channels = [
                s
                for s in channel_statuses
                if s.status == NotificationStatus.DELIVERED and not s.skipped
            ]
            overall_status = (
                NotificationStatus.DELIVERED
                if delivered_channels
                else NotificationStatus.FAILED
            )
            now = datetime.now(timezone.utc)

            # Update the notification record with delivery results
            await self.storage.update_notification(
                notification.id,
                {
                    "channels": [status.model_dump() for status in channel_statuses],
                    "status": overall_status.value,
                    "delivered_at": now
                    if overall_status == NotificationStatus.DELIVERED
                    else None,
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
        """Fetch user's notification channel preferences from DB."""
        try:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            prefs = (user or {}).get("notification_channel_prefs", {})
            return {
                "telegram": prefs.get("telegram", True),
                "discord": prefs.get("discord", True),
            }
        except Exception as e:
            # Default to all DISABLED on error — better to skip delivery than
            # to spam users who have opted out when the DB is unavailable.
            logger.warning(f"Failed to fetch channel prefs for {user_id}: {e}")
            return {k: False for k in DEFAULT_CHANNEL_PREFERENCES}

    async def _deliver_via_channel(
        self, notification: NotificationRecord, adapter: ChannelAdapter
    ) -> ChannelDeliveryStatus:
        """
        Deliver notification via a specific channel.

        Args:
            notification: The notification to deliver
            adapter: The channel adapter to use for delivery

        Returns:
            ChannelDeliveryStatus indicating success or failure
        """
        try:
            content = await adapter.transform(notification.original_request)
            return await adapter.deliver(content, notification.user_id)
        except Exception as e:
            logger.error(f"Channel delivery failed: {e}")
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
        request: Optional[Request],
    ) -> ActionResult:
        """
        Execute a notification action.

        Args:
            notification_id: ID of the notification containing the action
            action_id: ID of the specific action to execute
            user_id: ID of the user executing the action
            request: Optional FastAPI request object for context

        Returns:
            ActionResult containing execution status and results
        """
        logger.info(f"Executing action {action_id} for notification {notification_id}")

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
                    "Action has already been executed"
                    if action.executed
                    else "Action is disabled"
                ),
                error_code=(
                    "ACTION_ALREADY_EXECUTED" if action.executed else "ACTION_DISABLED"
                ),
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
            await self.storage.update_notification(
                notification_id, result.update_notification
            )
            logger.info(
                f"Broadcasting notification {notification.id} to user {notification.user_id}"
            )
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
    async def mark_as_read(
        self, notification_id: str, user_id: str
    ) -> NotificationRecord | None:
        """
        Mark notification as read.

        Args:
            notification_id: ID of the notification to mark as read
            user_id: ID of the user marking the notification

        Returns:
            Updated notification record if successful, None otherwise
        """
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return None

        logger.info(
            f"Marking notification {notification_id} as read for user {user_id}"
        )

        await self.storage.update_notification(
            notification_id,
            {
                "status": NotificationStatus.READ.value,
                "read_at": datetime.now(timezone.utc),
            },
        )

        # Get the updated notification
        updated_notification = await self.storage.get_notification(
            notification_id, user_id
        )

        # Broadcast update via websocket
        await websocket_manager.broadcast_to_user(
            user_id, {"type": "notification.read", "notification_id": notification_id}
        )

        return updated_notification

    async def archive_notification(self, notification_id: str, user_id: str) -> bool:
        """
        Archive a notification.

        Args:
            notification_id: ID of the notification to archive
            user_id: ID of the user archiving the notification

        Returns:
            True if successfully archived, False otherwise
        """
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return False

        logger.info(f"Archiving notification {notification_id} for user {user_id}")

        await self.storage.update_notification(
            notification_id,
            {
                "status": NotificationStatus.ARCHIVED.value,
                "archived_at": datetime.now(timezone.utc),
            },
        )

        return True

    # NOTIFICATION RETRIEVAL & QUERIES
    async def get_user_notifications(
        self,
        user_id: str,
        status: Optional[NotificationStatus] = None,
        limit: int = 50,
        offset: int = 0,
        channel_type: Optional[str] = None,
        notification_type: Optional[NotificationType] = None,
        source: Optional[NotificationSourceEnum] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get notifications for a user with optional filtering.

        Args:
            user_id: ID of the user whose notifications to retrieve
            status: Optional status filter
            limit: Maximum number of notifications to return
            offset: Number of notifications to skip (for pagination)
            channel_type: Optional channel type filter
            notification_type: Optional notification type filter
            source: Optional source filter

        Returns:
            List of serialized notifications
        """
        notifications = await self.storage.get_user_notifications(
            user_id, status, limit, offset, channel_type, notification_type, source
        )
        return [await self._serialize_notification(n) for n in notifications]

    async def get_notification(
        self, notification_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific notification by ID for a user.

        Args:
            notification_id: ID of the notification to retrieve
            user_id: ID of the user requesting the notification

        Returns:
            Serialized notification if found, None otherwise
        """
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return None
        return await self._serialize_notification(notification)

    # BULK OPERATIONS
    async def bulk_actions(
        self, notification_ids: List[str], user_id: str, action: BulkActions
    ) -> Dict[str, bool]:
        """
        Perform bulk actions on multiple notifications.

        Args:
            notification_ids: List of notification IDs to operate on
            user_id: ID of the user performing the bulk action
            action: The type of bulk action to perform

        Returns:
            Dictionary mapping notification IDs to success/failure status
        """
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
                logger.error(f"Bulk action failed for {notification_id}: {e}")
                results[notification_id] = False

        return results

    # UTILITY & SERIALIZATION METHODS
    async def _serialize_notification(
        self, notification: NotificationRecord
    ) -> Dict[str, Any]:
        """
        Serialize notification for API response.

        Args:
            notification: The notification record to serialize

        Returns:
            Dictionary representation suitable for API responses
        """
        return {
            "id": notification.id,
            "user_id": notification.user_id,
            "status": notification.status.value,
            "created_at": notification.created_at.isoformat(),
            "delivered_at": (
                notification.delivered_at.isoformat()
                if notification.delivered_at
                else None
            ),
            "read_at": (
                notification.read_at.isoformat() if notification.read_at else None
            ),
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
                            action.executed_at.isoformat()
                            if action.executed_at
                            else None
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
                    "delivered_at": (
                        ch.delivered_at.isoformat() if ch.delivered_at else None
                    ),
                    "error_message": ch.error_message,
                }
                for ch in notification.channels
            ],
        }
