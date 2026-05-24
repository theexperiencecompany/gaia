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
from collections.abc import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.decorators import tiered_rate_limit
from app.models.message_models import MessageRequestWithHistory
from app.services.chat_service import run_chat_stream_background
from shared.py.wide_events import ChatContext, log

# Set to hold references to background tasks to prevent garbage collection
_background_tasks: set[asyncio.Task] = set()

router = APIRouter()


def _build_chat_context(
    body: MessageRequestWithHistory,
    conversation_id: str,
    stream_id: str,
) -> ChatContext:
    """Build a ChatContext from the request body."""
    return ChatContext(
        conversation_id=conversation_id,
        stream_id=stream_id,
        is_new_conversation=body.conversation_id is None,
        message_count=len(body.messages) if body.messages else 0,
        has_files=bool(body.fileIds or body.fileData),
        file_count=len(body.fileIds or []) + len(body.fileData or []),
        tool_category=body.toolCategory,
        has_reply=bool(body.replyToMessage),
        has_calendar_event=bool(body.selectedCalendarEvent),
        selected_workflow_id=body.selectedWorkflow.id if body.selectedWorkflow else None,
    )


async def _stream_from_redis(
    stream_id: str, request: Request, start_event: asyncio.Event | None = None
) -> AsyncGenerator[str, None]:
    """Subscribe to Redis channel and forward chunks to HTTP response."""
    if not redis_cache.redis:
        log.error(f"Redis unavailable for stream {stream_id}")
        if start_event and not start_event.is_set():
            start_event.set()
        yield "data: [STREAM_ERROR]\n\n"
        return

    try:
        async for chunk in stream_manager.subscribe_stream(stream_id, start_event=start_event):
            if await request.is_disconnected():
                log.info(f"Client disconnected, stream {stream_id} continues in background")
                break
            yield chunk
    except asyncio.CancelledError:
        # Client disconnected - stream continues in background
        log.info(f"Stream {stream_id}: client connection cancelled")
    except Exception as e:
        log.error(f"Error streaming to client: {e}")
    finally:
        if start_event and not start_event.is_set():
            start_event.set()


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
    stream_id = str(uuid4())
    conversation_id = body.conversation_id or str(uuid4())
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required",
        )
    log.set(
        user={"id": user_id},
        chat=_build_chat_context(body, conversation_id, stream_id),
        user_message_length=len(body.messages[-1]["content"]) if body.messages else 0,
        selected_tool=body.selectedTool,
    )

    # Initialize stream tracking in Redis
    await stream_manager.start_stream(
        stream_id=stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    # Start background streaming task (continues even if client disconnects)
    start_event = asyncio.Event()
    task = asyncio.create_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=body,
            user=user,
            user_time=tz_info[1],
            conversation_id=conversation_id,
            source="web",
            start_event=start_event,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # CORS is intentionally NOT set here — CORSMiddleware echoes the request's
    # Origin against the allowlist in get_allowed_origins() (FRONTEND_URL, the
    # production heygaia.* domains, and the localhost ports the desktop app
    # uses). Hardcoding a single origin here would break desktop and any
    # additional allowed domains. Mobile and bots use native HTTP / a separate
    # /api/v1/bot/chat-stream endpoint and are not subject to browser CORS.
    return StreamingResponse(
        _stream_from_redis(stream_id, request, start_event=start_event),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
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
    Verifies that the requesting user owns the stream before cancelling.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required",
        )
    log.set(user={"id": user_id}, chat={"stream_id": stream_id})

    # Verify stream ownership
    progress = await stream_manager.get_progress(stream_id)
    if not progress:
        return {
            "success": False,
            "stream_id": stream_id,
            "error": "Stream not found",
        }

    if progress.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this stream",
        )

    success = await stream_manager.cancel_stream(stream_id)
    log.info(f"Cancel stream request: stream_id={stream_id}, success={success}")

    return {
        "success": success,
        "stream_id": stream_id,
    }


@router.get("/stream/{stream_id}")
async def subscribe_executor_stream(
    stream_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """
    Subscribe to a background executor SSE stream by stream_id.

    Used by the frontend to receive live tool events for queued executor tasks.
    The stream_id is delivered via the `executor.stream_started` WebSocket event.
    Verifies stream ownership before allowing subscription.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id is required",
        )

    progress = await stream_manager.get_progress(stream_id)
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stream not found",
        )

    if progress.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to subscribe to this stream",
        )

    log.set(user={"id": user_id}, chat={"stream_id": stream_id})

    # Race condition: executor finished before frontend subscribed.
    # Return [DONE] immediately so the client closes cleanly.
    if progress.get("is_complete"):
        log.info(f"Executor stream {stream_id} already complete, returning [DONE]")

        async def _already_done() -> AsyncGenerator[str, None]:
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _already_done(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    log.info(f"Client subscribed to executor stream {stream_id}")

    return StreamingResponse(
        _stream_from_redis(stream_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
