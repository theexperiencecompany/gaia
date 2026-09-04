"""Dev-only identity + seeding endpoints (mounted only in development).

Mint users, seed deterministic sample data, attach files, and tear them down so
coding agents can bootstrap a full environment without a WorkOS login. The router
is mounted by ``create_app`` only when ``ENV == development`` and
``DEV_AUTH_BYPASS_EMAIL`` is set, so every route here 404s in production.
"""

from fastapi import APIRouter, File, Form, Header, UploadFile, status
from langgraph.errors import GraphRecursionError

from app.models.files_models import FileDocument
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
from app.services.dev_agent_service import (
    list_dev_subagents,
    run_executor_direct,
    run_subagent_direct,
)
from app.services.dev_service import (
    attach_dev_file,
    delete_dev_user,
    mint_dev_user,
    seed_dev_data,
)
from app.services.storage import SAFE_PATH_ID_PATTERN
from shared.py.wide_events import log

router = APIRouter(prefix="/dev", tags=["Dev"])


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


@router.post("/attachments", status_code=status.HTTP_201_CREATED)
async def attach_dev_conversation_file(
    file: UploadFile = File(...),
    email: str = Form(min_length=3, max_length=320),
    conversation_id: str = Form(pattern=SAFE_PATH_ID_PATTERN),
    content_length: int | None = Header(default=None, alias="content-length"),
) -> FileDocument:
    """Ingest a file for a dev user's conversation via the real upload service.

    Same ``FileService.upload`` the production upload endpoint runs, so pass the
    ``conversation_id`` a later ``POST /dev/executor`` run uses and the executor
    will surface the file to itself exactly as it does for a real chat upload.
    """
    log.set(dev={"operation": "attach_file", "email": email, "conversation_id": conversation_id})
    document = await attach_dev_file(email, conversation_id, file, content_length)
    log.set(dev={"file_id": document.file_id, "mime_type": document.type})
    return document


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
    try:
        result = await run_executor_direct(
            payload.email, payload.task, payload.conversation_id, payload.model
        )
    except GraphRecursionError as e:
        # The agent looped without converging. That is a result about the agent,
        # not a server fault: raising 500 made callers classify it as
        # infrastructure and drop it from their accuracy, which flatters the
        # agent by hiding its worst outcome.
        log.set(dev={"converged": False, "reason": str(e)[:200]})
        return DevAgentRunResponse(
            user_id="",
            conversation_id=payload.conversation_id or "",
            thread_id="",
            agent="executor_agent",
            message=f"agent did not converge: {e}",
            converged=False,
        )
    log.set(dev={"user_id": result.user_id, "thread_id": result.thread_id})
    return result


@router.post("/subagents/{subagent_id}")
async def run_subagent(subagent_id: str, payload: RunDevAgentRequest) -> DevAgentRunResponse:
    """Run one subagent directly with a task, skipping comms and the executor."""
    log.set(dev={"operation": "run_subagent", "email": payload.email, "subagent_id": subagent_id})
    result = await run_subagent_direct(
        payload.email, subagent_id, payload.task, payload.conversation_id, payload.model
    )
    log.set(dev={"user_id": result.user_id, "thread_id": result.thread_id})
    return result
