"""Notify a user's clients that an approval is waiting.

Two independent best-effort channels — a failure here must never propagate into
the gate (the SSE card is the primary surface; these only wake a client that
isn't actively watching the stream):

- in-app WebSocket broadcast (open web/mobile clients);
- Expo push (backgrounded mobile app), with interactive approve/deny actions.
"""

import asyncio
from typing import TypedDict

import httpx
from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.device_tokens import device_token_repository
from shared.py.wide_events import log

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_TIMEOUT_SECONDS = 10.0
# Expo rejects a push request carrying more than 100 messages.
_EXPO_PUSH_BATCH_SIZE = 100
_EXPO_DEVICE_NOT_REGISTERED = "DeviceNotRegistered"


class _ApprovalPushData(TypedDict):
    type: str
    conversation_id: str
    approval_id: str


class _ExpoPushMessage(TypedDict):
    to: str
    title: str
    body: str
    categoryId: str
    data: _ApprovalPushData


class _ExpoTicketDetails(BaseModel):
    error: str | None = None


class _ExpoPushTicket(BaseModel):
    status: str | None = None
    details: _ExpoTicketDetails | None = None


class _ExpoPushTickets(BaseModel):
    """Expo's reply to a push request: one ticket per message sent, in order."""

    data: list[_ExpoPushTicket] = []


async def notify_approval_pending(
    user_id: str,
    conversation_id: str,
    approval_id: str,
    summary: str,
) -> None:
    """Wake a not-actively-watching client over every channel. Never raises."""
    await asyncio.gather(
        _broadcast_in_app(user_id, conversation_id, approval_id, summary),
        _push_to_devices(user_id, conversation_id, approval_id, summary),
    )


async def _broadcast_in_app(
    user_id: str, conversation_id: str, approval_id: str, summary: str
) -> None:
    """Best-effort in-app WebSocket ping to any open client for this user."""
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "hil_approval_pending",
                "data": {
                    "conversation_id": conversation_id,
                    "approval_id": approval_id,
                    "summary": summary,
                },
            },
        )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} HIL notify: WebSocket broadcast failed",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )


async def _push_to_devices(
    user_id: str, conversation_id: str, approval_id: str, summary: str
) -> None:
    """Best-effort Expo push to the user's registered devices."""
    try:
        tokens = await device_token_repository.list_active_tokens(user_id)
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


async def _send_expo_push(
    tokens: list[str], *, conversation_id: str, approval_id: str, summary: str
) -> None:
    messages: list[_ExpoPushMessage] = [
        {
            "to": token,
            "title": "GAIA needs your approval",
            "body": summary,
            "categoryId": "hil_approval",
            "data": {
                "type": "hil_approval",
                "conversation_id": conversation_id,
                "approval_id": approval_id,
            },
        }
        for token in tokens
    ]

    dead_tokens: list[str] = []
    async with httpx.AsyncClient(timeout=_EXPO_PUSH_TIMEOUT_SECONDS) as client:
        for start in range(0, len(messages), _EXPO_PUSH_BATCH_SIZE):
            end = start + _EXPO_PUSH_BATCH_SIZE
            response = await client.post(_EXPO_PUSH_URL, json=messages[start:end])
            dead_tokens.extend(_dead_tokens_from_receipts(tokens[start:end], response))

    if dead_tokens:
        await device_token_repository.deactivate(dead_tokens)


def _dead_tokens_from_receipts(batch: list[str], response: httpx.Response) -> list[str]:
    """Return the tokens of this batch that Expo reported as DeviceNotRegistered.

    A ticket flags a permanently dead token (app uninstalled / token expired);
    a reply that is not JSON or not ticket-shaped reports none.
    """
    try:
        tickets = _ExpoPushTickets.model_validate(response.json()).data
    except ValueError:
        return []
    return [
        token
        for token, ticket in zip(batch, tickets, strict=False)
        if ticket.status == "error"
        and ticket.details is not None
        and ticket.details.error == _EXPO_DEVICE_NOT_REGISTERED
    ]
