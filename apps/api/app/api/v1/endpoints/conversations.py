from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    PinnedUpdate,
    StarredUpdate,
    UpdateDescriptionRequest,
    UpdateMessagesRequest,
)
from app.services.conversation_service import (
    batch_sync_conversations,
    create_conversation_service,
    delete_all_conversations,
    delete_conversation,
    get_conversation,
    get_conversations,
    get_starred_messages,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    pin_message,
    star_conversation,
    update_conversation_description,
    update_messages,
)
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/conversations")
async def create_conversation_endpoint(
    conversation: ConversationModel, user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Create a new conversation.
    """
    response = await create_conversation_service(conversation, user)
    return JSONResponse(content=response)


@router.get("/conversations")
async def get_conversations_endpoint(
    user: dict = Depends(get_current_user),
    page: int = Query(
        1, alias="page", ge=1, description="Page number (starting from 1)"
    ),
    limit: int = Query(
        10,
        alias="limit",
        ge=1,
        le=100,
        description="Number of conversations per page (1-100)",
    ),
) -> JSONResponse:
    """
    Retrieve paginated conversations for the authenticated user.
    """
    response = await get_conversations(user, page=page, limit=limit)

    return JSONResponse(content=response)


@router.post("/conversations/batch-sync")
async def batch_sync_conversations_endpoint(
    request: BatchSyncRequest, user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Batch sync conversations - returns only stale conversations with messages.
    """
    response = await batch_sync_conversations(request, user)
    return JSONResponse(content=response)


@router.get("/conversations/{conversation_id}")
async def get_conversation_endpoint(
    conversation_id: str, user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Retrieve a specific conversation by its ID.
    """
    response = await get_conversation(conversation_id, user)
    return JSONResponse(content=response)


@router.put("/conversations/{conversation_id}/messages")
async def update_messages_endpoint(
    request: UpdateMessagesRequest, user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Update the messages of a conversation.
    """
    response = await update_messages(request, user)
    return JSONResponse(content=response)


@router.put("/conversations/{conversation_id}/star")
async def star_conversation_endpoint(
    conversation_id: str,
    body: StarredUpdate,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Star or unstar a conversation.
    """
    response = await star_conversation(conversation_id, body.starred, user)
    return JSONResponse(content=response)


@router.delete("/conversations")
async def delete_all_conversations_endpoint(
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Delete all conversations for the authenticated user.
    """
    response = await delete_all_conversations(user)
    return JSONResponse(content=response)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(
    conversation_id: str, user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Delete a specific conversation by its ID.
    """
    response = await delete_conversation(conversation_id, user)
    return JSONResponse(content=response)


@router.put("/conversations/{conversation_id}/messages/{message_id}/pin")
async def pin_message_endpoint(
    conversation_id: str,
    message_id: str,
    body: PinnedUpdate,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Pin or unpin a message within a conversation.
    """
    response = await pin_message(conversation_id, message_id, body.pinned, user)
    return JSONResponse(content=response)


@router.get("/messages/pinned")
async def get_starred_messages_endpoint(
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Retrieve all pinned messages across all conversations.
    """
    response = await get_starred_messages(user)
    return JSONResponse(content=response)


@router.put("/conversations/{conversation_id}/description")
async def update_conversation_description_endpoint(
    conversation_id: str,
    body: UpdateDescriptionRequest,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Update the description of a specific conversation.
    """
    response = await update_conversation_description(
        conversation_id, body.description, user
    )
    return JSONResponse(content=response)


@router.patch("/conversations/{conversation_id}/read")
async def mark_as_read_endpoint(
    conversation_id: str,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Mark a conversation as read.
    """
    response = await mark_conversation_as_read(conversation_id, user)
    return JSONResponse(content=response)


@router.patch("/conversations/{conversation_id}/unread")
async def mark_as_unread_endpoint(
    conversation_id: str,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Mark a conversation as unread.
    """
    response = await mark_conversation_as_unread(conversation_id, user)
    return JSONResponse(content=response)
