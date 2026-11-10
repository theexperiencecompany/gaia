"""The WebSocket transport for words the user reads: one outbox.message event, two kinds."""

import asyncio
from typing import Any

from app.constants.log_tags import LogTag
from app.constants.websocket import (
    WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS,
    WS_EVENT_OUTBOX_MESSAGE,
    OutboxMessageKind,
)
from app.core.websocket_manager import websocket_manager
from shared.py.wide_events import log

_BROADCAST_ATTEMPTS = 2


async def publish_conversation_message(
    user_id: str, conversation_id: str, message: dict[str, Any]
) -> None:
    """Push a chat message to the user's open clients; one retry, then log and give up."""
    event = {
        "type": WS_EVENT_OUTBOX_MESSAGE,
        "kind": OutboxMessageKind.CONVERSATION_MESSAGE,
        "conversation_id": conversation_id,
        "message": message,
    }
    for attempt in range(_BROADCAST_ATTEMPTS):
        try:
            await websocket_manager.broadcast_to_user(user_id, event)
            return
        except Exception as ws_err:
            log.warning(
                f"{LogTag.AGENT} publish_conversation_message: broadcast attempt failed",
                attempt=attempt + 1,
                user_id=user_id,
                error=str(ws_err),
            )
            if attempt < _BROADCAST_ATTEMPTS - 1:
                await asyncio.sleep(WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS)


async def publish_notification(user_id: str, notification: dict[str, Any]) -> None:
    """Push a delivered notification record to the user's open clients; raises on a failed publish."""
    await websocket_manager.broadcast_to_user(
        user_id,
        {
            "type": WS_EVENT_OUTBOX_MESSAGE,
            "kind": OutboxMessageKind.NOTIFICATION,
            "notification": notification,
        },
    )
