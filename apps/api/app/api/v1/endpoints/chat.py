"""Chat endpoints with Redis-backed background streaming.

The background task publishes chunks to a Redis channel and the HTTP response
subscribes to that channel — so if the client disconnects, the stream still
runs to completion and the conversation lands in MongoDB.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_id,
    get_user_timezone_from_preferences,
)
from app.constants.cache import STREAM_TURN_DEDUP_PREFIX, STREAM_TURN_DEDUP_TTL
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.decorators import enforce_daily_cost_budget, tiered_rate_limit
from app.models.chat_models import CancelStreamResponse, ConversationSource
from app.models.message_models import MessageRequestWithHistory
from app.models.stream_events import ErrorFrame
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.chat.stream import run_chat_stream_background
from app.utils.agent_utils import format_sse_data
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import ChatContext, get_trace_id, log, log_context

_USER_ID_REQUIRED = "user_id is required"
_DUPLICATE_TURN = "duplicate turn_id: this send was already accepted"
_SSE_MEDIA_TYPE = "text/event-stream"
_DELIVERY_FAILED = "The connection to the server was lost before this response finished."
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

    The body runs while the response streams — after the request's
    ``http_request`` event has emitted — so it needs its own boundary or the
    delivery outcome (disconnects, delivery errors) is silently discarded.
    The generator body inherits the request's context, so ``get_trace_id()``
    here still returns the request's trace_id (verified against
    ``LoggingMiddleware`` + ``StreamingResponse``).
    """
    async with log_context("sse_delivery", trace_id=get_trace_id() or None, stream_id=stream_id):
        if not redis_cache.redis:
            log.error(f"{LogTag.CHAT} Redis unavailable for stream", stream_id=stream_id)
            yield "data: [STREAM_ERROR]\n\n"
            return

        try:
            async for chunk in stream_manager.subscribe_stream(
                stream_id, last_event_id=last_event_id
            ):
                if await request.is_disconnected():
                    log.set(client_disconnected=True)
                    log.info(
                        f"{LogTag.CHAT} Client disconnected, stream continues in background",
                        stream_id=stream_id,
                    )
                    break
                yield chunk
        except asyncio.CancelledError:
            # Client disconnected mid-stream — expected, not an error. The
            # background LangGraph task keeps running and persists the result.
            log.set(client_disconnected=True)
            log.info(f"{LogTag.CHAT} Client connection cancelled", stream_id=stream_id)
            raise
        except Exception as e:
            log.error(
                f"{LogTag.CHAT} Error streaming to client",
                stream_id=stream_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            # Closing silently is indistinguishable from a finished turn, so the
            # client would render a truncated answer as complete.
            yield format_sse_data(ErrorFrame(error=_DELIVERY_FAILED).model_dump())


@router.post("/chat-stream")
@tiered_rate_limit("chat_messages")
async def chat_stream_endpoint(
    request: Request,
    body: MessageRequestWithHistory,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
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
    # Cost wall: the decorator above caps how MANY messages; this caps how
    # EXPENSIVE they were. 429s before any stream work when the day's LLM
    # spend (recorded per call by LLMAccountingMiddleware) is exhausted.
    await enforce_daily_cost_budget(user_id, feature_key="chat_messages")
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
    # The ONE event for a chat message. It fires for every surface (web,
    # desktop, and bots via endpoints/bot.py), no ad blocker can drop it, and
    # it lands only once the request has passed the rate limit and the cost
    # budget — so it counts messages that were actually accepted.
    #
    # The composer context below used to ride on a second, client-side
    # `chat:message_sent`. Every field of it arrives in this request anyway, so
    # that emitter was a duplicate of this one wearing a different name and has
    # been removed; counting either name now gives the same, correct number.
    capture_context_event(
        AnalyticsEvents.CHAT_MESSAGE_SUBMITTED,
        {
            "is_new_conversation": body.conversation_id is None,
            "message_count": len(body.messages) if body.messages else 0,
            "has_files": bool(body.fileIds or body.fileData),
            "file_count": len(body.fileIds or []) + len(body.fileData or []),
            "has_selected_tool": bool(body.selectedTool),
            "tool_name": body.selectedTool,
            "tool_category": body.toolCategory,
            "has_selected_workflow": bool(body.selectedWorkflow),
            "workflow_id": body.selectedWorkflow.id if body.selectedWorkflow else None,
            "has_selected_calendar_event": bool(body.selectedCalendarEvent),
            "is_reply": bool(body.replyToMessage),
            "source": _resolve_source(request),
        },
    )

    spawn_background_task(
        run_chat_stream_background(
            stream_id=stream_id,
            body=body,
            user=user,
            conversation_id=conversation_id,
            source=_resolve_source(request),
        )
    )

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
    user_id: str = Depends(get_user_id),
) -> CancelStreamResponse:
    """Cancel a running stream owned by the requesting user."""
    log.set(user={"id": user_id}, chat={"stream_id": stream_id})

    # Progress is a free-form JSON blob deserialized from Redis, not a model —
    # keyed access is the honest read here.
    progress = await stream_manager.get_progress(stream_id)
    if not progress:
        return CancelStreamResponse(
            success=False,
            stream_id=stream_id,
            error="Stream not found",
        )

    if progress.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this stream",
        )

    success = await stream_manager.cancel_stream(stream_id)
    log.info(f"{LogTag.CHAT} Cancel stream request", stream_id=stream_id, success=success)

    return CancelStreamResponse(success=success, stream_id=stream_id)


@router.get("/stream/{stream_id}")
async def subscribe_executor_stream(
    stream_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
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

    # A finished stream still has a replayable event log — subscribe_stream
    # replays it and returns at the DONE control entry, so a late attach loses
    # nothing. (An earlier is_complete short-circuit returned a bare [DONE]
    # here, which dropped every frame a just-paused HIL resume had published —
    # the second approval card never reached the client.) Only when the log has
    # already expired is there genuinely nothing to replay; answer [DONE] then,
    # or subscribe_stream would idle on keepalives forever.
    if progress.get("is_complete") and not await stream_manager.has_events(stream_id):
        log.info(
            f"{LogTag.CHAT} Executor stream complete and log expired, returning [DONE]",
            stream_id=stream_id,
        )

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

    log.info(f"{LogTag.CHAT} Client subscribed to executor stream", stream_id=stream_id)

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
