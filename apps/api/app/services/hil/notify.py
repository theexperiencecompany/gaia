"""Notify a user's clients that an approval is waiting.

Two independent channels, both best-effort — a failure here must never
propagate into the gate (the SSE card is the primary surface; these only wake a
client that isn't actively watching the stream):

- in-app WebSocket broadcast (open web/mobile clients);
- Expo push (backgrounded mobile app), with interactive approve/deny actions.
"""

from typing import Any

import httpx

from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import device_tokens_collection
from shared.py.wide_events import log

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_PUSH_TIMEOUT_SECONDS = 10.0


async def _active_device_tokens(user_id: str) -> list[str]:
    cursor = device_tokens_collection.find(
        {"user_id": user_id, "is_active": True}, {"token": 1}
    )
    return [doc["token"] async for doc in cursor if doc.get("token")]


async def _send_expo_push(
    tokens: list[str], *, conversation_id: str, approval_id: str, summary: str
) -> None:
    messages: list[dict[str, Any]] = [
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
    async with httpx.AsyncClient(timeout=_EXPO_PUSH_TIMEOUT_SECONDS) as client:
        await client.post(_EXPO_PUSH_URL, json=messages)


async def notify_approval_pending(
    user_id: str,
    conversation_id: str,
    approval_id: str,
    summary: str,
) -> None:
    """Wake a not-actively-watching client. Never raises into the caller."""
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
        log.warning(f"{LogTag.HIL} HIL notify: WebSocket broadcast failed: {e}")

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
        log.warning(f"{LogTag.HIL} HIL notify: Expo push failed: {e}")
