"""Redis-backed handoff bridge for the mid-run browser gate.

When the agent reaches a sensitive step and the policy says "hand off", the
runner blocks on :func:`await_handoff`; the user completes the step in the
live-view and the ``/browser/handoffs/{id}/decision`` endpoint calls
:func:`resolve_handoff` (continue or cancel) from a possibly-different worker
process. Redis is the cross-process channel — the same decoupling the
cancel-stream flag uses. This is a browser-session continue/cancel signal, NOT
tool-call approval (the shared HIL system owns that).
"""

import asyncio

from app.constants.browser import (
    BROWSER_HANDOFF_CONV_KEY_PREFIX,
    BROWSER_HANDOFF_KEY_PREFIX,
    HANDOFF_KEY_TTL_SECONDS,
    HANDOFF_POLL_INTERVAL_SECONDS,
    HandoffDecision,
    HandoffStatus,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.schemas.browser import HandoffOutcome, HandoffRecord
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser.exceptions import BrowserHandoffNotOwned, BrowserUnavailableError
from shared.py.wide_events import log


def _key(handoff_id: str) -> str:
    return f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}"


def _conv_key(conversation_id: str) -> str:
    return f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}{conversation_id}"


async def create_pending_handoff(
    handoff_id: str, user_id: str, conversation_id: str, reason: str = ""
) -> None:
    """Persist a new pending handoff and return its id, or None when it already exists."""
    record = HandoffRecord(
        status=HandoffStatus.PENDING,
        user_id=user_id,
        conversation_id=conversation_id,
        reason=reason,
    )
    await _store(handoff_id, record)
    if conversation_id:
        await redis_cache.set(_conv_key(conversation_id), handoff_id, ttl=HANDOFF_KEY_TTL_SECONDS)


async def _store(handoff_id: str, record: HandoffRecord) -> None:
    stored = await redis_cache.set(
        _key(handoff_id), record, ttl=HANDOFF_KEY_TTL_SECONDS, model=HandoffRecord
    )
    if not stored:
        # A handoff that was never persisted can never be resolved by the other
        # process: the awaiting run would stall for the full timeout and a user
        # decision could be silently dropped. Fail loudly instead of stranding
        # both sides (the runner's unexpected-failure path resolves the card).
        raise BrowserUnavailableError(
            f"Could not persist handoff {handoff_id} (storage unavailable)."
        )


async def get_handoff(handoff_id: str) -> HandoffRecord | None:
    """Load a pending handoff by id, or None when unknown/expired."""
    return await redis_cache.get(_key(handoff_id), model=HandoffRecord)


async def get_conversation_pending_handoff(conversation_id: str) -> str | None:
    """The conversation's in-flight handoff id, if a browser task is waiting."""
    handoff_id = await redis_cache.get(_conv_key(conversation_id), model=str)
    return handoff_id or None


async def resolve_handoff(
    handoff_id: str, decision: HandoffDecision, user_id: str, message: str | None = None
) -> HandoffStatus | None:
    """Resolve a pending handoff, optionally attaching a free-text note the user
    sends back with a continue. Returns the new status, None if it does not
    exist/expired. Raises ``BrowserHandoffNotOwned`` if the caller does not own it.
    One-time: a settled handoff keeps its original status.
    """
    record = await get_handoff(handoff_id)
    if record is None:
        return None
    if record.user_id != user_id:
        raise BrowserHandoffNotOwned("Not authorized to resolve this handoff")

    if record.status != HandoffStatus.PENDING:
        return record.status

    new_status = (
        HandoffStatus.COMPLETED if decision == HandoffDecision.CONTINUE else HandoffStatus.CANCELLED
    )
    note = (message or "").strip() or None
    await _store(handoff_id, record.model_copy(update={"status": new_status, "message": note}))
    if record.conversation_id:
        await redis_cache.delete(_conv_key(record.conversation_id))
    log.info(
        f"{LogTag.BROWSER} Browser handoff resolved", handoff_id=handoff_id, status=new_status.value
    )
    # Explicit id: chat-message resolution runs in the stream's background task
    # where no request context exists to attribute the event.
    capture_event(
        user_id,
        AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
        {"decision": decision.value, "with_note": note is not None},
    )
    return new_status


async def await_handoff(handoff_id: str, timeout_seconds: int) -> HandoffOutcome:
    """Block until the handoff is resolved or ``timeout_seconds`` elapses, returning
    the terminal status plus any note the user attached."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        record = await get_handoff(handoff_id)
        if record is not None and record.status != HandoffStatus.PENDING:
            return HandoffOutcome(status=record.status, message=record.message)
        await asyncio.sleep(HANDOFF_POLL_INTERVAL_SECONDS)
    return HandoffOutcome(status=HandoffStatus.TIMEOUT)
