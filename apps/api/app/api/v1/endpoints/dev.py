"""Dev-only identity + seeding endpoints (mounted only in development).

Mint users, seed deterministic sample data, and tear them down so coding agents
can bootstrap a full environment without a WorkOS login. The router is mounted
by ``create_app`` only when ``ENV == development`` and ``DEV_AUTH_BYPASS_EMAIL``
is set, so every route here 404s in production.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.schemas.dev_schemas import (
    CreateDevUserRequest,
    DeleteDevUserResponse,
    DevAgentRunResponse,
    DevSubagentInfo,
    RunDevAgentRequest,
    SeedDevDataRequest,
    SeedDevDataResponse,
)
from app.services.briefing.service import run_daily_briefing, run_weekly_digest
from app.services.dev_agent_service import (
    list_dev_subagents,
    run_executor_direct,
    run_subagent_direct,
)
from app.services.dev_service import delete_dev_user, mint_dev_user, seed_dev_data
from shared.py.wide_events import log

router = APIRouter(prefix="/dev", tags=["Dev"])

_BRIEFING_RUNS = {"daily": run_daily_briefing, "weekly": run_weekly_digest}


@router.post("/users")
async def create_dev_user(payload: CreateDevUserRequest) -> UserDocument:
    """Idempotently mint (find-or-create) a dev user by email."""
    log.set(dev={"operation": "mint_user", "email": payload.email})
    user = await mint_dev_user(payload.email, payload.name)
    log.set(dev={"user_id": user.id})
    return user


@router.post("/seed")
async def seed_dev_user_data(payload: SeedDevDataRequest) -> SeedDevDataResponse:
    """Seed deterministic todos/conversations/platform links for an existing dev user."""
    log.set(
        dev={
            "operation": "seed",
            "email": payload.email,
            "todos": payload.todos,
            "conversations": payload.conversations,
        }
    )
    result = await seed_dev_data(
        payload.email, payload.todos, payload.conversations, payload.platform_links
    )
    log.set(dev={"user_id": result.user_id})
    return result


@router.delete("/users/{email}")
async def remove_dev_user(email: str) -> DeleteDevUserResponse:
    """Remove a dev user and the data it owns (teardown for tests)."""
    log.set(dev={"operation": "delete_user", "email": email})
    result = await delete_dev_user(email)
    log.set(dev={"user_id": result.user_id})
    return result


@router.get("/subagents")
async def list_subagents() -> list[DevSubagentInfo]:
    """List every registered subagent runnable via POST /dev/subagents/{id}."""
    log.set(dev={"operation": "list_subagents"})
    subagents = list_dev_subagents()
    log.set(dev={"count": len(subagents)})
    return subagents


@router.post("/executor")
async def run_executor(payload: RunDevAgentRequest) -> DevAgentRunResponse:
    """Run the executor agent directly with a task, skipping the comms agent."""
    log.set(dev={"operation": "run_executor", "email": payload.email})
    result = await run_executor_direct(payload.email, payload.task, payload.conversation_id)
    log.set(dev={"user_id": result.user_id, "thread_id": result.thread_id})
    return result


@router.post("/subagents/{subagent_id}")
async def run_subagent(subagent_id: str, payload: RunDevAgentRequest) -> DevAgentRunResponse:
    """Run one subagent directly with a task, skipping comms and the executor."""
    log.set(dev={"operation": "run_subagent", "email": payload.email, "subagent_id": subagent_id})
    result = await run_subagent_direct(
        payload.email, subagent_id, payload.task, payload.conversation_id
    )
    log.set(dev={"user_id": result.user_id, "thread_id": result.thread_id})
    return result


@router.post("/briefing/{kind}/{email}")
async def run_briefing_now(kind: str, email: str) -> JSONResponse:
    """Run the full daily/weekly briefing pipeline for a dev user, synchronously.

    The founder-day harness's trigger: same code path as the cron (curation →
    context → silent agent run → persist → deliver), without waiting for 8am.
    """
    log.set(dev={"operation": "run_briefing", "kind": kind, "email": email})
    run = _BRIEFING_RUNS.get(kind)
    if run is None:
        raise HTTPException(status_code=400, detail="kind must be 'daily' or 'weekly'")
    user = await user_repository.get_by_email(email)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail=f"No GAIA user exists for '{email}' — mint it via POST /api/v1/dev/users",
        )
    await run(user.id)
    log.set(dev={"user_id": user.id})
    return JSONResponse(content={"user_id": user.id, "kind": kind, "status": "completed"})
