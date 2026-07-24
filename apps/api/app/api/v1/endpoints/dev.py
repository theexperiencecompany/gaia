"""Dev-only identity + seeding endpoints (mounted only in development).

Mint users, seed deterministic sample data, and tear them down so coding agents
can bootstrap a full environment without a WorkOS login. The router is mounted
by ``create_app`` only when ``ENV == development`` and ``DEV_AUTH_BYPASS_EMAIL``
is set, so every route here 404s in production.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.dev_schemas import (
    CreateDevUserRequest,
    DeleteDevUserResponse,
    DevAgentRunResponse,
    DevSubagentInfo,
    DevUserResponse,
    RunDevAgentRequest,
    SeedDevDataRequest,
    SeedDevDataResponse,
)
from app.services.dev_agent_service import (
    list_dev_subagents,
    run_executor_direct,
    run_subagent_direct,
)
from app.services.dev_service import delete_dev_user, mint_dev_user, seed_dev_data
from shared.py.wide_events import log

router = APIRouter(prefix="/dev", tags=["Dev"])


@router.post("/users", response_model=DevUserResponse)
async def create_dev_user(payload: CreateDevUserRequest) -> JSONResponse:
    """Idempotently mint (find-or-create) a dev user by email."""
    log.set(dev={"operation": "mint_user", "email": payload.email})
    user = await mint_dev_user(payload.email, payload.name)
    log.set(dev={"user_id": user["id"]})
    return JSONResponse(content=user)


@router.post("/seed", response_model=SeedDevDataResponse)
async def seed_dev_user_data(payload: SeedDevDataRequest) -> JSONResponse:
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
    log.set(dev={"user_id": result["user_id"]})
    return JSONResponse(content=result)


@router.delete("/users/{email}", response_model=DeleteDevUserResponse)
async def remove_dev_user(email: str) -> JSONResponse:
    """Remove a dev user and the data it owns (teardown for tests)."""
    log.set(dev={"operation": "delete_user", "email": email})
    result = await delete_dev_user(email)
    log.set(dev={"user_id": result["user_id"]})
    return JSONResponse(content=result)


@router.get("/subagents", response_model=list[DevSubagentInfo])
async def list_subagents() -> JSONResponse:
    """List every registered subagent runnable via POST /dev/subagents/{id}."""
    log.set(dev={"operation": "list_subagents"})
    subagents = list_dev_subagents()
    log.set(dev={"count": len(subagents)})
    return JSONResponse(content=subagents)


@router.post("/executor", response_model=DevAgentRunResponse)
async def run_executor(payload: RunDevAgentRequest) -> JSONResponse:
    """Run the executor agent directly with a task, skipping the comms agent."""
    log.set(dev={"operation": "run_executor", "email": payload.email})
    result = await run_executor_direct(payload.email, payload.task, payload.conversation_id)
    log.set(dev={"user_id": result["user_id"], "thread_id": result["thread_id"]})
    return JSONResponse(content=result)


@router.post("/subagents/{subagent_id}", response_model=DevAgentRunResponse)
async def run_subagent(subagent_id: str, payload: RunDevAgentRequest) -> JSONResponse:
    """Run one subagent directly with a task, skipping comms and the executor."""
    log.set(dev={"operation": "run_subagent", "email": payload.email, "subagent_id": subagent_id})
    result = await run_subagent_direct(
        payload.email, subagent_id, payload.task, payload.conversation_id
    )
    log.set(dev={"user_id": result["user_id"], "thread_id": result["thread_id"]})
    return JSONResponse(content=result)
