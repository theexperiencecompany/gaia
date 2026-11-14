import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.constants.log_tags import LogTag
from app.constants.notifications import (
    CHANNEL_TYPE_CONVERSATION,
    CHANNEL_TYPE_INAPP,
    CHANNEL_TYPE_PUSH,
    EXTERNAL_NOTIFICATION_CHANNELS,
)
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.notifications import notification_repository
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource
from app.models.notification.notification_models import (
    ActionResult,
    BulkActions,
    ChannelDeliveryStatus,
    NotificationActionView,
    NotificationChannelView,
    NotificationContentView,
    NotificationListFilters,
    NotificationRecord,
    NotificationRequest,
    NotificationStatus,
    NotificationView,
)
from app.services.delivery.chat_channel import (
    ChatChannel,
    InApp,
    ProactiveTarget,
    is_active_place,
    resolve_proactive_target,
)
from app.utils.notification.actions import (
    ActionHandler,
    ApiCallActionHandler,
    ModalActionHandler,
    RedirectActionHandler,
)
from app.utils.notification.channels import (
    ChannelAdapter,
    ConversationChannelAdapter,
    DiscordChannelAdapter,
    ImessageChannelAdapter,
    PushChannelAdapter,
    SlackChannelAdapter,
    TContent,
    TelegramChannelAdapter,
    WhatsAppChannelAdapter,
)
from app.utils.notification.storage import (
    MongoDBNotificationStorage,
)
from shared.py.wide_events import NotificationContext, log


class NotificationNotFoundError(LookupError):
    """The notification just stored could not be read back."""


@dataclass(frozen=True, slots=True)
class Notified:
    """A notification as stored after sending, and where routing found the user (None when it named its channels)."""

    record: NotificationRecord
    target: ProactiveTarget | None

    @property
    def chat_app(self) -> ConversationSource | None:
        """The chat app that delivered it, on this call or an earlier attempt; None when none did."""
        for channel in self.record.channels:
            if (
                channel.channel_type in EXTERNAL_NOTIFICATION_CHANNELS
                and channel.status == NotificationStatus.DELIVERED
                and not channel.skipped
            ):
                return ConversationSource(channel.channel_type)
        return None


def _lands_in_conversation(target: ProactiveTarget, source: ConversationSource | None) -> bool:
    """Whether a fact goes back into its conversation: yes, unless the user is active somewhere else."""
    if not is_active_place(target):
        return True
    if isinstance(target, ChatChannel):
        return source is target.source
    # Web chats are stored without a source; anything not a chat app's conversation is an app chat.
    return source not in BOT_CONVERSATION_SOURCES


class NotificationOrchestrator:
    """Core notification engine: creation, multi-channel delivery, actions, bulk operations, and status management."""

    def __init__(self, storage: MongoDBNotificationStorage | None = None) -> None:
        self.storage = storage or MongoDBNotificationStorage()
        # Erased element type: the registry is heterogeneous by design (each
        # adapter has its own payload shape). ``_deliver_via_channel`` rebinds
        # the real one per adapter, so transform → deliver stays checked.
        self.channel_adapters: dict[str, ChannelAdapter[Any]] = {}
        self.action_handlers: dict[str, ActionHandler] = {}

        self._register_default_components()

    # INITIALIZATION & REGISTRATION METHODS
    def _register_default_components(self) -> None:
        """Register default adapters, handlers, and sources."""
        self.register_channel_adapter(ConversationChannelAdapter())
        self.register_channel_adapter(PushChannelAdapter())
        self.register_channel_adapter(TelegramChannelAdapter())
        self.register_channel_adapter(DiscordChannelAdapter())
        self.register_channel_adapter(WhatsAppChannelAdapter())
        self.register_channel_adapter(SlackChannelAdapter())
        self.register_channel_adapter(ImessageChannelAdapter())

        self.register_action_handler(ApiCallActionHandler())
        self.register_action_handler(RedirectActionHandler())
        self.register_action_handler(ModalActionHandler())

    def register_channel_adapter(self, adapter: ChannelAdapter[TContent]) -> None:
        """Accept any adapter's own payload type; the registry holds it erased."""
        self.channel_adapters[adapter.channel_type] = adapter
        log.info(
            f"{LogTag.NOTIFICATION} Registered channel adapter", channel_type=adapter.channel_type
        )

    def register_action_handler(self, handler: ActionHandler) -> None:
        self.action_handlers[handler.action_type] = handler
        log.info(
            f"{LogTag.NOTIFICATION} Registered action handler", action_type=handler.action_type
        )

    # NOTIFICATION CREATION & DELIVERY
    async def notify(self, request: NotificationRequest) -> Notified:
        """Store the notification once and send it once per channel; a retry with the same id sends nothing new.

        The record is inserted only if absent and each channel is claimed on it
        before its send, so a retried producer resumes only the channels never started.
        """
        log.set(notification=NotificationContext(operation="send", notification_id=request.id))
        await notification_repository.insert_if_absent(
            NotificationRecord(
                id=request.id,
                user_id=request.user_id,
                status=NotificationStatus.PENDING,
                created_at=request.created_at,
                original_request=request,
            )
        )
        channels, target = await self._route(request)
        claimed = [
            channel
            for channel in channels
            if await notification_repository.claim_channel(request.id, channel)
        ]
        outcomes = await asyncio.gather(
            *(
                self._deliver_via_channel(request, self.channel_adapters[channel])
                for channel in claimed
                if channel != CHANNEL_TYPE_INAPP
            )
        )
        for outcome in outcomes:
            await notification_repository.record_channel(request.id, outcome)
        announce = CHANNEL_TYPE_INAPP in claimed
        if announce:
            # The stored record is the in-app delivery; the one event below announces it.
            await notification_repository.record_channel(
                request.id,
                ChannelDeliveryStatus(
                    channel_type=CHANNEL_TYPE_INAPP,
                    status=NotificationStatus.DELIVERED,
                    delivered_at=datetime.now(UTC),
                ),
            )
        record = await self._settle(request)
        if announce:
            await websocket_manager.broadcast_to_user(
                request.user_id,
                {
                    "type": "notification.delivered",
                    # JSON mode: enums as their values, matching what REST clients receive.
                    "notification": self._serialize_notification(record).model_dump(mode="json"),
                },
            )
        return Notified(record=record, target=target)

    async def _settle(self, request: NotificationRequest) -> NotificationRecord:
        """Set the overall status from every channel's outcome so far and return the stored record."""
        record = await self.storage.get_notification(request.id, request.user_id)
        if record is None:
            raise NotificationNotFoundError(request.id)
        delivered = [
            c for c in record.channels if c.status == NotificationStatus.DELIVERED and not c.skipped
        ]
        status = NotificationStatus.DELIVERED if delivered else NotificationStatus.FAILED
        delivered_at = min((c.delivered_at for c in delivered if c.delivered_at), default=None)
        log.set_ns(
            "notification",
            operation="dispatch",
            notification_id=request.id,
            result_count=len(delivered),
            success=status == NotificationStatus.DELIVERED,
        )
        await self.storage.update_notification(
            request.id, {"status": status.value, "delivered_at": delivered_at}
        )
        return record.model_copy(update={"status": status, "delivered_at": delivered_at})

    async def _route(
        self, request: NotificationRequest
    ) -> tuple[list[str], ProactiveTarget | None]:
        """Choose the channels once: the ones the request names, else by where the user is reached.

        By default: the inbox; the conversation the fact belongs to, unless the
        user is active somewhere else; the chat app the user is reached on, unless
        that conversation already is its chat; and push to the user's phones.
        """
        if request.channels:
            named = [
                c.channel_type
                for c in request.channels
                if c.enabled and self._can_send(c.channel_type, request)
            ]
            return list(dict.fromkeys(named)), None
        target = await self._proactive_target(request.user_id)
        channels = [CHANNEL_TYPE_INAPP]
        chat_app = target.source if isinstance(target, ChatChannel) else None
        if request.conversation_id is not None:
            source = await conversation_repository.get_source(
                request.conversation_id, user_id=request.user_id
            )
            if _lands_in_conversation(target, source):
                channels.append(CHANNEL_TYPE_CONVERSATION)
                if source is chat_app:
                    chat_app = None
        if chat_app is not None:
            channels.append(chat_app.value)
        channels.append(CHANNEL_TYPE_PUSH)
        return channels, target

    def _can_send(self, channel_type: str, request: NotificationRequest) -> bool:
        """Whether a channel the request names exists and takes this request; the inbox always does."""
        if channel_type == CHANNEL_TYPE_INAPP:
            return True
        adapter = self.channel_adapters.get(channel_type)
        return adapter is not None and adapter.can_handle(request)

    async def _proactive_target(self, user_id: str) -> ProactiveTarget:
        """Return where the user is reached; the inbox alone when that cannot be read.

        A stray chat-app message is not worth guessing a platform the user may
        have switched off, so a failed lookup degrades to the inbox, on the wide event.
        """
        try:
            return await resolve_proactive_target(user_id)
        except Exception as e:
            log.warning(
                f"{LogTag.NOTIFICATION} Chat channel lookup failed, delivering in-app only",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return InApp(reason="no_chat_app")

    async def _deliver_via_channel(
        self, request: NotificationRequest, adapter: ChannelAdapter[TContent]
    ) -> ChannelDeliveryStatus:
        """Send on one adapter; a raised error is that channel's failed outcome, never the others'.

        TContent binds to this adapter's own payload type, so the value
        flowing from transform into deliver is checked per adapter even
        though the registry itself is erased.
        """
        try:
            content = await adapter.transform(request)
            return await adapter.deliver(content, request.user_id)
        except Exception as e:
            log.error(
                f"{LogTag.NOTIFICATION} Channel delivery failed",
                channel_type=adapter.channel_type,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ChannelDeliveryStatus(
                channel_type=adapter.channel_type,
                status=NotificationStatus.FAILED,
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
            user={"id": user_id},
            operation="execute_action",
            notification=NotificationContext(operation="dispatch", notification_id=notification_id),
        )
        log.info(
            f"{LogTag.NOTIFICATION} Executing action for notification",
            action_id=action_id,
            notification_id=notification_id,
        )

        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return ActionResult(
                success=False, message="Notification not found", error_code="NOT_FOUND"
            )

        action = notification.get_action_by_id(action_id)
        if not action:
            return ActionResult(
                success=False, message="Action not found", error_code="ACTION_NOT_FOUND"
            )

        if not action.is_executable():
            return ActionResult(
                success=False,
                message=(
                    "Action has already been executed" if action.executed else "Action is disabled"
                ),
                error_code=("ACTION_ALREADY_EXECUTED" if action.executed else "ACTION_DISABLED"),
            )

        handler = self.action_handlers.get(action.type.value)
        if not handler or not handler.can_handle(action):
            return ActionResult(
                success=False,
                message=f"No handler available for action type: {action.type}",
                error_code="NO_HANDLER",
            )

        result = await handler.execute(action, notification, user_id, request=request)

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
            log.info(
                f"{LogTag.NOTIFICATION} Broadcasting notification to user",
                id=notification.id,
                user_id=notification.user_id,
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
    async def mark_as_read(self, notification_id: str, user_id: str) -> NotificationRecord | None:
        """Mark a notification as read."""
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return None

        log.info(
            f"{LogTag.NOTIFICATION} Marking notification as read for user",
            notification_id=notification_id,
            user_id=user_id,
        )

        await self.storage.update_notification(
            notification_id,
            {
                "status": NotificationStatus.READ.value,
                "read_at": datetime.now(UTC),
            },
        )

        updated_notification = await self.storage.get_notification(notification_id, user_id)

        await websocket_manager.broadcast_to_user(
            user_id, {"type": "notification.read", "notification_id": notification_id}
        )

        return updated_notification

    async def mark_all_read(self, user_id: str, channel_type: str | None = None) -> int:
        """Mark every delivered notification for a user as read in one write.

        Unlike bulk_actions, this does not require the caller to already know
        every notification ID — it operates server-side on all matching
        notifications, including any not yet loaded into a client's paginated view.
        """
        log.info(
            f"{LogTag.NOTIFICATION} Marking all notifications as read for user",
            user_id=user_id,
            channel_type=channel_type,
        )
        updated_count = await self.storage.mark_all_read(user_id, channel_type=channel_type)

        await websocket_manager.broadcast_to_user(
            user_id, {"type": "notification.all_read", "channel_type": channel_type}
        )

        return updated_count

    async def archive_notification(self, notification_id: str, user_id: str) -> bool:
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return False

        log.info(
            f"{LogTag.NOTIFICATION} Archiving notification for user",
            notification_id=notification_id,
            user_id=user_id,
        )

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
        *,
        filters: NotificationListFilters | None = None,
    ) -> list[NotificationView]:
        """Get a user's notifications with optional filtering and pagination."""
        notifications = await self.storage.get_user_notifications(user_id, filters=filters)
        return [self._serialize_notification(n) for n in notifications]

    async def get_notification(self, notification_id: str, user_id: str) -> NotificationView | None:
        """Get a specific notification by ID for a user."""
        notification = await self.storage.get_notification(notification_id, user_id)
        if not notification:
            return None
        return self._serialize_notification(notification)

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

                results[notification_id] = success
            except Exception as e:
                log.error(
                    f"{LogTag.NOTIFICATION} Bulk action failed for",
                    notification_id=notification_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
                results[notification_id] = False

        return results

    # UTILITY & SERIALIZATION METHODS
    def _serialize_notification(self, notification: NotificationRecord) -> NotificationView:
        """Flatten a stored record into the view API/tool consumers read.

        Timestamps are emitted as ISO strings because NotificationView publishes
        them as str — that is the established wire contract.
        """
        request = notification.original_request
        return NotificationView(
            id=notification.id,
            user_id=notification.user_id,
            status=notification.status,
            created_at=notification.created_at.isoformat(),
            delivered_at=(
                notification.delivered_at.isoformat() if notification.delivered_at else None
            ),
            read_at=(notification.read_at.isoformat() if notification.read_at else None),
            content=NotificationContentView(
                title=request.content.title,
                body=request.content.body,
                actions=[
                    NotificationActionView(
                        id=action.id,
                        type=action.type,
                        label=action.label,
                        style=action.style,
                        requires_confirmation=action.requires_confirmation,
                        confirmation_message=action.confirmation_message,
                        config=action.config,
                        executed=action.executed,
                        executed_at=(
                            action.executed_at.isoformat() if action.executed_at else None
                        ),
                        disabled=action.disabled,
                    )
                    for action in (request.content.actions or [])
                ],
            ),
            source=request.source,
            type=request.type,
            metadata=request.metadata,
            channels=[
                NotificationChannelView(
                    channel_type=ch.channel_type,
                    status=ch.status,
                    skipped=ch.skipped,
                    delivered_at=(ch.delivered_at.isoformat() if ch.delivered_at else None),
                    error_message=ch.error_message,
                )
                for ch in notification.channels
            ],
        )
