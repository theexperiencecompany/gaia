"""The sandbox-facing execute route — code mode's only door back into GAIA.

Authenticated by the run's HMAC token alone (the sandbox has no session), so
the path is excluded from WorkOS auth. Credentials never leave the host: the
route resolves the user's tools and runs them server-side via the same
dispatch core the LLM-facing execute tool uses.
"""

from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.agents.tools.execute.dispatch import DispatchError, dispatch_tool
from app.services.sandbox.execute_token import verify_execute_token
from app.utils.errors import AppError
from shared.py.wide_events import log

router = APIRouter(prefix="/sandbox", tags=["Sandbox"])


class SandboxExecuteRequest(BaseModel):
    tool_name: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class SandboxExecuteResponse(BaseModel):
    ok: bool
    resolved_name: str
    output: Any = None
    error: DispatchError | None = None


@router.post("/execute")
async def sandbox_execute(
    payload: SandboxExecuteRequest,
    authorization: str = Header(default=""),
) -> SandboxExecuteResponse:
    log.set(sandbox_execute={"tool_name": payload.tool_name})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(
            message="Missing sandbox execute token",
            why="the route is token-authenticated; there is no session here",
            fix="Send 'Authorization: Bearer <token>' minted by run_code",
            status_code=401,
        )
    claims = verify_execute_token(token)
    log.set(user={"id": claims.user_id}, sandbox_execute={"run_id": claims.run_id})

    result = await dispatch_tool(
        user_id=claims.user_id,
        tool_name=payload.tool_name,
        data=payload.data,
        # Synthesized run config: the wrappers resolve per-user auth server-side
        # from this identity (Composio connected account, MCP token store).
        config={
            "configurable": {"user_id": claims.user_id},
            "metadata": {"user_id": claims.user_id},
        },
    )
    log.set_ns("sandbox_execute", resolved_name=result.resolved_name, ok=result.ok)
    return SandboxExecuteResponse(
        ok=result.ok,
        resolved_name=result.resolved_name,
        output=result.output,
        error=result.error,
    )
