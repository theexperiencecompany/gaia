from datetime import datetime, timezone

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.decorators import tiered_rate_limit
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import (
    MessageDict,
    MessageRequestWithHistory,
    SaveIncompleteConversationRequest,
)
from app.services.chat_service import (
    chat_stream,
)
from app.services.conversation_service import update_messages
from app.utils.chat_utils import create_conversation
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.post("/chat-stream")
@tiered_rate_limit("chat_messages")
async def chat_stream_endpoint(
    body: MessageRequestWithHistory,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tz_info: GET_USER_TZ_TYPE = Depends(get_user_timezone),
) -> StreamingResponse:
    """
    Stream chat messages in real time.
    """

    return StreamingResponse(
        chat_stream(
            body=body,
            user=user,
            background_tasks=background_tasks,
            user_time=tz_info[1],
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/save-incomplete-conversation")
@tiered_rate_limit("chat_messages")
async def save_incomplete_conversation(
    body: SaveIncompleteConversationRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Save incomplete conversation when stream is cancelled.
    """
    conversation_id = body.conversation_id

    # Only create new conversation if conversation_id is None
    if conversation_id is None:
        last_message: MessageDict = {"role": "user", "content": body.message}
        selectedTool = body.selectedTool
        selectedWorkflow = body.selectedWorkflow
        conversation = await create_conversation(
            last_message,
            user=user,
            selectedTool=selectedTool,
            selectedWorkflow=selectedWorkflow,
        )
        conversation_id = conversation.get("conversation_id", "")

    # Save the incomplete conversation immediately (not as background task)
    # Since user expects to see it right away when they navigate/refresh

    # Create user message
    user_message = MessageModel(
        type="user",
        response=body.message,
        date=datetime.now(timezone.utc).isoformat(),
        fileIds=body.fileIds,
        fileData=body.fileData,
        selectedTool=body.selectedTool,
        toolCategory=body.toolCategory,
    )

    # Create bot message with incomplete response
    bot_message = MessageModel(
        type="bot",
        response=body.incomplete_response,
        date=datetime.now(timezone.utc).isoformat(),
        fileIds=body.fileIds,
    )

    # Save immediately instead of background task
    await update_messages(
        UpdateMessagesRequest(
            conversation_id=conversation_id,
            messages=[user_message, bot_message],
        ),
        user=user,
    )

    return {
        "success": True,
        "conversation_id": conversation_id,
    }
