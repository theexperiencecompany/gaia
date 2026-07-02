"""Chat endpoints with Redis-backed background streaming.

The background task publishes chunks to a Redis channel and the HTTP response
subscribes to that channel — so if the client disconnects, the stream still
runs to completion and the conversation lands in MongoDB.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.constants.cache import STREAM_TURN_DEDUP_PREFIX, STREAM_TURN_DEDUP_TTL
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.decorators import tiered_rate_limit
from app.models.chat_models import ConversationSource
from app.models.message_models import MessageRequestWithHistory
from app.services.chat.stream import run_chat_stream_background
from shared.py.wide_events import ChatContext, log

# asyncio.create_task only keeps a weakref; without this set the task can be GC'd mid-flight.
_background_tasks: set[asyncio.Task] = set()

_USER_ID_REQUIRED = "user_id is required"
_DUPLICATE_TURN = "duplicate turn_id: this send was already accepted"
_SSE_MEDIA_TYPE = "text/event-stream"
_CLIENT_TYPE_HEADER = "X-Client-Type"

router = APIRouter()


def _resolve_source(request: Request) -> str:
    """Map the client-type header to a conversation source.

    Only the desktop app is trusted to claim a non-web source — it unlocks
    desktop-executed tools, which are useless (harmless) anywhere else.
    """
    client_type = request.headers.get(_CLIENT_TYPE_HEADER, "").strip().lower()
    if client_type == ConversationSource.DESKTOP.value:
        return ConversationSource.DESKTOP.value
    return ConversationSource.WEB.value


def _build_chat_context(
    body: MessageRequestWithHistory,
    conversation_id: str,
    stream_id: str,
) -> ChatContext:
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
    stream_id: str, request: Request, last_event_id: str | None = None
) -> AsyncGenerator[str, None]:
    """Forward the stream's event log to the client, following live.

    The log replays from ``last_event_id`` (or the beginning), so this can be
    attached at any point in the turn's lifetime without losing frames.
    """
    if not redis_cache.redis:
        log.error(f"{LogTag.CHAT} Redis unavailable for stream {stream_id}")
        yield "data: [STREAM_ERROR]\n\n"
        return

    try:
        async for chunk in stream_manager.subscribe_stream(stream_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                log.info(
                    f"{LogTag.CHAT} Client disconnected, stream {stream_id} continues in background"
                )
                break
            yield chunk
    except asyncio.CancelledError:
        log.info(f"{LogTag.CHAT} Stream {stream_id}: client connection cancelled")
    except Exception as e:
        log.error(f"{LogTag.CHAT} Error streaming to client: {e}")


@router.post("/chat-stream")
@tiered_rate_limit("chat_messages")
async def chat_stream_endpoint(
    request: Request,
    body: MessageRequestWithHistory,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
    home_timezone: Annotated[str, Depends(get_user_timezone_from_preferences)],
) -> StreamingResponse:
    """Stream a chat turn. Continues in the background if the client disconnects."""
    stream_id = str(uuid4())
    conversation_id = body.conversation_id or str(uuid4())
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_USER_ID_REQUIRED,
        )
    # Seed the agent's home zone (DB-resolved, browser-header-healed) so its
    # "now" and schedule defaults run in the user's real zone, not stored UTC.
    user = {**user, "timezone": home_timezone}
    log.set(
        user={"id": user_id},
        chat=_build_chat_context(body, conversation_id, stream_id),
        user_message_length=len(body.messages[-1]["content"]) if body.messages else 0,
        selected_tool=body.selectedTool,
    )

    # Idempotency: the client stamps each SEND with a turn_id that survives its
    # retries. First claim wins atomically; a duplicate POST gets a 409 instead
    # of persisting the same user+bot message pair twice.
    if body.turn_id and redis_cache.redis:
        claimed = await redis_cache.redis.set(
            f"{STREAM_TURN_DEDUP_PREFIX}{user_id}:{body.turn_id}",
            stream_id,
            nx=True,
            ex=STREAM_TURN_DEDUP_TTL,
        )
        if not claimed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_DUPLICATE_TURN,
            )

    await stream_manager.start_stream(
        stream_id=stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    task = asyncio.create_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=body,
            user=user,
            conversation_id=conversation_id,
            source=_resolve_source(request),
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Don't set Access-Control-Allow-Origin here — CORSMiddleware echoes the
    # request Origin per-request against the allowlist; hardcoding it would
    # pin a single origin and break the desktop app + alternate domains.
    return StreamingResponse(
        _stream_from_redis(stream_id, request),
        media_type=_SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Stream-Id": stream_id,
        },
    )


@router.post("/cancel-stream/{stream_id}")
async def cancel_stream_endpoint(
    stream_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Cancel a running stream owned by the requesting user."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_USER_ID_REQUIRED,
        )
    log.set(user={"id": user_id}, chat={"stream_id": stream_id})

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
    log.info(f"{LogTag.CHAT} Cancel stream request: stream_id={stream_id}, success={success}")

    return {
        "success": success,
        "stream_id": stream_id,
    }


@router.get("/stream/{stream_id}")
async def subscribe_executor_stream(
    stream_id: str,
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
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
            detail=_USER_ID_REQUIRED,
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
        log.info(f"{LogTag.CHAT} Executor stream {stream_id} already complete, returning [DONE]")

        async def _already_done() -> AsyncGenerator[str, None]:
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _already_done(),
            media_type=_SSE_MEDIA_TYPE,
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    log.info(f"{LogTag.CHAT} Client subscribed to executor stream {stream_id}")

    return StreamingResponse(
        _stream_from_redis(stream_id, request, last_event_id=request.headers.get("Last-Event-ID")),
        media_type=_SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/conversations/{conversation_id}/active-stream")
async def get_active_stream(
    conversation_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Stream id of the conversation's in-flight chat turn, if any.

    Lets a reloaded client rediscover a live turn and re-attach via
    ``GET /stream/{stream_id}`` — the event log replays everything missed.
    Returns ``{"stream_id": null}`` when nothing is streaming (or the turn
    already completed/cancelled), so the client treats absence as normal.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_USER_ID_REQUIRED,
        )

    stream_id = await stream_manager.get_active_stream_id(user_id, conversation_id)
    if not stream_id:
        return {"stream_id": None}

    progress = await stream_manager.get_progress(stream_id)
    if not progress or progress.get("is_complete") or progress.get("is_cancelled"):
        return {"stream_id": None}

    return {"stream_id": stream_id}
