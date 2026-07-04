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
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
import json
from typing import Any, Literal
from uuid import uuid4

from app.agents.core.background.session import get_session
from app.constants.cache import (
    HIL_PENDING_CONVERSATION_PREFIX,
    HIL_REQUEST_PREFIX,
    HIL_RESULT_CHANNEL_PREFIX,
)
from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    APPROVAL_TOOL_CATEGORY,
    HIL_APPROVAL_TIMEOUT_SECONDS,
    HIL_REQUEST_TTL_GRACE_SECONDS,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.utils.errors import AppError
from shared.py.wide_events import log

ApprovalStatus = Literal["pending", "approved", "denied", "timeout"]

_PUBSUB_POLL_SECONDS = 1.0
_MAX_SUMMARY_ARGS = 2
_MAX_ARG_VALUE_LEN = 60


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


def build_summary(tool_name: str, args: dict[str, Any], integration_name: str | None) -> str:
    """Deterministic one-line summary of a gated call (no LLM in the hot path)."""
    label = tool_name.replace("_", " ").strip().capitalize()
    if integration_name:
        label = f"{label} ({integration_name})"
    parts: list[str] = []
    for key, value in (args or {}).items():
        if len(parts) >= _MAX_SUMMARY_ARGS:
            break
        if isinstance(value, (str, int, float, bool)):
            text = str(value)
            if len(text) > _MAX_ARG_VALUE_LEN:
                text = f"{text[:_MAX_ARG_VALUE_LEN]}…"
            parts.append(f"{key}: {text}")
    return f"{label} — {', '.join(parts)}" if parts else label


def _entry(
    approval_id: str,
    tool_call: dict[str, Any],
    *,
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


async def _publish_entry(stream_id: str, entry: dict[str, Any]) -> None:
    """Deliver a frame live (replayable event log) AND record it for persistence.

    The session append mirrors ``make_redis_stream_writer`` so the executor
    drain path persists the card; the SSE publish reaches live/reloaded clients.
    """
    await stream_manager.publish_chunk(
        stream_id, f"data: {json.dumps({'tool_data': entry})}\n\n"
    )
    session = get_session(stream_id)
    if session is not None:
        session.tool_events.append({"tool_data": entry})


async def request_approval(
    *,
    stream_id: str,
    user_id: str,
    conversation_id: str,
    tool_call: dict[str, Any],
    summary: str,
    integration_name: str | None,
) -> ApprovalOutcome:
    """Publish the approval card and block until decision or timeout."""
    if not redis_cache.redis:
        log.error(f"{LogTag.HIL} HIL bridge: Redis unavailable — failing closed")
        return ApprovalOutcome(status="denied", feedback="approval system unavailable")

    approval_id = str(uuid4())
    request_key = f"{HIL_REQUEST_PREFIX}{approval_id}"
    pending_set_key = f"{HIL_PENDING_CONVERSATION_PREFIX}{conversation_id}"
    result_channel = f"{HIL_RESULT_CHANNEL_PREFIX}{approval_id}"
    ttl = int(HIL_APPROVAL_TIMEOUT_SECONDS) + HIL_REQUEST_TTL_GRACE_SECONDS

    log.set(hil={"approval_id": approval_id, "tool": tool_call.get("name"), "stream_id": stream_id})

    await redis_cache.set(
        request_key,
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "stream_id": stream_id,
            "tool_name": tool_call.get("name", ""),
            "summary": summary,
        },
        ttl=ttl,
    )
    await redis_cache.redis.sadd(pending_set_key, approval_id)
    await redis_cache.redis.expire(pending_set_key, ttl)

    pubsub = redis_cache.redis.pubsub()
    try:
        # Subscribe before publishing so a fast decision can never slip through.
        await pubsub.subscribe(result_channel)
        await _publish_entry(
            stream_id,
            _entry(
                approval_id,
                tool_call,
                status="pending",
                summary=summary,
                integration_name=integration_name,
            ),
        )

        try:
            async with asyncio.timeout(HIL_APPROVAL_TIMEOUT_SECONDS):
                outcome = await _await_decision(pubsub)
        except TimeoutError:
            outcome = ApprovalOutcome(status="timeout")

        await _publish_entry(
            stream_id,
            _entry(
                approval_id,
                tool_call,
                status=outcome.status,
                summary=summary,
                integration_name=integration_name,
                feedback=outcome.feedback,
            ),
        )
        return outcome
    finally:
        # Best-effort cleanup in independent guards — never mask the outcome.
        try:
            await redis_cache.delete(request_key)
            await redis_cache.redis.srem(pending_set_key, approval_id)
        except Exception:  # nosec B110 - cleanup must not mask the outcome
            pass
        try:
            await pubsub.unsubscribe(result_channel)
            await pubsub.aclose()
        except Exception:  # nosec B110 - cleanup must not mask the outcome
            pass


async def _await_decision(pubsub: Any) -> ApprovalOutcome:
    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=_PUBSUB_POLL_SECONDS
        )
        if message is None or message["type"] != "message":
            continue
        raw = message["data"]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"{LogTag.HIL} HIL bridge: discarding malformed decision payload")
            continue
        decision = payload.get("decision")
        return ApprovalOutcome(
            status="approved" if decision == "approve" else "denied",
            feedback=payload.get("feedback"),
            scope=payload.get("scope", "once"),
        )


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
    request_key = f"{HIL_REQUEST_PREFIX}{approval_id}"
    pending = await redis_cache.get(request_key)
    if not pending:
        raise ApprovalRequestNotFound()
    if pending.get("user_id") != user_id:
        raise ApprovalRequestForbidden()

    await redis_cache.delete(request_key)
    await redis_cache.redis.publish(
        f"{HIL_RESULT_CHANNEL_PREFIX}{approval_id}",
        json.dumps({"decision": decision, "feedback": feedback, "scope": scope}),
    )
    return pending


async def pending_approvals_for_conversation(conversation_id: str) -> list[dict[str, Any]]:
    """Pending request payloads (with ids) for the conversational resolver."""
    if not redis_cache.redis:
        return []
    pending_set_key = f"{HIL_PENDING_CONVERSATION_PREFIX}{conversation_id}"
    ids = await redis_cache.redis.smembers(pending_set_key)
    out: list[dict[str, Any]] = []
    for raw_id in ids:
        approval_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        payload = await redis_cache.get(f"{HIL_REQUEST_PREFIX}{approval_id}")
        if payload:
            out.append({"approval_id": approval_id, **payload})
    return out
