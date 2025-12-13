"""Memory management API routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import tiered_rate_limit
from app.models.memory_models import (
    CreateMemoryRequest,
    CreateMemoryResponse,
    DeleteMemoryResponse,
    MemorySearchResult,
)
from app.services.memory_service import memory_service

router = APIRouter()


@router.get("", response_model=MemorySearchResult)
async def get_all_memories(
    user: dict = Depends(get_current_user),
):
    """
    Get all memories for the current user.

    Args:
        user: Current authenticated user

    Returns:
        MemorySearchResult with all memories
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    result = await memory_service.get_all_memories(user_id=user_id)

    return result


@router.post("", response_model=CreateMemoryResponse)
@tiered_rate_limit("memory")
async def create_memory(
    request: CreateMemoryRequest,
    user: dict = Depends(get_current_user),
):
    """
    Create a new memory for the current user.

    Args:
        request: Memory creation request
        user: Current authenticated user

    Returns:
        CreateMemoryResponse with success status
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    memory_entry = await memory_service.store_memory(
        message=request.content,
        user_id=user_id,
        metadata=request.metadata,
        async_mode=False,
    )

    if memory_entry:
        return CreateMemoryResponse(
            success=True,
            memory_id=memory_entry.id,
            message="Memory created successfully",
        )
    else:
        return CreateMemoryResponse(success=False, message="Failed to create memory")


@router.delete("/{memory_id}", response_model=DeleteMemoryResponse)
@tiered_rate_limit("memory")
async def delete_memory(
    memory_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Delete a specific memory.

    Args:
        memory_id: ID of the memory to delete
        user: Current authenticated user

    Returns:
        DeleteMemoryResponse with success status
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    success = await memory_service.delete_memory(memory_id=memory_id, user_id=user_id)

    if success:
        return DeleteMemoryResponse(success=True, message="Memory deleted successfully")
    else:
        return DeleteMemoryResponse(success=False, message="Failed to delete memory")


@router.delete("", response_model=DeleteMemoryResponse)
@tiered_rate_limit("memory")
async def clear_all_memories(
    user: dict = Depends(get_current_user),
):
    """
    Clear all memories for the current user.

    Args:
        user: Current authenticated user

    Returns:
        DeleteMemoryResponse with success status
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        # Use the new delete_all_memories method from v2 API
        success = await memory_service.delete_all_memories(user_id=user_id)

        if success:
            return DeleteMemoryResponse(
                success=True, message="All memories cleared successfully"
            )
        else:
            return DeleteMemoryResponse(
                success=False, message="Failed to clear memories"
            )
    except Exception as e:
        return DeleteMemoryResponse(
            success=False, message=f"Failed to clear memories: {str(e)}"
        )
