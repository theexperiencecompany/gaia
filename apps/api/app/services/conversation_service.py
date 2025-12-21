import asyncio
from datetime import datetime, timezone

from app.db.mongodb.collections import conversations_collection
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.utils.tool_data_utils import (
    convert_conversation_messages,
    convert_legacy_tool_data,
)
from bson import ObjectId
from fastapi import HTTPException, status


async def create_conversation_service(
    conversation: ConversationModel, user: dict
) -> dict:
    """
    Create a new conversation.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated"
        )

    created_at = datetime.now(timezone.utc).isoformat()
    conversation_data = {
        "user_id": user_id,
        "conversation_id": conversation.conversation_id,
        "description": conversation.description,
        "is_system_generated": conversation.is_system_generated or False,
        "system_purpose": conversation.system_purpose,
        "is_unread": conversation.is_unread or False,
        "messages": [],
        "createdAt": created_at,
    }

    try:
        insert_result = await conversations_collection.insert_one(conversation_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create conversation: {str(e)}",
        )

    if not insert_result.acknowledged:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation",
        )

    return {
        "conversation_id": conversation.conversation_id,
        "user_id": user_id,
        "createdAt": created_at,
        "detail": "Conversation created successfully",
    }


async def get_conversations(user: dict, page: int = 1, limit: int = 10) -> dict:
    """
    Fetch paginated conversations for the authenticated user, including starred conversations.
    """
    user_id = user["user_id"]

    projection = {
        "_id": 1,
        "user_id": 1,
        "conversation_id": 1,
        "description": 1,
        "starred": 1,
        "is_system_generated": 1,
        "system_purpose": 1,
        "is_unread": 1,
        "createdAt": 1,
        "updatedAt": 1,
    }

    starred_filter = {"user_id": user_id, "starred": True}
    non_starred_filter = {
        "user_id": user_id,
        "$or": [{"starred": {"$exists": False}}, {"starred": False}],
    }
    skip = (page - 1) * limit

    starred_future = (
        conversations_collection.find(starred_filter, projection)
        .sort("createdAt", -1)
        .to_list(None)
    )
    non_starred_count_future = conversations_collection.count_documents(
        non_starred_filter
    )
    non_starred_future = (
        conversations_collection.find(non_starred_filter, projection)
        .sort("createdAt", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )

    (
        starred_conversations,
        non_starred_count,
        non_starred_conversations,
    ) = await asyncio.gather(
        starred_future, non_starred_count_future, non_starred_future
    )

    starred_conversations = _convert_ids(starred_conversations)
    non_starred_conversations = _convert_ids(non_starred_conversations)

    combined_conversations = starred_conversations + non_starred_conversations
    total = len(starred_conversations) + non_starred_count
    total_pages = (
        ((non_starred_count + limit - 1) // limit) if non_starred_count > 0 else 1
    )

    result = {
        "conversations": combined_conversations,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }

    return result


async def get_conversation(conversation_id: str, user: dict) -> dict:
    """
    Fetch a specific conversation by ID.
    """
    user_id = user.get("user_id")
    conversation = await conversations_collection.find_one(
        {"user_id": user_id, "conversation_id": conversation_id}
    )

    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or does not belong to the user",
        )

    conversations = _convert_ids([conversation])

    # Convert legacy tool data to unified format
    return convert_conversation_messages(conversations[0])


async def star_conversation(conversation_id: str, starred: bool, user: dict) -> dict:
    """
    Star or unstar a conversation.
    """
    user_id = user.get("user_id")
    update_result = await conversations_collection.update_one(
        {"user_id": user_id, "conversation_id": conversation_id},
        {"$set": {"starred": starred}, "$currentDate": {"updatedAt": True}},
    )

    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Conversation not found or update failed"
        )

    return {"message": "Conversation updated successfully", "starred": starred}


async def delete_all_conversations(user: dict) -> dict:
    """
    Delete all conversations for the authenticated user.
    """
    user_id = user.get("user_id")
    delete_result = await conversations_collection.delete_many({"user_id": user_id})

    if delete_result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="No conversations found for the user",
        )

    return {"message": "All conversations deleted successfully"}


async def delete_conversation(conversation_id: str, user: dict) -> dict:
    """
    Delete a specific conversation by ID.
    """
    user_id = user.get("user_id")
    delete_result = await conversations_collection.delete_one(
        {"user_id": user_id, "conversation_id": conversation_id}
    )

    if delete_result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or does not belong to the user",
        )

    return {
        "message": "Conversation deleted successfully",
        "conversation_id": conversation_id,
    }


async def update_messages(request: UpdateMessagesRequest, user: dict) -> dict:
    """
    Add messages to an existing conversation, including any file IDs attached to the messages.
    """
    user_id = user.get("user_id")
    conversation_id = request.conversation_id

    messages = []
    for message in request.messages:
        message_dict = message.model_dump(exclude={"loading"})
        # Remove None values to keep the document clean
        message_dict = {k: v for k, v in message_dict.items() if v is not None}
        message_dict.setdefault("message_id", str(ObjectId()))
        messages.append(message_dict)

    update_result = await conversations_collection.update_one(
        {"user_id": user_id, "conversation_id": conversation_id},
        {
            "$push": {"messages": {"$each": messages}},
            "$currentDate": {"updatedAt": True},
        },
    )

    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or does not belong to the user",
        )

    return {
        "conversation_id": conversation_id,
        "message": "Messages updated",
        "modified_count": update_result.modified_count,
        "message_ids": [msg["message_id"] for msg in messages],
    }


async def pin_message(
    conversation_id: str, message_id: str, pinned: bool, user: dict
) -> dict:
    """
    Pin or unpin a message within a conversation.
    """
    user_id = user.get("user_id")
    conversation = await conversations_collection.find_one(
        {"user_id": user_id, "conversation_id": conversation_id}
    )

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation.get("messages", [])
    target_message = next(
        (msg for msg in messages if msg.get("message_id") == message_id), None
    )

    if not target_message:
        raise HTTPException(status_code=404, detail="Message not found in conversation")

    update_result = await conversations_collection.update_one(
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "messages.message_id": message_id,
        },
        {
            "$set": {"messages.$.pinned": pinned},
            "$currentDate": {"updatedAt": True},
        },
    )

    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Message not found or update failed"
        )

    response_message = (
        f"Message with ID {message_id} pinned successfully"
        if pinned
        else f"Message with ID {message_id} unpinned successfully"
    )

    return {"message": response_message, "pinned": pinned}


async def get_starred_messages(user: dict) -> dict:
    """
    Fetch all pinned messages across all conversations for the authenticated user.
    """
    user_id = user.get("user_id")

    results = await conversations_collection.aggregate(
        [
            {"$match": {"user_id": user_id}},
            {"$unwind": "$messages"},
            {"$match": {"messages.pinned": True}},
            {"$project": {"_id": 0, "conversation_id": 1, "message": "$messages"}},
        ]
    ).to_list(None)

    # Convert legacy tool data for each message
    converted_results = []
    for result in results:
        if "message" in result:
            result["message"] = convert_legacy_tool_data(result["message"])
        converted_results.append(result)

    return {"results": converted_results}


async def create_system_conversation(
    user_id: str, description: str, system_purpose: SystemPurpose
) -> dict:
    """
    Create a system-generated conversation with proper flags.

    Args:
        user_id: The user ID
        description: Description of the conversation
        system_purpose: Purpose identifier (e.g., "email_processing", "reminder_processing")

    Returns:
        dict: Created conversation data
    """
    from uuid import uuid4

    conversation_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conversation_data = ConversationModel(
        conversation_id=conversation_id,
        description=description,
        is_system_generated=True,
        system_purpose=system_purpose,
        is_unread=True,
    ).model_dump(exclude_unset=True, exclude_none=True)

    conversation_data["user_id"] = user_id
    conversation_data["messages"] = []
    conversation_data["createdAt"] = created_at

    try:
        insert_result = await conversations_collection.insert_one(conversation_data)
        if not insert_result.acknowledged:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create system conversation",
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create system conversation: {str(e)}",
        )


async def get_or_create_system_conversation(
    user_id: str, system_purpose: SystemPurpose, description: str | None = None
) -> dict:
    """
    Get existing system conversation for a purpose or create a new one.

    Args:
        user_id: The user ID
        system_purpose: Purpose identifier (e.g., "email_processing", "reminder_processing")
        description: Optional description, defaults to purpose-based description

    Returns:
        dict: Existing or newly created system conversation
    """
    # Try to find existing system conversation for this purpose
    existing_conversation = await conversations_collection.find_one(
        {
            "user_id": user_id,
            "is_system_generated": True,
            "system_purpose": system_purpose,
        }
    )

    if existing_conversation:
        existing_conversation["_id"] = str(existing_conversation["_id"])
        return existing_conversation

    # Create new system conversation if none exists
    if not description:
        description_map = {
            "email_processing": "Email Actions & Notifications",
            "reminder_processing": "Reminder Management",
            "task_automation": "Automated Tasks",
            "system_notifications": "System Notifications",
        }
        description = description_map.get(
            system_purpose,
            f"System: {system_purpose.replace('_', ' ').title()}",
        )

    return await create_system_conversation(user_id, description, system_purpose)


async def update_conversation_description(
    conversation_id: str, description: str, user: dict
) -> dict:
    """
    Update the description of a specific conversation.
    """
    user_id = user.get("user_id")
    update_result = await conversations_collection.update_one(
        {"user_id": user_id, "conversation_id": conversation_id},
        {"$set": {"description": description}, "$currentDate": {"updatedAt": True}},
    )

    if update_result.modified_count == 0:
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
    """
    Mark a conversation as read (set is_unread to False).
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated"
        )
    await conversations_collection.update_one(
        {"user_id": user_id, "conversation_id": conversation_id},
        {"$set": {"is_unread": False}, "$currentDate": {"updatedAt": True}},
    )
    return {
        "message": "Conversation marked as read",
        "conversation_id": conversation_id,
    }


async def mark_conversation_as_unread(conversation_id: str, user: dict) -> dict:
    """Mark a conversation as unread."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated"
        )

    await conversations_collection.update_one(
        {"user_id": user_id, "conversation_id": conversation_id},
        {"$set": {"is_unread": True}, "$currentDate": {"updatedAt": True}},
    )
    return {
        "message": "Conversation marked as unread",
        "conversation_id": conversation_id,
    }


def _convert_datetime_to_iso(obj: dict, *fields: str) -> None:
    """Convert datetime fields to ISO format strings in place."""
    for field in fields:
        if field in obj and isinstance(obj[field], datetime):
            obj[field] = obj[field].isoformat()


def _convert_ids(conversations):
    """Convert MongoDB ObjectIds and datetime fields to JSON-serializable formats."""
    for conv in conversations:
        conv["_id"] = str(conv["_id"])
        _convert_datetime_to_iso(conv, "createdAt", "updatedAt")
    return conversations


async def batch_sync_conversations(request: BatchSyncRequest, user: dict) -> dict:
    """
    Batch sync conversations - returns only conversations that have been updated
    since the provided timestamp, including their messages.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated"
        )

    conversation_map = {
        item.conversation_id: item.last_updated for item in request.conversations
    }

    if not conversation_map:
        return {"conversations": []}

    # Build match conditions for each conversation
    match_conditions = []
    for conv_id, last_updated in conversation_map.items():
        condition = {
            "user_id": user_id,
            "conversation_id": conv_id,
        }

        # Only include if updated after the provided timestamp
        if last_updated:
            try:
                last_updated_dt = datetime.fromisoformat(
                    last_updated.replace("Z", "+00:00")
                )
                condition["$or"] = [
                    {"updatedAt": {"$gt": last_updated_dt}},
                    {"updatedAt": {"$exists": False}},
                ]
            except (ValueError, AttributeError):
                # If invalid timestamp, include the conversation
                pass

        match_conditions.append(condition)

    if not match_conditions:
        return {"conversations": []}

    # Use aggregation to efficiently fetch conversations with messages
    pipeline = [
        {"$match": {"$or": match_conditions}},
        {
            "$project": {
                "_id": 0,
                "conversation_id": 1,
                "description": 1,
                "starred": 1,
                "is_system_generated": 1,
                "system_purpose": 1,
                "is_unread": 1,
                "createdAt": 1,
                "updatedAt": 1,
                "messages": 1,
            }
        },
    ]

    conversations = await conversations_collection.aggregate(pipeline).to_list(None)

    # Convert datetime objects to ISO strings
    for conv in conversations:
        _convert_datetime_to_iso(conv, "createdAt", "updatedAt")

        # Convert message timestamps
        if "messages" in conv:
            for message in conv["messages"]:
                _convert_datetime_to_iso(message, "timestamp", "createdAt", "date")

        # Convert legacy tool data
        conv = convert_conversation_messages(conv)

    return {"conversations": conversations}
