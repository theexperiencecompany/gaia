"""Memory management API routes — the settings-UI contract (plan F6).

Backed directly by the memory engine facade. Literal sub-paths
(/overview, /tree, /graph, /episodes, /documents) are declared before the
parameterized /{memory_id} routes so they never shadow each other.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.memory import (
    MEMORY_EPISODES_DEFAULT_DAYS,
    MEMORY_EPISODES_MAX_RANGE_DAYS,
    UUID_PATH_PATTERN,
    MemoryDocType,
    MemorySourceType,
)
from app.decorators import tiered_rate_limit
from app.memory.engine import memory_engine
from app.models.memory_models import (
    CreateMemoryRequest,
    CreateMemoryResponse,
    DeleteMemoryResponse,
    MemoryDocument,
    MemoryDocumentsResponse,
    MemoryEntry,
    MemoryEpisodesResponse,
    MemoryGraphResponse,
    MemoryListResponse,
    MemoryOverviewResponse,
    MemorySearchResult,
    MemoryTreeResponse,
    UpdateDocumentRequest,
    UpdateMemoryRequest,
)
from shared.py.wide_events import log

USER_DELETED_REASON = "user_deleted"

router = APIRouter()


def _require_user_id(user: dict) -> str:
    """Extract the authenticated user's ID or fail the request."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    return user_id


@router.get("")
async def list_memories(
    user: Annotated[dict, Depends(get_current_user)],
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Memories per page"),
    category: str | None = Query(
        default=None, description="Exact folder to list (e.g. 'work/gaia')"
    ),
) -> MemoryListResponse:
    """One page of the user's memories, newest first.

    ``category`` is an EXACT folder match so tree expansion shows only that
    folder's own memories.
    """
    user_id = _require_user_id(user)
    log.set(
        user={"id": user_id},
        memory={"operation": "list", "page": page, "page_size": page_size, "category": category},
    )

    result = await memory_engine.list_memories(
        user_id, page=page, page_size=page_size, category=category
    )

    log.set(memory={"operation": "list", "result_count": len(result.memories)})
    return result


@router.get("/search")
async def search_memories(
    user: Annotated[dict, Depends(get_current_user)],
    q: str = Query(min_length=1, max_length=500, description="Search query"),
    limit: int = Query(default=20, ge=1, le=50, description="Max results"),
) -> MemorySearchResult:
    """Hybrid semantic + keyword search across all of a user's memories.

    Powers the settings "All" tab search box so a query finds matching
    memories anywhere, not just on the currently loaded page.
    """
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "search", "query": q})

    result = await memory_engine.recall(user_id, q, limit=limit, include_graph_expansion=False)

    log.set(memory={"operation": "search", "result_count": len(result.memories)})
    return result


@router.get("/overview")
async def get_memory_overview(
    user: Annotated[dict, Depends(get_current_user)],
) -> MemoryOverviewResponse:
    """Headline counts and core-document previews for the settings UI."""
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "overview"})

    result = await memory_engine.get_overview(user_id)

    log.set(memory={"operation": "overview", "total_memories": result.total_memories})
    return result


@router.get("/tree")
async def get_memory_tree(
    user: Annotated[dict, Depends(get_current_user)],
) -> MemoryTreeResponse:
    """The memory folder tree with per-folder counts (memories lazy-load)."""
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "tree"})

    result = await memory_engine.get_tree(user_id)

    log.set(memory={"operation": "tree", "total_count": result.total_count})
    return result


@router.get("/graph")
async def get_memory_graph(
    user: Annotated[dict, Depends(get_current_user)],
) -> MemoryGraphResponse:
    """The entity graph: nodes, labeled edges, and their provenance memories."""
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "graph"})

    result = await memory_engine.get_graph(user_id)

    log.set(memory={"operation": "graph", "nodes": len(result.nodes), "edges": len(result.edges)})
    return result


@router.get(
    "/episodes",
    responses={
        400: {"description": "Invalid date range (start after end, or range exceeds limit)"}
    },
)
async def get_memory_episodes(
    user: Annotated[dict, Depends(get_current_user)],
    start: date | None = Query(default=None, description="Range start (inclusive)"),
    end: date | None = Query(default=None, description="Range end (inclusive)"),
) -> MemoryEpisodesResponse:
    """Journal pages for a date range (defaults to the last 14 days)."""
    user_id = _require_user_id(user)

    resolved_end = end or datetime.now(UTC).date()
    resolved_start = start or resolved_end - timedelta(days=MEMORY_EPISODES_DEFAULT_DAYS - 1)
    if resolved_start > resolved_end:
        raise HTTPException(status_code=400, detail="start must be on or before end")
    if (resolved_end - resolved_start).days + 1 > MEMORY_EPISODES_MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Date range cannot exceed {MEMORY_EPISODES_MAX_RANGE_DAYS} days",
        )

    log.set(
        user={"id": user_id},
        memory={
            "operation": "episodes",
            "start": resolved_start.isoformat(),
            "end": resolved_end.isoformat(),
        },
    )

    result = await memory_engine.get_episodes(user_id, resolved_start, resolved_end)

    log.set(memory={"operation": "episodes", "result_count": len(result.episodes)})
    return result


@router.get("/documents")
async def get_memory_documents(
    user: Annotated[dict, Depends(get_current_user)],
) -> MemoryDocumentsResponse:
    """All of the user's core memory documents."""
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "get_documents"})

    result = await memory_engine.get_documents(user_id)

    log.set(memory={"operation": "get_documents", "result_count": len(result.documents)})
    return result


@router.put("/documents/{doc_type}")
@tiered_rate_limit("memory")
async def update_memory_document(
    doc_type: MemoryDocType,
    request: UpdateDocumentRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> MemoryDocument:
    """Rewrite one core document (full replace; bumps its version)."""
    user_id = _require_user_id(user)
    log.set(
        user={"id": user_id},
        memory={
            "operation": "update_document",
            "doc_type": doc_type.value,
            "content_length": len(request.content),
        },
    )

    result = await memory_engine.update_document(user_id, doc_type, request.content)

    log.set(memory={"operation": "update_document", "version": result.version})
    return result


@router.post("")
@tiered_rate_limit("memory")
async def create_memory(
    request: CreateMemoryRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> CreateMemoryResponse:
    """Store one explicit memory (auto-categorized when no folder is given)."""
    user_id = _require_user_id(user)
    log.set(
        user={"id": user_id},
        memory={
            "operation": "create",
            "content_length": len(request.content),
            "category": request.category_path,
        },
    )

    try:
        retained = await memory_engine.retain_single(
            user_id,
            request.content,
            category_path=request.category_path,
            source_type=MemorySourceType.MANUAL,
        )
    except Exception as e:
        log.error(f"Failed to create memory for user {user_id}: {e}")
        return CreateMemoryResponse(success=False, message="Failed to create memory")

    entry = retained.entry
    log.set(memory={"operation": "create", "memory_id": entry.id, "success": True})
    return CreateMemoryResponse(
        success=True,
        memory_id=entry.id,
        message=f"Memory created under '{entry.category_path}'",
    )


@router.get("/{memory_id}/history")
async def get_memory_history(
    user: Annotated[dict, Depends(get_current_user)],
    memory_id: str = Path(pattern=UUID_PATH_PATTERN),
) -> MemorySearchResult:
    """The memory's full supersession chain, newest version first.

    Lets the UI expand a v2+ row to show the older versions it replaced.
    """
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "history", "memory_id": memory_id})

    result = await memory_engine.get_history(user_id, memory_id)

    log.set(memory={"operation": "history", "versions": len(result.memories)})
    return result


@router.patch(
    "/{memory_id}",
    responses={404: {"description": "Memory not found or already superseded"}},
)
@tiered_rate_limit("memory")
async def update_memory(
    request: UpdateMemoryRequest,
    user: Annotated[dict, Depends(get_current_user)],
    memory_id: str = Path(pattern=UUID_PATH_PATTERN),
) -> MemoryEntry:
    """Correct a memory: chains a new version, returns the new chain head."""
    user_id = _require_user_id(user)
    log.set(
        user={"id": user_id},
        memory={"operation": "update", "memory_id": memory_id},
    )

    entry = await memory_engine.update_memory(user_id, memory_id, request.content)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory not found or already superseded")

    log.set(memory={"operation": "update", "new_memory_id": entry.id, "version": entry.version})
    return entry


@router.delete(
    "/{memory_id}",
    responses={404: {"description": "Memory not found"}},
)
@tiered_rate_limit("memory")
async def delete_memory(
    user: Annotated[dict, Depends(get_current_user)],
    memory_id: str = Path(pattern=UUID_PATH_PATTERN),
) -> DeleteMemoryResponse:
    """Soft-delete one memory (hidden from recall, kept for lineage history)."""
    user_id = _require_user_id(user)
    log.set(
        user={"id": user_id},
        memory={"operation": "delete", "memory_id": memory_id},
    )

    success = await memory_engine.forget_memory(user_id, memory_id, USER_DELETED_REASON)

    log.set(memory={"operation": "delete", "memory_id": memory_id, "success": success})
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return DeleteMemoryResponse(success=True, message="Memory deleted successfully")


@router.delete("")
@tiered_rate_limit("memory")
async def clear_all_memories(
    user: Annotated[dict, Depends(get_current_user)],
) -> DeleteMemoryResponse:
    """Hard-wipe the user's entire memory (memories, graph, journal, documents)."""
    user_id = _require_user_id(user)
    log.set(user={"id": user_id}, memory={"operation": "delete_all"})

    deleted = await memory_engine.delete_all(user_id)

    log.set(memory={"operation": "delete_all", "deleted_count": deleted, "success": True})
    return DeleteMemoryResponse(success=True, message=f"Cleared {deleted} memories")
