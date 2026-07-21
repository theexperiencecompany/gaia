import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from fastapi import HTTPException, status
from psycopg_pool import AsyncConnectionPool

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.models.conversation_models import ConversationDocument
from app.services.storage import JuiceFSUnavailable, delete_session_dir
from shared.py.wide_events import log

# The projected fields a batch-sync row returns (matches the pre-repository
# aggregation): the conversation summary plus its full message history, minus the
# internal user_id/_id/metadata.
_SYNC_FIELDS = {
    "conversation_id",
    "description",
    "starred",
    "is_system_generated",
    "is_onboarding_conversation",
    "system_purpose",
    "is_unread",
    "createdAt",
    "updatedAt",
    "messages",
}


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards so a conversation_id matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _delete_checkpoint_threads(conversation_id: str) -> None:
    """Delete the LangGraph Postgres checkpoint threads for a conversation.

    A conversation owns its base thread (`thread_id == conversation_id`) plus
    derived threads that embed the id — `executor_<conv>`,
    `<integration>_executor_<conv>_<runhex>`, `workflow_<conv>`, and nested
    combinations. Rather than enumerate the (dynamic, per-integration) prefixes,
    match every thread whose id contains the conversation_id and delete each via
    the saver. Best-effort: the nightly `prune_checkpoint_versions` orphan sweep
    is the backstop if this fails, so a failure here never fails the API call.
    """

    manager = await get_checkpointer_manager()
    checkpointer = manager.get_checkpointer()
    # `CheckpointerManager.pool` is populated by `setup()` before the provider
    # resolves; get_checkpointer() above already asserts the manager is ready.
    pool = cast(AsyncConnectionPool, manager.pool)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s ESCAPE '\\'",
            (f"%{_like_escape(conversation_id)}%",),
        )
        thread_ids = [row[0] for row in await cur.fetchall()]
    for thread_id in thread_ids:
        await checkpointer.adelete_thread(thread_id)


async def _cleanup_checkpoint_threads(conversation_id: str) -> None:
    """Best-effort wrapper around `_delete_checkpoint_threads` for delete paths.

    Mirrors the session-dir cleanup contract: a failure is logged and swallowed
    so a Postgres hiccup never fails an already-committed conversation delete;
    the nightly orphan sweep cleans up anything left behind.
    """
    try:
        await _delete_checkpoint_threads(conversation_id)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} checkpoint thread cleanup failed", conv=conversation_id, error=str(e)
        )


async def create_conversation_service(conversation: ConversationModel, user: dict) -> dict:
    """Create a new conversation."""
    user_id = user.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    created_at = datetime.now(UTC).isoformat()
    document = ConversationDocument(
        user_id=user_id,
        conversation_id=conversation.conversation_id,
        description=conversation.description,
        is_system_generated=conversation.is_system_generated or False,
        system_purpose=conversation.system_purpose,
        is_unread=conversation.is_unread or False,
        is_onboarding_demo=conversation.is_onboarding_demo,
        source=conversation.source,
        createdAt=created_at,
    )

    try:
        await conversation_repository.create(document)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create conversation: {e!s}",
        )

    return {
        "conversation_id": conversation.conversation_id,
        "user_id": user_id,
        "createdAt": created_at,
        "detail": "Conversation created successfully",
    }


async def get_conversations(user: dict, page: int = 1, limit: int = 10) -> dict:
    """Fetch paginated conversations for the authenticated user, starred first.

    Bot-originated conversations are excluded from the web list (reachable by
    direct URL); the repository applies that source filter.
    """
    user_id = user["user_id"]
    skip = (page - 1) * limit

    starred, non_starred, non_starred_count = await asyncio.gather(
        conversation_repository.list_starred_summaries(user_id),
        conversation_repository.list_active_summaries(user_id, skip=skip, limit=limit),
        conversation_repository.count_active(user_id),
    )

    combined = [summary.model_dump(mode="json") for summary in (*starred, *non_starred)]
    total = len(starred) + non_starred_count
    total_pages = ((non_starred_count + limit - 1) // limit) if non_starred_count > 0 else 1

    return {
        "conversations": combined,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


async def get_conversation(conversation_id: str, user: dict) -> dict:
    """Fetch a specific conversation by ID (messages already normalized on read)."""
    user_id = user.get("user_id", "")
    document = await conversation_repository.get(conversation_id, user_id=user_id)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or does not belong to the user",
        )
    return document.model_dump(mode="json", exclude={"id"})


async def star_conversation(conversation_id: str, starred: bool, user: dict) -> dict:
    """Star or unstar a conversation."""
    user_id = user.get("user_id", "")
    updated = await conversation_repository.set_starred(
        conversation_id, user_id=user_id, starred=starred
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found or update failed")
    return {"message": "Conversation updated successfully", "starred": starred}


async def delete_all_conversations(user: dict) -> dict:
    """Delete all conversations for the authenticated user."""
    user_id = user.get("user_id", "")
    # The repository returns the deleted ids so their (non-user-scoped) checkpoint
    # threads can be cleaned up afterwards.
    conversation_ids = await conversation_repository.delete_all_for_user(user_id)

    if not conversation_ids:
        raise HTTPException(status_code=404, detail="No conversations found for the user")

    for conversation_id in conversation_ids:
        await _cleanup_checkpoint_threads(conversation_id)

    return {"message": "All conversations deleted successfully"}


async def delete_conversation(conversation_id: str, user: dict) -> dict:
    """Delete a specific conversation by ID."""
    user_id = user.get("user_id", "")
    deleted = await conversation_repository.delete(conversation_id, user_id=user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or does not belong to the user",
        )

    # Best-effort cleanup of the on-disk session dir. Mongo delete already
    # succeeded; the ARQ prune task is the backstop if this fails.
    if user_id:
        try:
            await delete_session_dir(user_id, conversation_id)
        except JuiceFSUnavailable as e:
            log.warning("[conversation] juicefs cleanup skipped", error=str(e))
        except Exception as e:
            log.warning("[conversation] session dir cleanup failed", error=str(e))

    await _cleanup_checkpoint_threads(conversation_id)

    return {
        "message": "Conversation deleted successfully",
        "conversation_id": conversation_id,
    }


async def update_messages(
    request: UpdateMessagesRequest, user: dict, max_messages: int | None = None
) -> dict:
    """Append messages to a conversation.

    ``max_messages`` caps stored history to the most recent N (via ``$slice``) so
    per-workflow threads can't outgrow MongoDB's 16MB document limit.
    """
    user_id = user.get("user_id", "")
    message_ids = await conversation_repository.append_messages(
        request.conversation_id,
        user_id=user_id,
        messages=request.messages,
        max_messages=max_messages,
    )

    if message_ids is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or does not belong to the user",
        )

    return {
        "conversation_id": request.conversation_id,
        "message": "Messages updated",
        "modified_count": 1,
        "message_ids": message_ids,
    }


async def pin_message(conversation_id: str, message_id: str, pinned: bool, user: dict) -> dict:
    """Pin or unpin a message within a conversation."""
    user_id = user.get("user_id", "")
    document = await conversation_repository.get(conversation_id, user_id=user_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not any(message.message_id == message_id for message in document.messages):
        raise HTTPException(status_code=404, detail="Message not found in conversation")

    updated = await conversation_repository.set_message_pinned(
        conversation_id, user_id=user_id, message_id=message_id, pinned=pinned
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found or update failed")

    response_message = (
        f"Message with ID {message_id} pinned successfully"
        if pinned
        else f"Message with ID {message_id} unpinned successfully"
    )
    return {"message": response_message, "pinned": pinned}


async def get_starred_messages(user: dict) -> dict:
    """Fetch all pinned messages across all conversations for the authenticated user."""
    user_id = user.get("user_id", "")
    hits = await conversation_repository.list_pinned_messages(user_id)
    return {"results": [hit.model_dump(mode="json") for hit in hits]}


async def create_system_conversation(
    user_id: str, description: str, system_purpose: SystemPurpose
) -> dict:
    """Create a system-generated conversation with proper flags."""
    conversation_id = str(uuid4())
    created_at = datetime.now(UTC).isoformat()

    document = ConversationDocument(
        user_id=user_id,
        conversation_id=conversation_id,
        description=description,
        is_system_generated=True,
        system_purpose=system_purpose,
        is_unread=True,
        createdAt=created_at,
    )

    try:
        await conversation_repository.create(document)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create system conversation: {e!s}",
        )

    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "description": description,
        "is_system_generated": True,
        "system_purpose": system_purpose,
        "createdAt": created_at,
        "detail": "System conversation created successfully",
    }


async def update_conversation_description(
    conversation_id: str, description: str, user: dict
) -> dict:
    """Update the description of a specific conversation."""
    user_id = user.get("user_id", "")
    updated = await conversation_repository.set_description(
        conversation_id, user_id=user_id, description=description
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or description not updated",
        )

    return {
        "message": "Conversation description updated successfully",
        "conversation_id": conversation_id,
        "description": description,
    }


async def mark_conversation_as_read(conversation_id: str, user: dict) -> dict:
    """Mark a conversation as read (set is_unread to False)."""
    user_id = user.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")
    await conversation_repository.set_unread(conversation_id, user_id=user_id, unread=False)
    return {
        "message": "Conversation marked as read",
        "conversation_id": conversation_id,
    }


async def mark_conversation_as_unread(conversation_id: str, user: dict) -> dict:
    """Mark a conversation as unread."""
    user_id = user.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    updated = await conversation_repository.set_unread(
        conversation_id, user_id=user_id, unread=True
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or update failed",
        )

    return {
        "message": "Conversation marked as unread",
        "conversation_id": conversation_id,
    }


async def batch_sync_conversations(request: BatchSyncRequest, user: dict) -> dict:
    """Return only conversations updated since the client's last-seen timestamp,
    including their messages and the stream id of an in-flight turn
    (``active_stream_id``) so a reloaded client can re-attach without a separate
    discovery request.
    """
    user_id = user.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    if not request.conversations:
        return {"conversations": []}

    documents = await conversation_repository.find_updated_since(user_id, request.conversations)

    conversations = []
    for document in documents:
        row = document.model_dump(mode="json", include=_SYNC_FIELDS)
        row["active_stream_id"] = await stream_manager.get_resumable_stream_id(
            user_id, document.conversation_id
        )
        conversations.append(row)

    return {"conversations": conversations}
