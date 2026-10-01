"""Redis-backed handoff bridge for the mid-run browser gate.

When the agent hands off at a sensitive step the runner blocks on
await_handoff; the user completes the step in the live-view and the handoff
decision endpoint calls resolve_handoff (continue or cancel) from a possibly
different worker process, with Redis as the cross-process channel. This is a
browser-session continue/cancel signal, not tool-call approval (the shared
HIL system owns that).
"""

from app.constants.browser import (
    BROWSER_HANDOFF_KEY_PREFIX,
    BROWSER_HANDOFF_REPLY_KEY_PREFIX,
    HANDOFF_DECISION_STATUS,
    EngineFailure,
    HandoffDecision,
    HandoffKind,
    HandoffStatus,
)
from app.constants.chat import ConversationSource, SourceCategory
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.schemas.browser import HandoffOutcome, HandoffRecord
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser.exceptions import BrowserHandoffNotOwned, BrowserUnavailableError
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from app.services.browser.live_code import revoke_handoff_live_code
from shared.py.wide_events import log


def _key(handoff_id: str) -> str:
    return f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}"


def _reply_key(address: str) -> str:
    return f"{BROWSER_HANDOFF_REPLY_KEY_PREFIX}{address}"


def _settled_key(handoff_id: str) -> str:
    return f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}:settled"


def _wake_key(handoff_id: str) -> str:
    return f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}:wake"


def bot_chat_address(source: ConversationSource, user_id: str) -> str:
    """Name the requester's own chat on a bot platform, where a bot run's prompts go whichever chat started it."""
    return f"{source.value}:{user_id}"


def reply_address(conversation_id: str, user_id: str, source: ConversationSource | None) -> str:
    """Where the user's chat reply to a handoff arrives: their bot chat on the platform the prompt went to, else the conversation showing the card.

    A group-started bot run is therefore answered from the requester's DM.
    """
    if source is not None and SourceCategory.from_source(source) is SourceCategory.BOT:
        return bot_chat_address(source, user_id)
    return conversation_id


async def create_pending_handoff(
    handoff_id: str,
    user_id: str,
    conversation_id: str,
    reason: str = "",
    kind: HandoffKind = HandoffKind.USER,
    reply_to: str = "",
) -> None:
    """Persist a new pending handoff of this kind.

    Only a USER handoff takes a reply address (see reply_address): that key is
    what makes a plain chat reply resolve it, and an agent-guidance pause is not
    something the user was ever asked about.
    """
    address = reply_to if kind is HandoffKind.USER else ""
    record = HandoffRecord(
        status=HandoffStatus.PENDING,
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,
        reason=reason,
        reply_address=address,
    )
    stored = await redis_cache.set(
        _key(handoff_id), record, ttl=browser_job_ttl_seconds(), model=HandoffRecord
    )
    if not stored:
        raise _storage_unavailable(handoff_id)
    if address:
        await redis_cache.client.set(_reply_key(address), handoff_id, ex=browser_job_ttl_seconds())


def _storage_unavailable(handoff_id: str) -> BrowserUnavailableError:
    # A handoff that was never persisted can never be resolved by the other
    # process (the run would stall for the full timeout), so fail loudly; the
    # runner's unexpected-failure path resolves the card.
    return BrowserUnavailableError(f"Could not persist handoff {handoff_id} (storage unavailable).")


async def get_handoff(handoff_id: str) -> HandoffRecord | None:
    """Load a handoff by id with its decision, or None when unknown/expired."""
    record = await redis_cache.get(_key(handoff_id), model=HandoffRecord)
    if record is None:
        return None
    decided = await _decision(handoff_id)
    if decided is None:
        return record
    return record.model_copy(update={"status": decided.status, "message": decided.message})


async def _decision(handoff_id: str) -> HandoffOutcome | None:
    """Return the one decision a handoff was settled with, note and all; None while it is pending."""
    return await redis_cache.get(_settled_key(handoff_id), model=HandoffOutcome)


async def get_pending_handoff_for_reply(address: str) -> str | None:
    """Return the in-flight handoff a chat reply at this address answers, if a browser task is waiting."""
    return await redis_cache.client.get(_reply_key(address)) or None


async def resolve_handoff(
    handoff_id: str,
    decision: HandoffDecision,
    user_id: str,
    message: str | None = None,
    *,
    redirect: bool = False,
) -> HandoffStatus | None:
    """Resolve a pending handoff, optionally attaching a free-text note the user sends back with a continue.

    redirect marks the note as the user replacing the task, which only the reply
    classifier says. Return the new status, or None when it does not exist or
    expired. Raise BrowserHandoffNotOwned for another user's handoff. One-time:
    a settled handoff keeps its original status.
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

    new_status = HANDOFF_DECISION_STATUS[decision]
    note = (message or "").strip() or None
    settled = await _settle(
        handoff_id,
        HandoffOutcome(status=new_status, message=note, redirect=redirect and note is not None),
    )
    if settled.status is not new_status:
        return settled.status
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


async def cancel_handoff(handoff_id: str) -> HandoffStatus:
    """Settle a handoff as CANCELLED because its run was stopped; return the decision of record."""
    return (await _settle(handoff_id, HandoffOutcome(status=HandoffStatus.CANCELLED))).status


async def fail_handoff(handoff_id: str, cause: EngineFailure) -> HandoffStatus:
    """Settle a handoff as FAILED because the browser it waits on is gone; return the decision of record."""
    return (
        await _settle(handoff_id, HandoffOutcome(status=HandoffStatus.FAILED, cause=cause))
    ).status


async def _settle(handoff_id: str, outcome: HandoffOutcome) -> HandoffOutcome:
    """Claim the one decision for a handoff and wake its waiter; return the decision of record when another won.

    The marker carries the whole decision, note included, so no reader ever
    sees a decision without the note it was sent with.
    """
    ttl = browser_job_ttl_seconds()
    if not await redis_cache.set_if_absent(
        _settled_key(handoff_id), outcome, ttl=ttl, model=HandoffOutcome
    ):
        decided = await _decision(handoff_id)
        if decided is None:
            raise _storage_unavailable(handoff_id)
        return decided
    record = await redis_cache.get(_key(handoff_id), model=HandoffRecord)
    if record is not None and record.reply_address:
        await redis_cache.delete(_reply_key(record.reply_address))
    await revoke_handoff_live_code(handoff_id)
    await redis_cache.client.rpush(_wake_key(handoff_id), outcome.status.value)
    await redis_cache.client.expire(_wake_key(handoff_id), ttl)
    return outcome


async def await_handoff(handoff_id: str, timeout_seconds: float) -> HandoffOutcome:
    """Block until the handoff is settled or timeout_seconds pass, returning its decision.

    Wakes on the settle itself. A lapse settles it TIMEOUT, so a decision that
    arrives after the run gave up is reported as late instead of accepted.
    """
    decided = await _decision(handoff_id)
    if decided is None:
        await redis_cache.client.blpop([_wake_key(handoff_id)], timeout=timeout_seconds)
        decided = await _decision(handoff_id)
    if decided is not None:
        return decided
    outcome = await _settle(handoff_id, HandoffOutcome(status=HandoffStatus.TIMEOUT))
    if outcome.status is HandoffStatus.TIMEOUT:
        log.warning(
            f"{LogTag.BROWSER} Handoff timed out with no decision",
            handoff_id=handoff_id,
            timeout_seconds=timeout_seconds,
        )
    return outcome
