"""Chat-stream orchestrator: one full turn through LangGraph.

:func:`run_chat_stream_background` is the public entry point — wraps a wide
event and delegates to :func:`_run_chat_stream`, which is structured as a
linear sequence of *phase* helpers (setup, init, loop, finalize). Each phase
helper does one thing the orchestrator name claims.

The orchestrator runs decoupled from the HTTP request: chunks are published to
a Redis channel via ``stream_manager`` and the conversation is always persisted
on completion, even if the client disconnects mid-stream.
"""

import asyncio
import contextlib
from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import UsageMetadataCallbackHandler

from app.agents.core.agent import call_agent
from app.core.stream_manager import stream_manager
from app.models.message_models import MessageRequestWithHistory
from app.services.chat.chunks import process_data_chunk
from app.services.chat.persistence import (
    initialize_new_conversation,
    save_conversation_async,
)
from app.services.chat.state import (
    aggregate_usage_metadata,
    inject_todo_progress,
    merge_tool_outputs,
    recover_stream_state,
)
from app.services.chat.workspace import (
    forward_artifact_events,
    prepare_user_workspace,
)
from app.services.storage import flush_fs_metrics
from app.utils.chat_utils import generate_and_update_description
from shared.py.wide_events import ChatContext, log, wide_task


async def run_chat_stream_background(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    source: str | None = None,
    start_event: asyncio.Event | None = None,
) -> None:
    """Run chat streaming in the background, publishing chunks to Redis.

    Independent of the HTTP request lifecycle — progress is saved to MongoDB on
    completion even if the client disconnects.
    """
    async with wide_task(
        "chat_stream",
        conversation_id=conversation_id,
        stream_id=stream_id,
    ):
        await _run_chat_stream(
            stream_id=stream_id,
            body=body,
            user=user,
            user_time=user_time,
            conversation_id=conversation_id,
            source=source,
            start_event=start_event,
        )


class _StreamState:
    """Mutable accumulators threaded through the orchestrator phases.

    Holds the running text, tool data, tool outputs, todo snapshots, follow-up
    actions, usage metadata, and cancellation flag for a single turn. Bundled
    into one object so the phase helpers can share state without unwieldy
    argument lists.
    """

    __slots__ = (
        "bot_message_id",
        "complete_message",
        "follow_up_actions",
        "is_cancelled",
        "todo_progress_accumulated",
        "tool_data",
        "tool_outputs",
        "usage_metadata",
        "user_message_id",
    )

    def __init__(self) -> None:
        self.complete_message: str = ""
        self.tool_data: dict[str, Any] = {"tool_data": []}
        self.tool_outputs: dict[str, str] = {}
        self.todo_progress_accumulated: dict[str, Any] = {}
        self.follow_up_actions: list[str] = []
        self.usage_metadata: dict[str, Any] = {}
        self.is_cancelled: bool = False
        self.user_message_id: str = str(uuid4())
        self.bot_message_id: str = str(uuid4())


async def _run_chat_stream(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    source: str | None = None,
    start_event: asyncio.Event | None = None,
) -> None:
    state = _StreamState()
    is_new_conversation = body.conversation_id is None
    user_id = user.get("user_id")
    artifact_task: asyncio.Task[None] | None = None
    description_task: asyncio.Task[str] | None = None

    try:
        description_task = _start_description_task(is_new_conversation, body, conversation_id, user)
        _set_stream_log_context(body, user_id, conversation_id, stream_id, is_new_conversation)

        if user_id:
            await prepare_user_workspace(user_id, conversation_id)
            artifact_task = asyncio.create_task(
                forward_artifact_events(
                    user_id, conversation_id, stream_id, state.tool_data, source
                )
            )

        await _publish_init_chunk(
            body,
            user,
            conversation_id,
            stream_id,
            state,
            start_event,
            is_new_conversation,
        )
        usage_callback = UsageMetadataCallbackHandler()
        description_task = await _consume_agent_stream(
            body,
            user,
            user_time,
            conversation_id,
            stream_id,
            source,
            usage_callback,
            description_task,
            state,
        )
        state.usage_metadata = usage_callback.usage_metadata or {}
        _log_usage_summary(state)
        await _finalize_description(description_task, stream_id)
        await stream_manager.publish_chunk(stream_id, "data: [DONE]\n\n")
        await stream_manager.complete_stream(stream_id)

    except Exception as e:  # noqa: BLE001 — surface to client + flag the stream
        await _handle_stream_error(stream_id, e, start_event)
    finally:
        await _finalize_stream(stream_id, body, user, conversation_id, state, artifact_task)


def _set_stream_log_context(
    body: MessageRequestWithHistory,
    user_id: str | None,
    conversation_id: str,
    stream_id: str,
    is_new_conversation: bool,
) -> None:
    """Attach structured log context for the stream."""
    log.set(
        user={"id": str(user_id)} if user_id else {},
        chat=ChatContext(
            conversation_id=conversation_id,
            stream_id=stream_id,
            is_new_conversation=is_new_conversation,
            message_count=len(body.messages) if body.messages else None,
            has_files=bool(body.fileIds or body.fileData),
            file_count=len(body.fileIds or []) + len(body.fileData or []),
            tool_category=body.toolCategory,
            has_reply=bool(body.replyToMessage),
            has_calendar_event=bool(body.selectedCalendarEvent),
            selected_workflow_id=body.selectedWorkflow.id if body.selectedWorkflow else None,
        ),
        user_message_length=len(body.messages[-1]["content"]) if body.messages else 0,
        selected_tool=body.selectedTool,
    )


def _start_description_task(
    is_new_conversation: bool,
    body: MessageRequestWithHistory,
    conversation_id: str,
    user: dict,
) -> asyncio.Task[str] | None:
    """Create a background task to generate a conversation description if new."""
    if not is_new_conversation:
        return None
    last_message = body.messages[-1] if body.messages else None
    return asyncio.create_task(
        generate_and_update_description(
            conversation_id,
            last_message,
            user,
            body.selectedTool if body.selectedTool else None,
            body.selectedWorkflow if body.selectedWorkflow else None,
        )
    )


async def _publish_description_if_ready(
    stream_id: str,
    description_task: asyncio.Task[str] | None,
) -> asyncio.Task[str] | None:
    """Publish the description chunk if the task has completed. Returns ``None``
    to clear the task reference."""
    if not description_task or not description_task.done():
        return description_task
    try:
        description = description_task.result()
        await stream_manager.publish_chunk(
            stream_id,
            f"""data: {json.dumps({"conversation_description": description})}\n\n""",
        )
    except Exception as e:  # noqa: BLE001 — description is non-critical
        log.error(f"Failed to get conversation description: {e}")
    return None


async def _wait_for_http_subscriber(
    start_event: asyncio.Event | None,
    stream_id: str,
) -> None:
    """Block until the HTTP handler has subscribed to the Redis channel (or
    5s timeout)."""
    if not start_event or start_event.is_set():
        return
    try:
        await asyncio.wait_for(start_event.wait(), timeout=5.0)
    except TimeoutError:
        log.warning(f"Stream {stream_id} HTTP subscriber timeout, proceeding anyway")


async def _publish_init_chunk(
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    stream_id: str,
    state: _StreamState,
    start_event: asyncio.Event | None,
    is_new_conversation: bool,
) -> None:
    """Send the first SSE frame (conversation id + message ids) to the client."""
    if is_new_conversation:
        init_data = await initialize_new_conversation(
            body=body,
            user=user,
            conversation_id=conversation_id,
            user_message_id=state.user_message_id,
            bot_message_id=state.bot_message_id,
            stream_id=stream_id,
        )
    else:
        init_payload = {
            "user_message_id": state.user_message_id,
            "bot_message_id": state.bot_message_id,
            "stream_id": stream_id,
        }
        init_data = f"data: {json.dumps(init_payload)}\n\n"

    await _wait_for_http_subscriber(start_event, stream_id)
    await stream_manager.publish_chunk(stream_id, init_data)


async def _consume_agent_stream(
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    stream_id: str,
    source: str | None,
    usage_callback: UsageMetadataCallbackHandler,
    description_task: asyncio.Task[str] | None,
    state: _StreamState,
) -> asyncio.Task[str] | None:
    """Iterate the agent's SSE chunks and dispatch each to the right path.

    Returns the (possibly-cleared) ``description_task`` so the orchestrator can
    await whatever's left.
    """
    async for chunk in await call_agent(
        request=body,
        user=user,
        conversation_id=conversation_id,
        user_time=user_time,
        usage_metadata_callback=usage_callback,
        stream_id=stream_id,
        bot_message_id=state.bot_message_id,
        source=source,
    ):
        if await stream_manager.is_cancelled(stream_id):
            state.is_cancelled = True
            log.info(f"Stream {stream_id} cancelled by user")
            break

        # Skip [DONE] marker — we send it after description generation.
        if chunk == "data: [DONE]\n\n":
            continue

        description_task = await _publish_description_if_ready(stream_id, description_task)

        if chunk.startswith("nostream: "):
            state.complete_message = _parse_complete_message(chunk)
            continue

        if chunk.startswith("data: "):
            try:
                state.follow_up_actions, _ = await process_data_chunk(
                    stream_id,
                    chunk,
                    state.tool_data,
                    state.tool_outputs,
                    state.todo_progress_accumulated,
                    state.follow_up_actions,
                )
            except Exception as e:  # noqa: BLE001 — fall back to passthrough
                log.error(f"Error processing chunk: {e}")
                await stream_manager.publish_chunk(stream_id, chunk)
        else:
            await stream_manager.publish_chunk(stream_id, chunk)
    return description_task


def _parse_complete_message(chunk: str) -> str:
    """Pull the ``complete_message`` field out of a ``nostream: {...}`` marker."""
    nostream_json = json.loads(chunk.replace("nostream: ", ""))
    if isinstance(nostream_json, dict) and "complete_message" in nostream_json:
        return str(nostream_json["complete_message"])
    return ""


def _log_usage_summary(state: _StreamState) -> None:
    """Aggregate usage metadata and emit the per-turn token totals to the wide
    event.

    Reads ``cache_read`` from the LangChain ``UsageMetadataCallback`` rather
    than the wide-event ``ContextVar``. ``LLMAccountingMiddleware`` writes
    ``cached_tokens`` per-step into the wide event from inside a LangGraph
    node, but those writes happen in a child ``copy_context()`` frame that does
    not propagate back to the ``wide_task`` block — so the worker rollup would
    otherwise see ``cached_tokens=null`` even when caching fired. The callback
    handler runs in the parent context via LangChain's tracer and accumulates
    correctly across every model call.
    """
    total_input, total_output, total_cached = aggregate_usage_metadata(state.usage_metadata)
    cache_hit_rate = round(total_cached / max(total_input, 1), 4) if total_input else 0.0
    existing_model = log.get().get("model") or {}
    log.set(
        model={
            **existing_model,
            "tokens_used": total_input + total_output,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cached_tokens": total_cached,
            "cache_hit_rate": cache_hit_rate,
        },
        response_length=len(state.complete_message),
        follow_up_actions_count=len(state.follow_up_actions),
        is_cancelled=state.is_cancelled,
    )


async def _finalize_description(
    description_task: asyncio.Task[str] | None,
    stream_id: str,
) -> None:
    """Await the description task and publish the resulting chunk, if any."""
    if not description_task:
        return
    try:
        description = await description_task
        await stream_manager.publish_chunk(
            stream_id,
            f"""data: {json.dumps({"conversation_description": description})}\n\n""",
        )
    except Exception as e:  # noqa: BLE001 — description is non-critical
        log.error(f"Failed to get conversation description: {e}")


async def _handle_stream_error(
    stream_id: str,
    error: Exception,
    start_event: asyncio.Event | None,
) -> None:
    """Publish the error to the client and flag the stream as failed.

    Order matters: ``set_error`` publishes the ``STREAM_ERROR_SIGNAL`` which
    breaks the subscriber loop, so the error chunk must go on the wire first.
    """
    log.error(f"Background stream error for {stream_id}: {error}")
    await _wait_for_http_subscriber(start_event, stream_id)
    await stream_manager.publish_chunk(stream_id, f"data: {json.dumps({'error': str(error)})}\n\n")
    await stream_manager.set_error(stream_id, str(error))


async def _finalize_stream(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    state: _StreamState,
    artifact_task: asyncio.Task[None] | None,
) -> None:
    """Always-run cleanup: cancel artifact forwarder, recover state, persist,
    cleanup Redis, emit final wide event."""
    if artifact_task is not None:
        artifact_task.cancel()
        with contextlib.suppress(BaseException):
            await artifact_task

    # On cancellation, complete_message may be empty because nostream: marker
    # never arrives — recover from Redis progress which tracks accumulated text.
    state.complete_message, state.tool_data = await recover_stream_state(
        stream_id, state.complete_message, state.tool_data
    )

    merge_tool_outputs(state.tool_data, state.tool_outputs)
    inject_todo_progress(state.tool_data, state.todo_progress_accumulated)

    await save_conversation_async(
        body=body,
        user=user,
        conversation_id=conversation_id,
        complete_message=state.complete_message,
        tool_data=state.tool_data,
        metadata=state.usage_metadata,
        user_message_id=state.user_message_id,
        bot_message_id=state.bot_message_id,
    )

    await stream_manager.cleanup(stream_id)

    tool_entries = state.tool_data.get("tool_data", [])
    fs_metrics = flush_fs_metrics()
    log.set(
        response_length=len(state.complete_message),
        tool_calls_count=len(tool_entries),
        tool_types=list({e["tool_name"] for e in tool_entries if "tool_name" in e}),
        todo_progress_sources=list(state.todo_progress_accumulated.keys()),
        # Per-op FS latency aggregate — one structured field so LogQL can split
        # on op name, count, total_ms, max_ms without N+1 log lines. Empty dict
        # elided so events without FS activity stay clean.
        **({"fs": fs_metrics} if fs_metrics else {}),
    )
    log.debug(f"Background stream {stream_id} completed and saved")
