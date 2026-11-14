"""Expo push: an approval request wakes the user's phones, with approve and deny buttons."""

import httpx
from pydantic import BaseModel, Field

from app.constants.notifications import APPROVAL_PUSH_CATEGORY, CHANNEL_TYPE_PUSH
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.device_token_service import get_device_token_service
from app.utils.notification.channels.base import ChannelAdapter

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_TIMEOUT_SECONDS = 10.0
# Expo rejects a push request carrying more than 100 messages.
_EXPO_PUSH_BATCH_SIZE = 100
_EXPO_UNREGISTERED_DEVICE_ERROR = "DeviceNotRegistered"


class _ExpoTicketDetails(BaseModel):
    error: str | None = None


class _ExpoTicket(BaseModel):
    status: str
    details: _ExpoTicketDetails | None = None


class _ExpoPushReceipts(BaseModel):
    """Expo's reply to a push batch: one ticket per message, in the order sent."""

    data: list[_ExpoTicket] = Field(default_factory=list)


class PushMessage(BaseModel):
    """One Expo message body, before it is addressed to a device token."""

    title: str
    body: str
    category_id: str
    data: dict[str, object]


class PushChannelAdapter(ChannelAdapter[PushMessage]):
    """Sends the notification to every active Expo token the user registered."""

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_PUSH

    def can_handle(self, notification: NotificationRequest) -> bool:
        """Return True for an approval request only: the phone is woken for nothing else."""
        return notification.source is NotificationSourceEnum.APPROVAL

    async def transform(self, notification: NotificationRequest) -> PushMessage:
        """Carry the notification id and its metadata, so a tap opens what it is about."""
        return PushMessage(
            title=notification.content.title,
            body=notification.content.body,
            category_id=APPROVAL_PUSH_CATEGORY,
            data={"notification_id": notification.id, **notification.metadata},
        )

    async def deliver(self, content: PushMessage, user_id: str) -> ChannelDeliveryStatus:
        """Post the message to Expo in batches and retire the tokens Expo says are gone."""
        tokens = await get_device_token_service().get_active_tokens(user_id)
        if not tokens:
            return self._skipped("push: no registered device")
        messages = [
            {
                "to": token,
                "title": content.title,
                "body": content.body,
                "categoryId": content.category_id,
                "data": content.data,
            }
            for token in tokens
        ]
        dead_tokens: list[str] = []
        async with httpx.AsyncClient(timeout=_EXPO_PUSH_TIMEOUT_SECONDS) as client:
            for start in range(0, len(messages), _EXPO_PUSH_BATCH_SIZE):
                response = await client.post(
                    _EXPO_PUSH_URL, json=messages[start : start + _EXPO_PUSH_BATCH_SIZE]
                )
                response.raise_for_status()
                dead_tokens.extend(
                    _dead_tokens_from_receipts(
                        tokens[start : start + _EXPO_PUSH_BATCH_SIZE], response
                    )
                )
        if dead_tokens:
            await get_device_token_service().deactivate_tokens(dead_tokens)
        return self._success()


def _dead_tokens_from_receipts(tokens: list[str], response: httpx.Response) -> list[str]:
    """Return the tokens of this batch whose ticket Expo marked DeviceNotRegistered (uninstalled or expired)."""
    try:
        receipts = _ExpoPushReceipts.model_validate(response.json())
    except ValueError:
        return []
    pairs = zip(tokens, receipts.data, strict=False)  # pragma: no mutate — the default; B905
    return [
        token
        for token, ticket in pairs
        if ticket.status == "error"
        and ticket.details is not None
        and ticket.details.error == _EXPO_UNREGISTERED_DEVICE_ERROR
    ]
