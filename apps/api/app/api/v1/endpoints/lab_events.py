"""The sandbox run event receiver: the sandbox's push door back into GAIA.

Dumb pipe: the run's HMAC token alone names the run (the path is excluded from
WorkOS auth like /sandbox/execute), and the body, any JSON object, is handed on
verbatim to wake the todo watching that run. Claude's raw hook POST and the
OpenCode plugin's {kind, raw} land the same way.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from app.constants.execute import (
    SANDBOX_LAB_EVENTS_BUDGET_WINDOW_SECONDS,
    SANDBOX_LAB_EVENTS_MAX_PER_MINUTE,
    SANDBOX_LAB_EVENTS_MAX_PER_RUN,
)
from app.schemas.common import ResponseModel
from app.services.agent_lab.lab_events import LabEventReceipt, record_lab_event
from app.services.sandbox.execute_token import SandboxExecuteClaims, claims_from_authorization
from app.services.sandbox.token_budget import TokenBudget, enforce_token_budget
from app.utils.errors import AppError
from shared.py.wide_events import log

router = APIRouter(prefix="/lab", tags=["Lab"])


class LabEventResponse(ResponseModel):
    """Accepted; the payload itself is never echoed back."""

    ok: bool
    run_id: str


LAB_EVENTS_BUDGET = TokenBudget(
    key_prefix="lab_events",
    max_calls=SANDBOX_LAB_EVENTS_MAX_PER_RUN,
    max_per_minute=SANDBOX_LAB_EVENTS_MAX_PER_MINUTE,
    window_seconds=SANDBOX_LAB_EVENTS_BUDGET_WINDOW_SECONDS,
    exhausted_message="Lab events budget exhausted for this run",
    exhausted_fix="A fresh lab run mints a fresh budget",
    rate_message="Lab events rate limit hit",
    rate_fix="Slow the hooks down or batch the work",
)


def _audit(claims: SandboxExecuteClaims, receipt: LabEventReceipt) -> None:
    # Every push from sandbox code runs one of the user's todos with no
    # per-action approval — the audit trail is the record.
    log.audit(
        "lab_event call",
        actor=claims.user_id,
        kind=receipt.kind,
        run_id=claims.run_id,
        todo_id=receipt.todo_id,
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
    log.set(lab_event={"operation": "report"})
    try:
        body: Any = await request.json()
    except Exception:
        raise AppError(
            message="sandbox run event body is not valid JSON",
            why="the push has no parseable object",
            fix="push a JSON object: the raw hook payload or {kind, raw}",
            status_code=422,
            code="agent_lab_event_not_json",
        ) from None
    if not isinstance(body, dict):
        raise AppError(
            message="sandbox run event must be a JSON object",
            why="the body is valid JSON but not an object",
            fix="push a JSON object: the raw hook payload or {kind, raw}",
            status_code=422,
            code="agent_lab_event_not_object",
        )
    claims = _claims_or_401(authorization)
    log.set(user={"id": claims.user_id}, lab_event={"run_id": claims.run_id})
    await enforce_token_budget(LAB_EVENTS_BUDGET, claims.run_id)

    receipt = await record_lab_event(claims.run_id, user_id=claims.user_id, body=body)
    _audit(claims, receipt)
    log.set_ns("lab_event", todo_id=receipt.todo_id, kind=receipt.kind)
    return LabEventResponse(ok=True, run_id=claims.run_id)
