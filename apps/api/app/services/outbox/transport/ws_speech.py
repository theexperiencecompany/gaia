"""The WebSocket transport for words the user reads: the one outbox.message event."""

import asyncio
from typing import Any

from app.constants.log_tags import LogTag
from app.constants.websocket import (
    WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS,
    WS_EVENT_OUTBOX_MESSAGE,
    OutboxMessageKind,
    ReportSettledOutcome,
)
from app.core.websocket_manager import websocket_manager
from shared.py.wide_events import log

_BROADCAST_ATTEMPTS = 2


async def _broadcast_with_retry(user_id: str, event: dict[str, Any]) -> None:
    """Push an event to the user's open clients; one retry, then log and give up."""
    for attempt in range(_BROADCAST_ATTEMPTS):
        try:
            await websocket_manager.broadcast_to_user(user_id, event)
            return
        except Exception as ws_err:
            log.warning(
                f"{LogTag.AGENT} outbox broadcast attempt failed",
                attempt=attempt + 1,
                user_id=user_id,
                error=str(ws_err),
            )
            if attempt < _BROADCAST_ATTEMPTS - 1:
                await asyncio.sleep(WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS)


async def publish_conversation_message(
    user_id: str, conversation_id: str, message: dict[str, Any]
) -> None:
    """Push a chat message to the user's open clients; one retry, then log and give up."""
    await _broadcast_with_retry(
        user_id,
        {
            "type": WS_EVENT_OUTBOX_MESSAGE,
            "kind": OutboxMessageKind.CONVERSATION_MESSAGE,
            "conversation_id": conversation_id,
            "message": message,
        },
    )


async def publish_report_settled(
    user_id: str, conversation_id: str, message_id: str, outcome: ReportSettledOutcome
) -> None:
    """Tell the user's open clients how the run behind a status chip ended; one retry, then log and give up."""
    await _broadcast_with_retry(
        user_id,
        {
            "type": WS_EVENT_OUTBOX_MESSAGE,
            "kind": OutboxMessageKind.REPORT_SETTLED,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "outcome": outcome,
        },
    )
