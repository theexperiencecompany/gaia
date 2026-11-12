"""Notify a user's devices that an approval is waiting.

Best-effort Expo push (backgrounded mobile app) with interactive approve/deny
actions; a failure here must never propagate into the gate. The SSE card is the
primary surface.
"""

from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.constants.log_tags import LogTag
from app.services.device_token_service import get_device_token_service
from shared.py.wide_events import log

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_TIMEOUT_SECONDS = 10.0
# Expo rejects a push request carrying more than 100 messages.
_EXPO_PUSH_BATCH_SIZE = 100


class _ExpoPushData(BaseModel):
    """What the app reads off a tapped approval notification."""

    type: Literal["hil_approval"] = "hil_approval"
    conversation_id: str
    approval_id: str


class _ExpoPushMessage(BaseModel):
    """One Expo push message, dumped by alias to Expo's camelCase."""

    to: str
    title: str
    body: str
    category_id: str = Field(serialization_alias="categoryId")
    data: _ExpoPushData


class _ExpoTicketDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: str | None = None


class _ExpoTicket(BaseModel):
    """Expo's verdict on one message; DeviceNotRegistered marks a dead token."""

    model_config = ConfigDict(extra="ignore")

    status: str
    details: _ExpoTicketDetails | None = None


class _ExpoPushReceipt(BaseModel):
    """Expo's reply: one ticket per message sent, in order."""

    model_config = ConfigDict(extra="ignore")

    data: list[_ExpoTicket] = Field(default_factory=list)


async def notify_approval_pending(
    user_id: str,
    conversation_id: str,
    approval_id: str,
    summary: str,
) -> None:
    """Wake the user's backgrounded devices. Never raises."""
    await _push_to_devices(user_id, conversation_id, approval_id, summary)


async def _push_to_devices(
    user_id: str, conversation_id: str, approval_id: str, summary: str
) -> None:
    """Best-effort Expo push to the user's registered devices."""
    try:
        tokens = await _active_device_tokens(user_id)
        if tokens:
            await _send_expo_push(
                tokens,
                conversation_id=conversation_id,
                approval_id=approval_id,
                summary=summary,
            )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} HIL notify: Expo push failed",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )


async def _active_device_tokens(user_id: str) -> list[str]:
    return await get_device_token_service().get_active_tokens(user_id)


async def _send_expo_push(
    tokens: list[str], *, conversation_id: str, approval_id: str, summary: str
) -> None:
    messages = [
        _ExpoPushMessage(
            to=token,
            title="GAIA needs your approval",
            body=summary,
            category_id="hil_approval",
            data=_ExpoPushData(conversation_id=conversation_id, approval_id=approval_id),
        )
        for token in tokens
    ]

    dead_tokens: list[str] = []
    async with httpx.AsyncClient(timeout=_EXPO_PUSH_TIMEOUT_SECONDS) as client:
        for start in range(0, len(messages), _EXPO_PUSH_BATCH_SIZE):
            batch = messages[start : start + _EXPO_PUSH_BATCH_SIZE]
            response = await client.post(
                _EXPO_PUSH_URL, json=[message.model_dump(by_alias=True) for message in batch]
            )
            dead_tokens.extend(_dead_tokens_from_receipts(batch, response))

    if dead_tokens:
        await _deactivate_device_tokens(dead_tokens)


def _dead_tokens_from_receipts(
    batch: list[_ExpoPushMessage], response: httpx.Response
) -> list[str]:
    """Return the tokens Expo reported as DeviceNotRegistered for this batch.

    The tickets align with the messages sent; an unreadable reply marks nothing dead.
    """
    try:
        receipt = _ExpoPushReceipt.model_validate(response.json())
    except ValueError:
        return []
    return [
        message.to
        for message, ticket in zip(batch, receipt.data, strict=False)
        if ticket.status == "error"
        and ticket.details is not None
        and ticket.details.error == "DeviceNotRegistered"
    ]


async def _deactivate_device_tokens(tokens: list[str]) -> None:
    """Mark dead tokens inactive so _active_device_tokens stops retrying them."""
    await get_device_token_service().deactivate_tokens(tokens)
