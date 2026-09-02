"""The sandbox-facing execute route — code mode's only door back into GAIA.

Authenticated by the run's HMAC token alone (the sandbox has no session), so
the path is excluded from WorkOS auth. Credentials never leave the host: the
route resolves the user's tools and runs them server-side via the same
dispatch core the LLM-facing execute tool uses.

Bash-driven scripting has no approval gate, so the blast radius is bounded
HERE: a hard per-token call budget, a per-minute rate limit, and an audit
entry per call. A runaway or injected script hits a wall, and every call is
attributable to the exact bash run (and sandbox) whose token made it.
"""

import time
from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.agents.tools.execute.dispatch import DispatchError, dispatch_tool
from app.constants.execute import (
    SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS,
    SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE,
    SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN,
)
from app.db.redis import redis_cache
from app.services.sandbox.execute_token import SandboxExecuteClaims, verify_execute_token
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


async def _enforce_budget(run_id: str) -> None:
    """Hard per-token limits — the wall a runaway or injected script hits.

    Counters live in Redis so every API replica enforces the same budget. The
    total counter's TTL exceeds any legal token lifetime, so it cannot expire
    (and reset) while its token is still valid.
    """
    total_key = f"sandbox_execute:calls:{run_id}"
    total = await redis_cache.client.incr(total_key)
    if total == 1:
        await redis_cache.client.expire(total_key, SANDBOX_EXECUTE_BUDGET_WINDOW_SECONDS)
    if total > SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN:
        raise AppError(
            message="Sandbox execute call budget exhausted for this run",
            why=f"more than {SANDBOX_EXECUTE_MAX_CALLS_PER_TOKEN} calls on one token",
            fix="Batch work inside the script; a fresh bash run mints a fresh budget",
            status_code=429,
        )
    minute_key = f"sandbox_execute:rate:{run_id}:{int(time.time() // 60)}"
    rate = await redis_cache.client.incr(minute_key)
    if rate == 1:
        await redis_cache.client.expire(minute_key, 120)
    if rate > SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE:
        raise AppError(
            message="Sandbox execute rate limit hit",
            why=f"more than {SANDBOX_EXECUTE_MAX_CALLS_PER_MINUTE} calls in one minute",
            fix="Slow the loop down or batch the work",
            status_code=429,
        )


def _audit(claims: SandboxExecuteClaims, tool_name: str, ok: bool) -> None:
    # Every proxied call from sandbox code is a sensitive act on the user's
    # accounts with no per-action approval — the audit trail is the record.
    log.audit(
        "sandbox_execute call",
        actor=claims.user_id,
        tool=tool_name,
        run_id=claims.run_id,
        sandbox_id=claims.sandbox_id,
        ok=ok,
    )


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
            fix="Tokens are injected into bash runs as GAIA_EXECUTE_TOKEN; send "
            "'Authorization: Bearer <token>'",
            status_code=401,
        )
    claims = verify_execute_token(token)
    log.set(user={"id": claims.user_id}, sandbox_execute={"run_id": claims.run_id})
    await _enforce_budget(claims.run_id)

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
        # Internal tools need graph runtime this route doesn't have, and
        # excluding them narrows what a leaked token can reach.
        integration_only=True,
    )
    _audit(claims, result.resolved_name, result.ok)
    log.set_ns("sandbox_execute", resolved_name=result.resolved_name, ok=result.ok)
    return SandboxExecuteResponse(
        ok=result.ok,
        resolved_name=result.resolved_name,
        output=result.output,
        error=result.error,
    )
