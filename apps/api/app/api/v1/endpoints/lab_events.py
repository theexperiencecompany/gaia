"""The lab lifecycle-event receiver — the sandbox's push door back into GAIA.

Dumb pipe: this route authenticates the caller, verifies the session belongs
to them, and files the raw payload's tail onto the run's tracked todo. It
never classifies or acts on kind/raw — a future supervisor reads the tail.
Authenticated by the run's HMAC token alone, so the path is excluded from
WorkOS auth like /sandbox/execute. Accepts canonical {session_id, kind, raw}
and Claude's raw hook POST alike; a hook-shaped push never 422s.
"""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from app.constants.execute import (
    SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE,
    SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN,
    SANDBOX_LAB_EVENTS_BUDGET_WINDOW_SECONDS,
    SANDBOX_LAB_EVENTS_RATE_BUCKET_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.schemas.common import ResponseModel
from app.services.agent_lab.lab_events import ParsedLabEvent, parse_lab_event_body, record_lab_event
from app.services.sandbox.execute_token import SandboxExecuteClaims, claims_from_authorization
from app.utils.errors import AppError
from shared.py.wide_events import log

router = APIRouter(prefix="/lab", tags=["Lab"])


class LabEventResponse(ResponseModel):
    """Accepted for storage; the payload itself is never echoed back."""

    ok: bool
    session_id: str


async def _enforce_lab_budget(run_id: str) -> None:
    """Per-run push limits, Redis-backed so every replica enforces one budget."""
    total_key = f"lab_events:calls:{run_id}"
    total = await redis_cache.client.incr(total_key)
    if total == 1:
        await redis_cache.client.expire(total_key, SANDBOX_LAB_EVENTS_BUDGET_WINDOW_SECONDS)
    if total > SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN:
        raise AppError(
            message="Lab events budget exhausted for this run",
            why=f"more than {SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN} pushes on one token",
            fix="A fresh lab run mints a fresh budget",
            status_code=429,
        )
    minute_key = f"lab_events:rate:{run_id}:{int(time.time()) // 60}"
    rate = await redis_cache.client.incr(minute_key)
    if rate == 1:
        await redis_cache.client.expire(minute_key, SANDBOX_LAB_EVENTS_RATE_BUCKET_TTL_SECONDS)
    if rate > SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE:
        raise AppError(
            message="Lab events rate limit hit",
            why=f"more than {SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE} pushes in one minute",
            fix="Slow the hooks down or batch the work",
            status_code=429,
        )


def _audit(claims: SandboxExecuteClaims, event: ParsedLabEvent, todo_id: str) -> None:
    # Every push from sandbox code writes to the user's todos with no per-action
    # approval — the audit trail is the record.
    log.audit(
        "lab_event call",
        actor=claims.user_id,
        kind=event.kind,
        run_id=claims.run_id,
        todo_id=todo_id,
        ok=True,
    )


def _claims_or_401(authorization: str) -> SandboxExecuteClaims:
    try:
        return claims_from_authorization(authorization)
    except AppError:
        log.warning("lab_event auth failed: bad or missing token")
        raise


@router.post("/events", status_code=202)
async def report_lab_event(
    request: Request,
    authorization: Annotated[str, Header()] = "",  # pragma: no mutate — no scheme, same 401
) -> LabEventResponse:
    try:
        body: Any = await request.json()
    except Exception:
        raise AppError(
            message="agent lab event body is not valid JSON",
            why="the push has no parseable object",
            fix="push {session_id, kind, raw} or the raw hook payload",
            status_code=422,
            code="agent_lab_event_not_identifiable",
        ) from None
    event = parse_lab_event_body(body)
    log.set(lab_event={"session_id": event.session_id, "kind": event.kind})
    claims = _claims_or_401(authorization)
    log.set(user={"id": claims.user_id}, lab_event={"run_id": claims.run_id})
    if event.session_id != claims.run_id:
        log.warning(
            "lab_event auth failed: session does not belong to the token",
            run_id=claims.run_id,
        )
        raise AppError(
            message="session does not belong to this token",
            why=f"body names {event.session_id} but the token is bound to {claims.run_id}",
            fix="push with the token minted for this run",
            status_code=403,
            code="agent_lab_session_not_owned",
        )
    await _enforce_lab_budget(claims.run_id)

    receipt = await record_lab_event(
        event.session_id, user_id=claims.user_id, kind=event.kind, raw=event.raw
    )
    _audit(claims, event, receipt.todo_id)
    log.set_ns("lab_event", session_id=receipt.id, todo_id=receipt.todo_id, kind=event.kind)
    return LabEventResponse(ok=True, session_id=receipt.id)
