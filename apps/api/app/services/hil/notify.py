"""Notify a user's clients that an approval is waiting.

Independent best-effort channels — a failure here must never propagate into
the gate:

- in-app WebSocket broadcast (open web/mobile clients, which render the SSE card);
- Expo push (backgrounded mobile app), with interactive approve/deny actions;
- the bot platform a bot conversation lives on, as its yes/no prompt. A bot's
  turn ends with its reply, so the card's stream is not where a bot user sees it.
"""

import asyncio

import httpx
from pydantic import BaseModel, Field

from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.conversations import conversation_repository
from app.services.device_token_service import get_device_token_service
from app.services.platform_message_service import deliver_message_to_platform, is_bot_platform
from shared.py.wide_events import log

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
        _prompt_on_bot_platform(user_id, conversation_id, approval_id, summary),
    )


def bot_approval_prompt(summary: str) -> str:
    """Return the yes/no question a bot user answers in chat; a bot has no approve/deny buttons."""
    return (
        f"**Approval needed:** {summary}\n"
        "Reply **yes** to approve or **no** to decline. "
        f"This expires in {_format_expiry(HIL_APPROVAL_TIMEOUT_SECONDS)}."
    )


def _format_expiry(seconds: float) -> str:
    """Say the approval window in hours once it passes an hour; "360 minutes" is unreadable."""
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    hours = round(minutes / 60)
    return "1 hour" if hours == 1 else f"{hours} hours"


async def _prompt_on_bot_platform(
    user_id: str, conversation_id: str, approval_id: str, summary: str
) -> None:
    """Ask a bot conversation's user through the platform's outbound queue; no-op off bots."""
    try:
        source = await conversation_repository.get_source(conversation_id, user_id=user_id)
        if not is_bot_platform(source):
            return
        delivered = await deliver_message_to_platform(
            source, user_id, bot_approval_prompt(summary), conversation_id=conversation_id
        )
        if not delivered:
            log.warning(
                f"{LogTag.HIL} HIL notify: bot approval prompt not delivered",
                platform=str(source),
                approval_id=approval_id,
                conversation_id=conversation_id,
            )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} HIL notify: bot approval prompt failed",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
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
    messages: list[dict[str, object]] = [
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
            batch = messages[start : start + _EXPO_PUSH_BATCH_SIZE]
            response = await client.post(_EXPO_PUSH_URL, json=batch)
            dead_tokens.extend(
                _dead_tokens_from_receipts(tokens[start : start + _EXPO_PUSH_BATCH_SIZE], response)
            )

    if dead_tokens:
        await _deactivate_device_tokens(dead_tokens)


def _dead_tokens_from_receipts(tokens: list[str], response: httpx.Response) -> list[str]:
    """Return the tokens of this batch whose ticket Expo marked DeviceNotRegistered (uninstalled or expired)."""
    try:
        receipts = _ExpoPushReceipts.model_validate(response.json())
    except ValueError:
        return []
    return [
        token
        for token, ticket in zip(tokens, receipts.data, strict=False)
        if ticket.status == "error"
        and ticket.details is not None
        and ticket.details.error == _EXPO_UNREGISTERED_DEVICE_ERROR
    ]


async def _deactivate_device_tokens(tokens: list[str]) -> None:
    """Mark dead tokens inactive so _active_device_tokens stops retrying them."""
    await get_device_token_service().deactivate_tokens(tokens)
