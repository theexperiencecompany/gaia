from typing import Any, TypedDict

from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.core.websocket_manager import websocket_manager
from app.models.notification.notification_models import (
    ActionStyle,
    ActionType,
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationType,
)
from app.utils.notification.channels.base import ChannelAdapter
from shared.py.wide_events import log


class InAppActionPayload(TypedDict):
    """One action button as it appears inside an ``InAppPayload``."""

    id: str
    type: ActionType
    label: str
    style: ActionStyle
    requires_confirmation: bool
    confirmation_message: str | None
    config: dict[str, Any] | None


class InAppPayload(TypedDict):
    """The ``notification.new`` WebSocket frame body."""

    id: str
    title: str
    body: str
    type: NotificationType
    priority: int
    actions: list[InAppActionPayload]
    metadata: dict[str, Any]
    created_at: str


class InAppChannelAdapter(ChannelAdapter[InAppPayload]):
    """In-app notification channel adapter.

    Pushes the notification payload to the connected client in real time via
    WebSocket using the ``notification.new`` event.  This is the *delivery*
    step for the in-app channel — the orchestrator subsequently fires a
    separate ``notification.delivered`` broadcast that carries the full record
    with channel-delivery statuses for all channels.  The two events serve
    different purposes and are not redundant:

    * ``notification.new``       — immediate display of the notification content
    * ``notification.delivered`` — status update after all channels have run
    """

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_INAPP

    def can_handle(self, notification: NotificationRequest) -> bool:  # noqa: ARG002 -- polymorphic interface; implementations keep the full signature
        """Return True — in-app delivery is always available for any request."""
        # In-app is always deliverable. The orchestrator decides targeting:
        # explicit requests look adapters up by channel_type, and auto-injection
        # always includes inapp — checking the request's channel list here would
        # silently skip the real-time push whenever channels are auto-injected
        # (the list is empty in that mode).
        return True

    async def transform(self, notification: NotificationRequest) -> InAppPayload:
        """Build the WebSocket payload for the in-app ``notification.new`` event."""
        return {
            "id": notification.id,
            "title": notification.content.title,
            "body": notification.content.body,
            "type": notification.type,
            "priority": notification.priority,
            "actions": [
                {
                    "id": action.id,
                    "type": action.type,
                    "label": action.label,
                    "style": action.style,
                    "requires_confirmation": action.requires_confirmation,
                    "confirmation_message": action.confirmation_message,
                    "config": action.config.model_dump() if action.config else None,
                }
                for action in (notification.content.actions or [])
            ],
            "metadata": notification.metadata,
            "created_at": notification.created_at.isoformat(),
        }

    async def deliver(self, content: InAppPayload, user_id: str) -> ChannelDeliveryStatus:
        """Push the in-app payload to the user's live WebSocket connection."""
        log.set(
            operation="inapp_deliver",
            user_id=user_id,
            notification_id=content["id"],
            channel_type=CHANNEL_TYPE_INAPP,
        )
        try:
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "notification.new",
                    "notification": content,
                },
            )
            log.info(f"{LogTag.NOTIFICATION} In-app notification delivered", user_id=user_id)
            return self._success()
        except Exception as e:
            log.error(
                f"{LogTag.NOTIFICATION} Failed to deliver in-app notification to user",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return self._error(str(e))
