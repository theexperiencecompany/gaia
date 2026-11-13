"""The Expo push transport: words that reach a backgrounded mobile app."""

from typing import Any

import httpx

from app.constants.log_tags import LogTag
from app.services.device_token_service import get_device_token_service
from shared.py.wide_events import log

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_TIMEOUT_SECONDS = 10.0
# Expo rejects a push request carrying more than 100 messages.
_EXPO_PUSH_BATCH_SIZE = 100


async def push_approval_pending(
    user_id: str, conversation_id: str, approval_id: str, body: str
) -> None:
    """Push the composed approval ask to the user's registered devices. Best-effort: never raises."""
    try:
        tokens = await _active_device_tokens(user_id)
        if tokens:
            await _send_expo_push(
                tokens,
                conversation_id=conversation_id,
                approval_id=approval_id,
                body=body,
            )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Approval push failed",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )


async def _active_device_tokens(user_id: str) -> list[str]:
    return await get_device_token_service().get_active_tokens(user_id)


async def _send_expo_push(
    tokens: list[str], *, conversation_id: str, approval_id: str, body: str
) -> None:
    messages: list[dict[str, Any]] = [
        {
            "to": token,
            "title": "GAIA needs your approval",
            "body": body,
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
            dead_tokens.extend(_dead_tokens_from_receipts(batch, response))

    if dead_tokens:
        await _deactivate_device_tokens(dead_tokens)


def _dead_tokens_from_receipts(batch: list[dict[str, Any]], response: httpx.Response) -> list[str]:
    """Return the tokens Expo reported as DeviceNotRegistered for this batch.

    Expo replies with {"data": [ticket, ...]} aligned to the messages sent; a
    ticket flags a permanently dead token (app uninstalled / token expired).
    """
    try:
        tickets = response.json().get("data", [])
    except ValueError:
        return []
    dead: list[str] = []
    for message, ticket in zip(batch, tickets, strict=False):
        if isinstance(ticket, dict) and ticket.get("status") == "error":
            if (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                dead.append(message["to"])
    return dead


async def _deactivate_device_tokens(tokens: list[str]) -> None:
    """Mark dead tokens inactive so _active_device_tokens stops retrying them."""
    await get_device_token_service().deactivate_tokens(tokens)
