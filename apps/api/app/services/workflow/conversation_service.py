"""
Workflow conversation service for managing single conversations per workflow.
"""

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, SystemPurpose, UpdateMessagesRequest
from app.services.conversation_service import (
    create_system_conversation,
    update_messages,
)
from shared.py.wide_events import log

# A workflow reuses one conversation across all runs; cap it so the doc can't grow
# past MongoDB's 16MB limit (and fail every run with WriteError 17419).
WORKFLOW_CONVERSATION_MAX_MESSAGES = 50


async def get_or_create_workflow_conversation(
    workflow_id: str, user_id: str, workflow_title: str
) -> dict:
    """
    Get existing workflow conversation or create a new one.
    Uses workflow_id in metadata to identify the conversation.

    Args:
        workflow_id: The workflow ID
        user_id: The user ID
        workflow_title: Title of the workflow for conversation description

    Returns:
        dict: Existing or newly created workflow conversation
    """
    # Reuse the existing workflow conversation if one already exists.
    existing = await conversation_repository.find_workflow_conversation(user_id, workflow_id)
    if existing is not None:
        return {"conversation_id": existing.conversation_id}

    conversation = await create_system_conversation(
        user_id=user_id,
        description=workflow_title,
        system_purpose=SystemPurpose.WORKFLOW_EXECUTION,
    )

    # Tag the new conversation with its workflow binding (source + metadata).
    await conversation_repository.set_workflow_binding(
        conversation["conversation_id"],
        user_id=user_id,
        workflow_id=workflow_id,
        workflow_title=workflow_title,
    )

    return conversation


async def add_workflow_execution_messages(
    conversation_id: str,
    workflow_execution_messages: list[MessageModel],
    user_id: str,
) -> None:
    """
    Add new execution messages to existing workflow conversation.

    Args:
        conversation_id: ID of the workflow conversation
        workflow_execution_messages: List of messages from workflow execution
        user_id: User ID for authorization
    """
    try:
        # Create update request
        messages_request = UpdateMessagesRequest(
            conversation_id=conversation_id, messages=workflow_execution_messages
        )

        user_dict = {"user_id": user_id}
        await update_messages(
            messages_request, user_dict, max_messages=WORKFLOW_CONVERSATION_MAX_MESSAGES
        )

    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Failed to store messages in conversation {conversation_id}: {e!s}"
        )
        raise
