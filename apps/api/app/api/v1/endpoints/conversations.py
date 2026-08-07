from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    PinnedUpdate,
    StarredUpdate,
    UpdateDescriptionRequest,
    UpdateMessagesRequest,
)
from app.models.conversation_models import (
    BatchSyncResponse,
    ConversationActionResponse,
    ConversationListResponse,
    CreateConversationResponse,
    DeleteAllConversationsResponse,
    PinMessageResponse,
    PinnedMessagesResponse,
    StarConversationResponse,
    UpdateDescriptionResponse,
    UpdateMessagesResponse,
)
from app.models.user_models import AuthenticatedUser
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
from shared.py.wide_events import log

router = APIRouter()


@router.post("/conversations")
async def create_conversation_endpoint(
    conversation: ConversationModel, user: AuthenticatedUser = Depends(get_current_user)
) -> CreateConversationResponse:
    """
    Create a new conversation.
    """
    log.set(
        user={"id": user["user_id"], "plan": user.get("plan")},
        conversation={"operation": "create", "is_new": True},
    )
    response = await create_conversation_service(conversation, user)
    log.set(
        conversation={
            "operation": "create",
            "is_new": True,
            "id": response.conversation_id,
        }
    )
    return response


@router.get("/conversations")
async def get_conversations_endpoint(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = Query(1, alias="page", ge=1, description="Page number (starting from 1)"),
    limit: int = Query(
        10,
        alias="limit",
        ge=1,
        le=100,
        description="Number of conversations per page (1-100)",
    ),
) -> ConversationListResponse:
    """
    Retrieve paginated conversations for the authenticated user.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "list", "page": page, "limit": limit},
    )
    response = await get_conversations(user, page=page, limit=limit)
    log.set(
        conversation={
            "operation": "list",
            "page": page,
            "limit": limit,
            "total_returned": len(response.conversations),
        }
    )

    return response


@router.post("/conversations/batch-sync")
async def batch_sync_conversations_endpoint(
    request: BatchSyncRequest, user: AuthenticatedUser = Depends(get_current_user)
) -> BatchSyncResponse:
    """
    Batch sync conversations - returns only stale conversations with messages.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "batch_sync"},
    )
    return await batch_sync_conversations(request, user)


@router.get("/conversations/{conversation_id}")
async def get_conversation_endpoint(
    conversation_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> JSONResponse:
    """
    Retrieve a specific conversation by its ID.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "get", "id": conversation_id},
    )
    document = await get_conversation(conversation_id, user)
    # Dumped rather than returned as a response model on purpose:
    # ``ConversationDocument`` is ``extra="allow"`` so a full-document read hands
    # back whatever stray/legacy top-level fields the row carries, and clients
    # (web/mobile/desktop) receive them verbatim today. Declaring a response model
    # here would silently filter those out — a product decision, not a typing fix.
    return JSONResponse(content=document.model_dump(mode="json", exclude={"id"}))


@router.put("/conversations/{conversation_id}/messages")
async def update_messages_endpoint(
    request: UpdateMessagesRequest, user: AuthenticatedUser = Depends(get_current_user)
) -> UpdateMessagesResponse:
    """
    Update the messages of a conversation.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "update_messages"},
    )
    return await update_messages(request, user)


@router.put("/conversations/{conversation_id}/star")
async def star_conversation_endpoint(
    conversation_id: str,
    body: StarredUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
) -> StarConversationResponse:
    """
    Star or unstar a conversation.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={
            "operation": "star",
            "id": conversation_id,
            "is_starred": body.starred,
        },
    )
    return await star_conversation(conversation_id, body.starred, user)


@router.delete("/conversations")
async def delete_all_conversations_endpoint(
    user: AuthenticatedUser = Depends(get_current_user),
) -> DeleteAllConversationsResponse:
    """
    Delete all conversations for the authenticated user.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "delete_all"},
    )
    return await delete_all_conversations(user)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(
    conversation_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> ConversationActionResponse:
    """
    Delete a specific conversation by its ID.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "delete", "id": conversation_id},
    )
    return await delete_conversation(conversation_id, user)


@router.put("/conversations/{conversation_id}/messages/{message_id}/pin")
async def pin_message_endpoint(
    conversation_id: str,
    message_id: str,
    body: PinnedUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
) -> PinMessageResponse:
    """
    Pin or unpin a message within a conversation.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "pin_message", "id": conversation_id},
    )
    return await pin_message(conversation_id, message_id, body.pinned, user)


@router.get("/messages/pinned")
async def get_starred_messages_endpoint(
    user: AuthenticatedUser = Depends(get_current_user),
) -> PinnedMessagesResponse:
    """
    Retrieve all pinned messages across all conversations.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "get_pinned"},
    )
    return await get_starred_messages(user)


@router.put("/conversations/{conversation_id}/description")
async def update_conversation_description_endpoint(
    conversation_id: str,
    body: UpdateDescriptionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> UpdateDescriptionResponse:
    """
    Update the description of a specific conversation.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "update_description", "id": conversation_id},
    )
    return await update_conversation_description(conversation_id, body.description, user)


@router.patch("/conversations/{conversation_id}/read")
async def mark_as_read_endpoint(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConversationActionResponse:
    """
    Mark a conversation as read.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "mark_read", "id": conversation_id},
    )
    return await mark_conversation_as_read(conversation_id, user)


@router.patch("/conversations/{conversation_id}/unread")
async def mark_as_unread_endpoint(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConversationActionResponse:
    """
    Mark a conversation as unread.
    """
    log.set(
        user={"id": user["user_id"]},
        conversation={"operation": "mark_unread", "id": conversation_id},
    )
    return await mark_conversation_as_unread(conversation_id, user)
