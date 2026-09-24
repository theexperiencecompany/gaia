"""Redis-backed handoff bridge for the mid-run browser gate.

When the agent hands off at a sensitive step the runner blocks on
await_handoff; the user completes the step in the live-view and the handoff
decision endpoint calls resolve_handoff (continue or cancel) from a possibly
different worker process, with Redis as the cross-process channel. This is a
browser-session continue/cancel signal, not tool-call approval (the shared
HIL system owns that).
"""

import asyncio

from app.constants.browser import (
    BROWSER_HANDOFF_CONV_KEY_PREFIX,
    BROWSER_HANDOFF_KEY_PREFIX,
    HANDOFF_KEY_TTL_SECONDS,
    HANDOFF_POLL_INTERVAL_SECONDS,
    HandoffDecision,
    HandoffKind,
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


def _settled_key(handoff_id: str) -> str:
    return f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}:settled"


async def create_pending_handoff(
    handoff_id: str,
    user_id: str,
    conversation_id: str,
    reason: str = "",
    kind: HandoffKind = HandoffKind.USER,
) -> None:
    """Persist a new pending handoff of this kind.

    Only a USER handoff takes the conversation's lookup key: that key is what
    makes a plain chat reply resolve a handoff, and an agent-guidance pause is
    not something the user was ever asked about.
    """
    record = HandoffRecord(
        status=HandoffStatus.PENDING,
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,
        reason=reason,
    )
    await _store(handoff_id, record)
    if conversation_id and kind is HandoffKind.USER:
        await redis_cache.set(_conv_key(conversation_id), handoff_id, ttl=HANDOFF_KEY_TTL_SECONDS)


def _storage_unavailable(handoff_id: str) -> BrowserUnavailableError:
    # A handoff that was never persisted can never be resolved by the other
    # process (the run would stall for the full timeout), so fail loudly; the
    # runner's unexpected-failure path resolves the card.
    return BrowserUnavailableError(f"Could not persist handoff {handoff_id} (storage unavailable).")


async def _store(handoff_id: str, record: HandoffRecord) -> None:
    stored = await redis_cache.set(
        _key(handoff_id), record, ttl=HANDOFF_KEY_TTL_SECONDS, model=HandoffRecord
    )
    if not stored:
        raise _storage_unavailable(handoff_id)


async def get_handoff(handoff_id: str) -> HandoffRecord | None:
    """Load a handoff by id, or None when unknown/expired.

    The settled marker is the decision of record: a resolver that claimed it but
    died before rewriting the record still counts as settled, so a waiter never
    polls a decided handoff until its timeout.
    """
    record = await _stored(handoff_id)
    if record is None or record.status != HandoffStatus.PENDING:
        return record
    settled = await redis_cache.get(_settled_key(handoff_id), model=str)
    return record.model_copy(update={"status": HandoffStatus(settled)}) if settled else record


async def _stored(handoff_id: str) -> HandoffRecord | None:
    """Read the record as the resolver last wrote it, with no settle marker over the top."""
    return await redis_cache.get(_key(handoff_id), model=HandoffRecord)


async def get_conversation_pending_handoff(conversation_id: str) -> str | None:
    """Return the conversation's in-flight handoff id, if a browser task is waiting."""
    # model=str only narrows the type: a stored str decodes to the same str without it.
    handoff_id = await redis_cache.get(_conv_key(conversation_id), model=str)  # pragma: no mutate
    return handoff_id or None


async def resolve_handoff(
    handoff_id: str, decision: HandoffDecision, user_id: str, message: str | None = None
) -> HandoffStatus | None:
    """Resolve a pending handoff, optionally attaching a free-text note the user sends back with a continue.

    Return the new status, or None when it does not exist or expired. Raise
    BrowserHandoffNotOwned when the caller does not own it. One-time: a settled
    handoff keeps its original status.
    """
    record = await get_handoff(handoff_id)
    if record is None:
        log.warning(
            f"{LogTag.BROWSER} Handoff decision dropped: no such handoff, or it expired",
            handoff_id=handoff_id,
        )
        return None
    if record.user_id != user_id:
        raise BrowserHandoffNotOwned("Not authorized to resolve this handoff")

    if record.status != HandoffStatus.PENDING:
        log.info(
            f"{LogTag.BROWSER} Handoff decision late: already settled",
            handoff_id=handoff_id,
            status=record.status.value,
        )
        return record.status

    new_status = (
        HandoffStatus.COMPLETED if decision == HandoffDecision.CONTINUE else HandoffStatus.CANCELLED
    )
    note = (message or "").strip() or None
    settled_as = await _settle(handoff_id, record, new_status, note)
    if settled_as is not new_status:
        return settled_as
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


async def _settle(
    handoff_id: str, record: HandoffRecord, status: HandoffStatus, note: str | None
) -> HandoffStatus:
    """Claim the one decision for a handoff; return the decision of record when another won."""
    if not await redis_cache.set_if_absent(
        _settled_key(handoff_id), status.value, ttl=HANDOFF_KEY_TTL_SECONDS
    ):
        # Another resolver settled it first: report that decision, never a second,
        # conflicting one. Still PENDING here means the marker write itself failed.
        settled = await get_handoff(handoff_id)
        if settled is None or settled.status == HandoffStatus.PENDING:
            raise _storage_unavailable(handoff_id)
        return settled.status
    await _store(handoff_id, record.model_copy(update={"status": status, "message": note}))
    if record.conversation_id and record.kind is HandoffKind.USER:
        # An AGENT record never wrote this key, so deleting it here would free a
        # user handoff waiting in the same conversation.
        await redis_cache.delete(_conv_key(record.conversation_id))
    return status


async def await_handoff(handoff_id: str, timeout_seconds: int) -> HandoffOutcome:
    """Block until the handoff is resolved or timeout_seconds elapses, returning the terminal status plus any note the user attached.

    A timeout settles the handoff as TIMEOUT, so a decision that arrives after the
    run gave up is reported as late instead of accepted, and the conversation no
    longer looks like it is waiting on the user.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:  # pragma: no mutate — < and <= differ only on one clock tick
        # The resolver claims the settle marker before it rewrites the record, so
        # reading the marker here would return a decision without the note it
        # carried -- and the note is the whole point of a continue.
        record = await _stored(handoff_id)
        if record is not None and record.status != HandoffStatus.PENDING:
            return HandoffOutcome(status=record.status, message=record.message)
        await asyncio.sleep(HANDOFF_POLL_INTERVAL_SECONDS)
    record = await get_handoff(handoff_id)
    if record is None:
        return HandoffOutcome(status=HandoffStatus.TIMEOUT)
    if record.status != HandoffStatus.PENDING:
        return HandoffOutcome(status=record.status, message=record.message)
    if await _settle(handoff_id, record, HandoffStatus.TIMEOUT, None) is HandoffStatus.TIMEOUT:
        log.warning(
            f"{LogTag.BROWSER} Handoff timed out with no decision",
            handoff_id=handoff_id,
            timeout_seconds=timeout_seconds,
        )
        return HandoffOutcome(status=HandoffStatus.TIMEOUT)
    # A decision landed on the deadline; it, and its note, are the outcome.
    decided = await get_handoff(handoff_id)
    if decided is None:
        return HandoffOutcome(status=HandoffStatus.TIMEOUT)
    return HandoffOutcome(status=decided.status, message=decided.message)
