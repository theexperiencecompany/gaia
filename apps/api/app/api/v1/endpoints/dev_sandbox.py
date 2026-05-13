"""Development-only smoke-test endpoints for the persistent coding sandbox.

POST /api/v1/dev/bash  — invoke the `bash` tool directly, bypassing the
                         executor agent. Useful for proving the
                         sandbox + JuiceFS + tool chain works end-to-end
                         without spinning up the chat UI.

POST /api/v1/dev/sandbox-info — return metadata about the user's current
                                 sandbox (template, shard, mount status).

Both endpoints are no-ops in production — they 404 unless ENV=development.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.py.wide_events import log
from app.agents.tools.coding import bash
from app.config.settings import settings
from app.services.sandbox import acquire_sandbox

router = APIRouter(prefix="/dev", tags=["Dev"])

# These endpoints are intentionally auth-less and dev-only — they 404 in
# production. Use them to smoke-test the persistent coding sandbox without
# having to mint a session cookie or JWT.


def _require_dev() -> None:
    """404 in production — these endpoints are smoke-test only."""
    if settings.ENV != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


class BashRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="User ID to scope the sandbox")
    command: str = Field(..., min_length=1, max_length=16_000)
    cwd: str = Field(default="/workspace")
    timeout: int = Field(default=30, ge=1, le=600)
    background: bool = Field(default=False)


class BashResponse(BaseModel):
    output: str
    user_id: str


@router.post("/bash", response_model=BashResponse, status_code=200)
async def dev_bash(payload: BashRequest) -> JSONResponse:
    """Run a shell command via the same `bash` tool the executor agent uses."""
    _require_dev()
    user_id = payload.user_id
    log.set(user={"id": user_id}, dev={"endpoint": "bash"})

    # Mirror how the agent passes config to LangChain tools.
    config: dict[str, Any] = {
        "configurable": {"user_id": user_id, "thread_id": f"dev-bash-{user_id}"},
        "metadata": {"agent_name": "dev_bash_endpoint", "user_id": user_id},
    }

    output = await bash.ainvoke(
        {
            "command": payload.command,
            "cwd": payload.cwd,
            "timeout": payload.timeout,
            "background": payload.background,
        },
        config=config,
    )

    return JSONResponse(content={"output": output, "user_id": user_id})


class SandboxInfoResponse(BaseModel):
    user_id: str
    template_id: str | None
    sandbox_id: str | None
    workspace_listing: list[str]
    mount_check: str
    juicefs_status: str


@router.get("/sandbox-info", response_model=SandboxInfoResponse, status_code=200)
async def dev_sandbox_info(user_id: str) -> JSONResponse:
    """Acquire the user's sandbox and report its low-level state.

    Forces a sandbox spawn / resume if needed. Returns the result of `df`,
    `mountpoint`, and `ls /workspace` so the caller can confirm the mount
    layer is healthy.
    """
    _require_dev()
    log.set(user={"id": user_id}, dev={"endpoint": "sandbox-info"})

    async with acquire_sandbox(user_id) as sbx:
        mount_check = await sbx.commands.run(
            "mountpoint /workspace || echo not_a_mount", timeout=10
        )
        ls = await sbx.commands.run(
            "ls -la /workspace 2>&1 | head -20", timeout=10
        )
        jfs_status = await sbx.commands.run(
            "mount | grep JuiceFS || echo no_juicefs_mount", timeout=10
        )

        return JSONResponse(
            content={
                "user_id": user_id,
                "template_id": settings.E2B_TEMPLATE_ID,
                "sandbox_id": getattr(sbx, "sandbox_id", None),
                "workspace_listing": (ls.stdout or "").splitlines(),
                "mount_check": (mount_check.stdout or "").strip(),
                "juicefs_status": (jfs_status.stdout or "").strip(),
            }
        )
