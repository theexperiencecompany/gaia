from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.client_type import request_client_source
from app.constants.chat import CONVERSATION_READ_LIMIT
from app.constants.general import MAX_PAGE_NUMBER
from app.core.shutdown_signal import shutdown_requested
from app.decorators import tiered_rate_limit
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    PinnedUpdate,
    StarredUpdate,
    UpdateDescriptionRequest,
)
from app.models.conversation_models import (
    BatchSyncResponse,
    ConversationActionResponse,
    ConversationEntriesPage,
    ConversationListResponse,
    CreateConversationResponse,
    DeleteAllConversationsResponse,
    LoadedConversation,
    PinMessageResponse,
    PinnedMessagesResponse,
    StarConversationResponse,
    UpdateDescriptionResponse,
)
from app.models.conversation_send_models import (
    BargeInAccepted,
    BargeInRequest,
    ConversationEvent,
    MessageAccepted,
    SendMessageRequest,
)
from app.models.user_models import AuthenticatedUser
from app.models.work_cancel_models import ConversationStopResponse
from app.services.conversation.event_stream import event_lines
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.send import submit_barge_in, submit_message
from app.services.conversation_service import (
    batch_sync_conversations,
    create_conversation_service,
    delete_all_conversations,
    delete_conversation,
    get_conversation,
    get_conversations,
    get_entries_before,
    get_starred_messages,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    pin_message,
    require_owned_conversation,
    star_conversation,
    update_conversation_description,
)
from app.services.conversation_stop_service import press_stop
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
        user={"id": user.user_id},
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
    page: int = Query(
        1,
        alias="page",
        ge=1,
        le=MAX_PAGE_NUMBER,
        description="Page number (starting from 1)",
    ),
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
        user={"id": user.user_id},
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
        user={"id": user.user_id},
        conversation={"operation": "batch_sync"},
    )
    return await batch_sync_conversations(request, user)


@router.get("/conversations/{conversation_id}", response_model_exclude={"id"})
async def get_conversation_endpoint(
    conversation_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> LoadedConversation:
    """
    Retrieve a conversation with the newest page of its log, as the events stream's entries.

    The head's own fields: ``ConversationDocument`` is ``extra="allow"``,
    so stray/legacy top-level fields the row carries still reach the client
    verbatim, while the declared fields give the schema its shape.
    """
    log.set(
        user={"id": user.user_id},
        conversation={"operation": "get", "id": conversation_id},
    )
    return await get_conversation(conversation_id, user)


@router.get("/conversations/{conversation_id}/entries")
async def get_entries_before_endpoint(
    conversation_id: str,
    before_seq: int = Query(ge=1, description="Return entries with a seq below this one"),
    limit: int = Query(
        default=CONVERSATION_READ_LIMIT, ge=1, le=CONVERSATION_READ_LIMIT, description="Page size"
    ),
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConversationEntriesPage:
    """Page a conversation's log back from before_seq, never starting inside an open reply, task or approval."""
    log.set(
        user={"id": user.user_id},
        conversation={"operation": "entries_before", "id": conversation_id},
    )
    page = await get_entries_before(conversation_id, user, before_seq=before_seq, limit=limit)
    log.set_ns("conversation", entries=len(page.entries), has_older=page.has_older)
    return page


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
@tiered_rate_limit("chat_messages")
async def send_message_endpoint(
    request: Request,
    conversation_id: str,
    body: SendMessageRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> MessageAccepted:
    """Accept a message into a conversation the step runs; its reply arrives on the events stream."""
    log.set(
        user={"id": user.user_id},
        conversation={"operation": "send", "id": conversation_id},
    )
    accepted = await submit_message(conversation_id, user, body, request_client_source(request))
    log.set_ns("conversation", message_id=accepted.message_id, seq=accepted.seq)
    return accepted


@router.post("/conversations/{conversation_id}/barge-in", status_code=status.HTTP_202_ACCEPTED)
async def barge_in_endpoint(
    conversation_id: str,
    body: BargeInRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> BargeInAccepted:
    """Record that the user spoke over a voice reply and how much of it they heard."""
    log.set(
        user={"id": user.user_id},
        conversation={"operation": "barge_in", "id": conversation_id},
    )
    await require_owned_conversation(conversation_id, user.user_id)
    return await submit_barge_in(conversation_id, user, body)


@router.get(
    "/conversations/{conversation_id}/events",
    response_class=StreamingResponse,
    responses={200: {"model": ConversationEvent, "content": {"text/event-stream": {}}}},
)
async def conversation_events_endpoint(
    request: Request,
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the conversation's screen as SSE: the newest page, then patches and live deltas."""
    log.set(
        user={"id": user.user_id},
        conversation={"operation": "events", "id": conversation_id},
    )
    await require_owned_conversation(conversation_id, user.user_id)
    lines = event_lines(
        runtime_ports().log,
        conversation_id,
        user.user_id,
        request.is_disconnected,
        shutdown_requested(),
    )
    return StreamingResponse(
        lines,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        user={"id": user.user_id},
        conversation={
            "operation": "star",
            "id": conversation_id,
            "is_starred": body.starred,
        },
    )
    return await star_conversation(conversation_id, body.starred, user)


@router.post("/conversations/{conversation_id}/stop")
async def stop_conversation_endpoint(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConversationStopResponse:
    """Stop everything running for a conversation: its reply in flight, executor, subagents, approvals and browser job."""
    log.set(
        user={"id": user.user_id},
        conversation={"operation": "stop", "id": conversation_id},
    )
    await require_owned_conversation(conversation_id, user.user_id)
    result = await press_stop(conversation_id, user.user_id, None)
    log.set_ns("conversation", stopped_work=result.work.stopped_anything)
    return result


@router.delete("/conversations")
async def delete_all_conversations_endpoint(
    user: AuthenticatedUser = Depends(get_current_user),
) -> DeleteAllConversationsResponse:
    """
    Delete all conversations for the authenticated user.
    """
    log.set(
        user={"id": user.user_id},
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
        user={"id": user.user_id},
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
        user={"id": user.user_id},
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
        user={"id": user.user_id},
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
        user={"id": user.user_id},
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
        user={"id": user.user_id},
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
        user={"id": user.user_id},
        conversation={"operation": "mark_unread", "id": conversation_id},
    )
    return await mark_conversation_as_unread(conversation_id, user)
