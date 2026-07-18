"""Redis-backed handoff bridge for the mid-run browser gate.

When the agent reaches a sensitive step and the policy says "hand off", the
runner blocks on :func:`await_handoff`; the user completes the step in the
Steel live-view and the ``/browser/handoffs/{id}/decision`` endpoint calls
:func:`resolve_handoff` (continue or cancel) from a possibly-different worker
process. Redis is the cross-process channel — the same decoupling the
cancel-stream flag uses. This is a browser-session continue/cancel signal, NOT
tool-call approval (the shared HIL system owns that).
"""

import asyncio

from app.constants.browser import (
    BROWSER_HANDOFF_KEY_PREFIX,
    HANDOFF_KEY_TTL_SECONDS,
    HANDOFF_POLL_INTERVAL_SECONDS,
    HandoffDecision,
    HandoffStatus,
)
from app.db.redis import get_cache, set_cache
from shared.py.wide_events import log


def _key(handoff_id: str) -> str:
    return f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}"


async def create_pending_handoff(handoff_id: str, user_id: str) -> None:
    await set_cache(
        _key(handoff_id),
        {"status": HandoffStatus.PENDING.value, "user_id": user_id},
        ttl=HANDOFF_KEY_TTL_SECONDS,
    )


async def get_handoff(handoff_id: str) -> dict | None:
    return await get_cache(_key(handoff_id))


async def resolve_handoff(
    handoff_id: str, decision: HandoffDecision, user_id: str
) -> HandoffStatus | None:
    """Resolve a pending handoff. Returns the new status, None if it does not
    exist/expired. Raises ``PermissionError`` if the caller does not own it.
    One-time: a settled handoff keeps its original status.
    """
    record = await get_handoff(handoff_id)
    if record is None:
        return None
    if record.get("user_id") != user_id:
        raise PermissionError("Not authorized to resolve this handoff")

    current = HandoffStatus(record["status"])
    if current != HandoffStatus.PENDING:
        return current

    new_status = (
        HandoffStatus.COMPLETED if decision == HandoffDecision.CONTINUE else HandoffStatus.CANCELLED
    )
    record["status"] = new_status.value
    await set_cache(_key(handoff_id), record, ttl=HANDOFF_KEY_TTL_SECONDS)
    log.info(f"Browser handoff {handoff_id} resolved: {new_status.value}")
    return new_status


async def await_handoff(handoff_id: str, timeout_seconds: int) -> HandoffStatus:
    """Block until the handoff is resolved or ``timeout_seconds`` elapses."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        record = await get_handoff(handoff_id)
        if record is not None:
            status = HandoffStatus(record["status"])
            if status != HandoffStatus.PENDING:
                return status
        await asyncio.sleep(HANDOFF_POLL_INTERVAL_SECONDS)
    return HandoffStatus.TIMEOUT
