"""
Chat endpoints with Redis-backed background streaming.

The streaming architecture is decoupled from HTTP request lifecycle:
1. Endpoint starts background task for LangGraph execution
2. Background task publishes chunks to Redis channel
3. Endpoint subscribes to channel and forwards to HTTP response
4. If client disconnects, stream continues in background
5. Conversation is always saved to MongoDB on completion
"""

import asyncio
from uuid import uuid4

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.config.loggers import chat_logger as logger
from app.core.stream_manager import stream_manager
from app.decorators import tiered_rate_limit
from app.models.message_models import MessageRequestWithHistory
from app.services.chat_service import run_chat_stream_background
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.post("/chat-stream")
@tiered_rate_limit("chat_messages")
async def chat_stream_endpoint(
    request: Request,
    body: MessageRequestWithHistory,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tz_info: GET_USER_TZ_TYPE = Depends(get_user_timezone),
) -> StreamingResponse:
    """
    Stream chat messages with background execution.

    The streaming runs in a background task independent of the HTTP connection.
    If the client disconnects, the stream continues and saves to MongoDB.
    """
    # Generate unique stream ID and conversation ID
    stream_id = str(uuid4())
    conversation_id = body.conversation_id or str(uuid4())
    user_id = user.get("user_id")
    if not user_id:
        raise ValueError("user_id is required")

    # Initialize stream tracking in Redis
    await stream_manager.start_stream(
        stream_id=stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # Start background streaming task (continues even if client disconnects)
    asyncio.create_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=body,
            user=user,
            user_time=tz_info[1],
            conversation_id=conversation_id,
        )
    )

    async def stream_from_redis():
        """Subscribe to Redis channel and forward chunks to HTTP response."""
        try:
            async for chunk in stream_manager.subscribe_stream(stream_id):
                # Check if client disconnected
                if await request.is_disconnected():
                    logger.info(
                        f"Client disconnected, stream {stream_id} continues in background"
                    )
                    break
                yield chunk
        except asyncio.CancelledError:
            # Client disconnected - stream continues in background
            logger.info(f"Stream {stream_id}: client connection cancelled")
        except Exception as e:
            logger.error(f"Error streaming to client: {e}")

    return StreamingResponse(
        stream_from_redis(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Access-Control-Allow-Origin": "*",
            "X-Stream-Id": stream_id,  # Send stream ID for cancellation
        },
    )


@router.post("/cancel-stream/{stream_id}")
async def cancel_stream_endpoint(
    stream_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Cancel a running stream.

    Called from frontend when user clicks the Stop button.
    """
    success = await stream_manager.cancel_stream(stream_id)
    logger.info(f"Cancel stream request: stream_id={stream_id}, success={success}")

    return {
        "success": success,
        "stream_id": stream_id,
    }
