"""Request/response bridge between the HIL gate and the user's clients.

The gate publishes an ``approval_request`` tool_data frame onto the turn's SSE
stream and blocks on a per-request Redis result channel. A decision arrives via
``POST /approvals/{id}/decision`` (buttons) or the conversational resolver, is
relayed over Redis (pub/sub crosses uvicorn workers), and the gate resumes.

Frame delivery mirrors ``make_redis_stream_writer``: every frame is both
published to the replayable stream event log (live + reload) AND appended to the
stream session's tool-event collector so the executor drain path persists it.
The gate only fires inside the detached executor/subagent (comms holds no gated
tools), where ``get_stream_writer`` is unavailable — so this dual write, keyed
purely by ``stream_id``, is what makes the card work at every nesting depth.
"""

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from http import HTTPStatus
import json
from typing import Any, Literal
from uuid import uuid4

from app.agents.core.background.session import get_session
from app.constants.cache import (
    HIL_DECLINED_PREFIX,
    HIL_PENDING_CONVERSATION_PREFIX,
    HIL_REQUEST_PREFIX,
    HIL_RESULT_CHANNEL_PREFIX,
)
from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    APPROVAL_TOOL_CATEGORY,
    HIL_APPROVAL_TIMEOUT_SECONDS,
    HIL_DECLINE_MEMORY_TTL_SECONDS,
    HIL_REQUEST_TTL_GRACE_SECONDS,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.services.hil.notify import notify_approval_pending
from app.utils.errors import AppError
from shared.py.wide_events import log

ApprovalStatus = Literal["pending", "approved", "denied", "timeout"]

_PUBSUB_POLL_SECONDS = 1.0
_MAX_SUMMARY_ARGS = 2
_MAX_ARG_VALUE_LEN = 60

# Keep-alive set so fire-and-forget notify tasks aren't GC'd mid-flight
# (asyncio.create_task holds only a weak reference).
_notify_tasks: set[asyncio.Task[None]] = set()


class ApprovalRequestNotFound(AppError):
    def __init__(self) -> None:
        super().__init__(
            message="Approval request expired or already resolved",
            status_code=HTTPStatus.GONE,
        )


class ApprovalRequestForbidden(AppError):
    def __init__(self) -> None:
        super().__init__(
            message="Approval request belongs to another user",
            status_code=HTTPStatus.FORBIDDEN,
        )


@dataclass
class ApprovalOutcome:
    status: ApprovalStatus
    feedback: str | None = None
    scope: str = "once"


async def request_approval(
    *,
    stream_id: str,
    user_id: str,
    conversation_id: str,
    tool_call: dict[str, Any],
    summary: str,
    integration_name: str | None,
) -> ApprovalOutcome:
    """Publish the approval card and block until the user decides or it times out."""
    if not redis_cache.redis:
        log.error(f"{LogTag.HIL} HIL bridge: Redis unavailable — failing closed")
        return ApprovalOutcome(status="denied", feedback="approval system unavailable")

    approval_id = str(uuid4())
    log.set(hil={"approval_id": approval_id, "tool": tool_call.get("name"), "stream_id": stream_id})
    await _register_pending_request(
        approval_id, conversation_id, stream_id, user_id, summary, tool_call.get("name", "")
    )

    pubsub = redis_cache.redis.pubsub()
    try:
        # Subscribe before publishing so a fast decision can never slip through.
        await pubsub.subscribe(_result_channel(approval_id))
        await _publish_entry(
            stream_id,
            _approval_entry(approval_id, tool_call, "pending", summary, integration_name),
        )
        _schedule_pending_notification(user_id, conversation_id, approval_id, summary)

        outcome = await _wait_for_decision(pubsub)
        await _publish_entry(
            stream_id,
            _approval_entry(
                approval_id, tool_call, outcome.status, summary, integration_name, outcome.feedback
            ),
        )
        return outcome
    finally:
        await _cleanup_pending_request(approval_id, conversation_id, pubsub)


async def relay_approval_decision(
    *,
    approval_id: str,
    user_id: str,
    decision: str,
    feedback: str | None,
    scope: str,
) -> dict[str, Any]:
    """Validate ownership, consume the pending key, publish the decision.

    Returns the pending-request payload (the conversational resolver uses it).
    Deletes the request key before publishing so late/duplicate deliveries
    cannot double-resolve — the same idempotency contract as the desktop bridge.
    """
    pending = await redis_cache.get(_request_key(approval_id))
    if not pending:
        raise ApprovalRequestNotFound()
    if pending.get("user_id") != user_id:
        raise ApprovalRequestForbidden()

    await redis_cache.delete(_request_key(approval_id))
    await redis_cache.redis.publish(
        _result_channel(approval_id),
        json.dumps({"decision": decision, "feedback": feedback, "scope": scope}),
    )
    return pending


async def pending_approvals_for_conversation(conversation_id: str) -> list[dict[str, Any]]:
    """Pending request payloads (with ids) for the conversational resolver."""
    if not redis_cache.redis:
        return []
    ids = await redis_cache.redis.smembers(_pending_set_key(conversation_id))
    out: list[dict[str, Any]] = []
    for raw_id in ids:
        approval_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        payload = await redis_cache.get(_request_key(approval_id))
        if payload:
            out.append({"approval_id": approval_id, **payload})
    return out


async def remember_declined_call(
    stream_id: str, tool_name: str, args: dict[str, Any], feedback: str | None
) -> None:
    """Record that the user declined this exact call for the rest of the turn."""
    if not redis_cache.redis:
        return
    await redis_cache.set(
        _declined_key(stream_id, tool_name, args),
        {"feedback": feedback},
        ttl=HIL_DECLINE_MEMORY_TTL_SECONDS,
    )


async def recall_declined_call(
    stream_id: str, tool_name: str, args: dict[str, Any]
) -> ApprovalOutcome | None:
    """The prior decline for this exact call in this turn, if any — so the gate
    can auto-deny a retry with the user's original feedback and never re-prompt."""
    if not redis_cache.redis:
        return None
    record = await redis_cache.get(_declined_key(stream_id, tool_name, args))
    if not record:
        return None
    return ApprovalOutcome(status="denied", feedback=record.get("feedback"))


def build_summary(tool_name: str, args: dict[str, Any], integration_name: str | None) -> str:
    """Deterministic one-line summary of a gated call (no LLM in the hot path)."""
    label = tool_name.replace("_", " ").strip().capitalize()
    if integration_name:
        label = f"{label} ({integration_name})"
    parts = _summary_arg_parts(args)
    return f"{label} — {', '.join(parts)}" if parts else label


# --- internals -----------------------------------------------------------------


async def _register_pending_request(
    approval_id: str,
    conversation_id: str,
    stream_id: str,
    user_id: str,
    summary: str,
    tool_name: str,
) -> None:
    """Record the pending request (owner + per-conversation index) in Redis."""
    ttl = int(HIL_APPROVAL_TIMEOUT_SECONDS) + HIL_REQUEST_TTL_GRACE_SECONDS
    await redis_cache.set(
        _request_key(approval_id),
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "stream_id": stream_id,
            "tool_name": tool_name,
            "summary": summary,
        },
        ttl=ttl,
    )
    await redis_cache.redis.sadd(_pending_set_key(conversation_id), approval_id)
    await redis_cache.redis.expire(_pending_set_key(conversation_id), ttl)


async def _wait_for_decision(pubsub: Any) -> ApprovalOutcome:
    """Block on the result channel until a decision arrives or the timeout fires."""
    try:
        async with asyncio.timeout(HIL_APPROVAL_TIMEOUT_SECONDS):
            return await _read_decision(pubsub)
    except TimeoutError:
        return ApprovalOutcome(status="timeout")


async def _read_decision(pubsub: Any) -> ApprovalOutcome:
    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=_PUBSUB_POLL_SECONDS
        )
        if message is None or message["type"] != "message":
            continue
        payload = _parse_decision(message["data"])
        if payload is None:
            continue
        decision = payload.get("decision")
        return ApprovalOutcome(
            status="approved" if decision == "approve" else "denied",
            feedback=payload.get("feedback"),
            scope=payload.get("scope", "once"),
        )


def _parse_decision(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning(f"{LogTag.HIL} HIL bridge: discarding malformed decision payload")
        return None


async def _cleanup_pending_request(approval_id: str, conversation_id: str, pubsub: Any) -> None:
    """Drop the request key + pending index and tear down the pubsub.

    Best-effort in independent guards: the request key also carries a TTL, and a
    cleanup failure must never mask the real approval outcome.
    """
    with contextlib.suppress(Exception):
        await redis_cache.delete(_request_key(approval_id))
        await redis_cache.redis.srem(_pending_set_key(conversation_id), approval_id)
    with contextlib.suppress(Exception):
        await pubsub.unsubscribe(_result_channel(approval_id))
        await pubsub.aclose()


def _schedule_pending_notification(
    user_id: str, conversation_id: str, approval_id: str, summary: str
) -> None:
    """Wake clients not watching the stream. Detached — a notify failure must
    never block the approval wait."""
    task = asyncio.create_task(
        notify_approval_pending(user_id, conversation_id, approval_id, summary)
    )
    _notify_tasks.add(task)
    task.add_done_callback(_notify_tasks.discard)


async def _publish_entry(stream_id: str, entry: dict[str, Any]) -> None:
    """Deliver a frame live (replayable event log) AND record it for persistence.

    The session append mirrors ``make_redis_stream_writer`` so the executor
    drain path persists the card; the SSE publish reaches live/reloaded clients.
    """
    await stream_manager.publish_chunk(stream_id, f"data: {json.dumps({'tool_data': entry})}\n\n")
    session = get_session(stream_id)
    if session is not None:
        session.tool_events.append({"tool_data": entry})


def _approval_entry(
    approval_id: str,
    tool_call: dict[str, Any],
    status: ApprovalStatus,
    summary: str,
    integration_name: str | None,
    feedback: str | None = None,
) -> dict[str, Any]:
    return {
        "tool_name": APPROVAL_REQUEST_TOOL_NAME,
        "tool_category": APPROVAL_TOOL_CATEGORY,
        "data": {
            "approval_id": approval_id,
            "tool_call_id": tool_call.get("id", ""),
            "gated_tool_name": tool_call.get("name", ""),
            "integration_name": integration_name,
            "summary": summary,
            "args_preview": tool_call.get("args", {}),
            "status": status,
            "feedback": feedback,
            "timeout_seconds": int(HIL_APPROVAL_TIMEOUT_SECONDS),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _summary_arg_parts(args: dict[str, Any]) -> list[str]:
    """Up to ``_MAX_SUMMARY_ARGS`` short ``key: value`` scalars for the summary."""
    parts: list[str] = []
    for key, value in (args or {}).items():
        if len(parts) >= _MAX_SUMMARY_ARGS:
            break
        if isinstance(value, (str, int, float, bool)):
            text = str(value)
            if len(text) > _MAX_ARG_VALUE_LEN:
                text = f"{text[:_MAX_ARG_VALUE_LEN]}…"
            parts.append(f"{key}: {text}")
    return parts


def _request_key(approval_id: str) -> str:
    return f"{HIL_REQUEST_PREFIX}{approval_id}"


def _result_channel(approval_id: str) -> str:
    return f"{HIL_RESULT_CHANNEL_PREFIX}{approval_id}"


def _pending_set_key(conversation_id: str) -> str:
    return f"{HIL_PENDING_CONVERSATION_PREFIX}{conversation_id}"


def _declined_key(stream_id: str, tool_name: str, args: dict[str, Any]) -> str:
    return f"{HIL_DECLINED_PREFIX}{stream_id}:{tool_name}:{_args_hash(args)}"


def _args_hash(args: dict[str, Any]) -> str:
    # md5 over the canonical args — a cache key, not a security boundary.
    payload = json.dumps(args or {}, sort_keys=True, default=str)
    return hashlib.md5(payload.encode(), usedforsecurity=False).hexdigest()  # nosec B324
