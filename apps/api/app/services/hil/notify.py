"""Notify a user's clients that an approval is waiting.

Two independent best-effort channels — a failure here must never propagate into
the gate (the SSE card is the primary surface; these only wake a client that
isn't actively watching the stream):

- in-app WebSocket broadcast (open web/mobile clients);
- Expo push (backgrounded mobile app), with interactive approve/deny actions.
"""

import asyncio

from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.services.outbox.transport.push import push_approval_pending
from shared.py.wide_events import log


async def notify_approval_pending(
    user_id: str,
    conversation_id: str,
    approval_id: str,
    summary: str,
) -> None:
    """Wake a not-actively-watching client over every channel. Never raises."""
    await asyncio.gather(
        _broadcast_in_app(user_id, conversation_id, approval_id, summary),
        push_approval_pending(user_id, conversation_id, approval_id, summary),
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
