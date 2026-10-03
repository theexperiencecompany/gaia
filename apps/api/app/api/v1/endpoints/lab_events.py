"""The lab lifecycle-event receiver — the sandbox's push door back into GAIA.

DUMB-PIPE RULE: this route authenticates the caller, verifies the session
belongs to them, and persists the raw payload verbatim. It never classifies,
interprets, or acts on kind/raw — no parsing contracts, no agent-output
abstraction. A future supervisor tick reads the stored tail and decides what
anything means; until then this module is storage only.

Authenticated by the session's HMAC token alone (the sandbox hooks have no
user session), so the path is excluded from WorkOS auth like /sandbox/execute.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.schemas.common import ResponseModel
from app.services.agent_lab.lab_events import record_lab_event
from app.services.sandbox.execute_token import claims_from_authorization
from shared.py.wide_events import log

router = APIRouter(prefix="/lab", tags=["Lab"])


class LabEventRequest(BaseModel):
    """One lifecycle push; kind is free-form, raw is the untouched agent payload."""

    session_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    raw: dict[str, Any] = Field(default_factory=dict)


class LabEventResponse(ResponseModel):
    """Accepted for storage; the payload itself is never echoed back."""

    ok: bool
    session_id: str


@router.post("/events", status_code=202)
async def report_lab_event(
    payload: LabEventRequest,
    authorization: Annotated[str, Header()] = "",  # pragma: no mutate — no scheme, same 401
) -> LabEventResponse:
    log.set(lab_event={"session_id": payload.session_id, "kind": payload.kind})
    claims = claims_from_authorization(authorization)
    log.set(user={"id": claims.user_id}, lab_event={"run_id": claims.run_id})
    session = await record_lab_event(
        payload.session_id, user_id=claims.user_id, kind=payload.kind, raw=payload.raw
    )
    log.set_ns("lab_event", session_id=session.id, kind=payload.kind)
    return LabEventResponse(ok=True, session_id=session.id)
