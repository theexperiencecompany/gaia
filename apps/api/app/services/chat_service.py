"""
Chat service with Redis-backed background streaming.

Background streaming decouples LangGraph execution from HTTP request lifecycle,
ensuring conversations are always saved even if client disconnects.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import UsageMetadataCallbackHandler

from app.agents.core.agent import call_agent
from app.agents.core.background.inbox import (
    deregister_bg_subagent_results,
    deregister_executor_done_event,
    deregister_executor_spawned,
    deregister_pending_subagents,
    deregister_tool_event_collector,
    get_tool_event_collector,
    register_executor_done_event,
    register_tool_event_collector,
    was_executor_spawned,
)
from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.model_pricing import calculate_token_cost
from app.core.stream_manager import stream_manager
from app.db.mongodb.collections import conversations_collection
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.services.conversation_service import update_messages
from app.services.payments.payment_service import payment_service
from app.utils.chat_utils import create_conversation, generate_and_update_description
from app.utils.stream_utils import (
    absorb_collector_event,
    aggregate_usage_metadata,
    apply_outputs_to_tool_data,
    inject_todo_progress,
    merge_tool_outputs,
    process_data_chunk,
    publish_description_if_ready,
    reconstruct_subagent_groups,
    recover_stream_state,
    set_stream_log_context,
)
from shared.py.wide_events import log, wide_task


async def run_chat_stream_background(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    source: str | None = None,
    start_event: asyncio.Event | None = None,
) -> None:
    """
    Run chat streaming in background, publishing chunks to Redis.

    This function runs independently of the HTTP request lifecycle.
    Progress is saved to MongoDB on completion, even if client disconnects.
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


def _start_description_task(
    is_new_conversation: bool,
    body: MessageRequestWithHistory,
    conversation_id: str,
    user: dict,
) -> asyncio.Task | None:
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


async def _wait_for_http_subscriber(
    start_event: asyncio.Event | None,
    stream_id: str,
) -> None:
    if not start_event or start_event.is_set():
        return
    try:
        await asyncio.wait_for(start_event.wait(), timeout=5.0)
    except TimeoutError:
        log.warning(f"Stream {stream_id} HTTP subscriber timeout, proceeding anyway")


async def _run_chat_stream(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    source: str | None = None,
    start_event: asyncio.Event | None = None,
) -> None:
    complete_message = ""
    tool_data: dict[str, Any] = {"tool_data": []}
    tool_outputs: dict[str, str] = {}
    todo_progress_accumulated: dict[str, Any] = {}
    user_message_id = str(uuid4())
    bot_message_id = str(uuid4())
    is_new_conversation = body.conversation_id is None or (
        body.is_onboarding_demo
        and not await conversations_collection.find_one(
            {
                "user_id": user.get("user_id"),
                "conversation_id": body.conversation_id,
            },
            {"_id": 1},
        )
    )
    usage_metadata: dict[str, Any] = {}
    follow_up_actions: list[str] = []
    is_cancelled = False
    _saved = False  # tracks whether _save_conversation_async already ran

    # Register the executor-done event so we can keep the SSE stream open
    # while the background executor produces tool events, then publish [DONE]
    # once it finishes. Comms re-narration + WS push of the user-facing
    # message happens independently in the executor's finally block.
    executor_done = register_executor_done_event(stream_id)
    # Register the tool event collector so make_redis_stream_writer can
    # append executor tool events. After executor finishes we drain this
    # list and attach it to the comms ack message's tool_data.
    register_tool_event_collector(stream_id)

    try:
        description_task = _start_description_task(is_new_conversation, body, conversation_id, user)

        user_id = user.get("user_id")
        set_stream_log_context(body, user_id, conversation_id, stream_id, is_new_conversation)

        usage_metadata_callback = UsageMetadataCallbackHandler()

        # Initialize conversation if new
        if is_new_conversation:
            init_data = await _initialize_new_conversation(
                body=body,
                user=user,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                bot_message_id=bot_message_id,
                stream_id=stream_id,
            )
        else:
            # For existing conversations there is no async setup before publishing
            # the init chunk. uvicorn does an asyncio.sleep(0) drain after sending
            # HTTP response headers, during which this background task can run and
            # reach publish_chunk before the HTTP subscriber has called
            # pubsub.subscribe(). Without this sleep the PUBLISH races the SUBSCRIBE
            # and the init chunk is silently dropped. New conversations avoid this
            # race via the MongoDB round-trips inside _initialize_new_conversation.
            await asyncio.sleep(0.05)
            init_data = f"data: {json.dumps({'user_message_id': user_message_id, 'bot_message_id': bot_message_id, 'stream_id': stream_id})}\n\n"

        await _wait_for_http_subscriber(start_event, stream_id)
        await stream_manager.publish_chunk(stream_id, init_data)
        async for chunk in await call_agent(
            request=body,
            user=user,
            conversation_id=conversation_id,
            user_time=user_time,
            usage_metadata_callback=usage_metadata_callback,
            stream_id=stream_id,
            user_message_id=user_message_id,
            bot_message_id=bot_message_id,
            source=source,
        ):
            if await stream_manager.is_cancelled(stream_id):
                is_cancelled = True
                log.info(f"Stream {stream_id} cancelled by user")
                break

            # Skip [DONE] marker - we send it after description generation
            if chunk == "data: [DONE]\n\n":
                continue

            description_task = await publish_description_if_ready(stream_id, description_task)

            # Process complete message marker (internal, not sent to client)
            if chunk.startswith("nostream: "):
                nostream_json = json.loads(chunk.replace("nostream: ", ""))
                if isinstance(nostream_json, dict) and "complete_message" in nostream_json:
                    complete_message = str(nostream_json["complete_message"])
                else:
                    complete_message = ""
                continue

            if chunk.startswith("data: "):
                try:
                    follow_up_actions, _ = await process_data_chunk(
                        stream_id,
                        chunk,
                        tool_data,
                        tool_outputs,
                        todo_progress_accumulated,
                        follow_up_actions,
                    )
                except Exception as e:
                    log.error(f"Error processing chunk: {e}")
                    await stream_manager.publish_chunk(stream_id, chunk)
            else:
                await stream_manager.publish_chunk(stream_id, chunk)

        usage_metadata = usage_metadata_callback.usage_metadata or {}
        total_input, total_output, total_cached = aggregate_usage_metadata(usage_metadata)
        # Read cache_read out of the LangChain UsageMetadataCallback rather
        # than the wide-event ContextVar. ``LLMAccountingMiddleware`` writes
        # ``cached_tokens`` per-step into the wide event from inside a
        # LangGraph node, but those writes happen in a child copy_context()
        # frame that does not propagate back to the wide_task block — so the
        # worker_task rollup would otherwise see ``cached_tokens=null`` even
        # when caching fired. The callback handler runs in the parent context
        # via LangChain's tracer and accumulates correctly across every model
        # call.
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
            response_length=len(complete_message),
            follow_up_actions_count=len(follow_up_actions),
            is_cancelled=is_cancelled,
        )

        # ── Early save: guarantee ordering before waiting for executor ──
        # Save the comms ack IMMEDIATELY after the comms streaming loop.
        # This ensures this message's array position in MongoDB is correct
        # even if a concurrent stream for a second user message completes
        # while we wait for the executor below.
        complete_message, tool_data = await recover_stream_state(
            stream_id, complete_message, tool_data
        )
        merge_tool_outputs(tool_data, tool_outputs)
        inject_todo_progress(tool_data, todo_progress_accumulated)
        reconstruct_subagent_groups(tool_data)

        await _save_conversation_async(
            body=body,
            user=user,
            conversation_id=conversation_id,
            complete_message=complete_message,
            tool_data=tool_data,
            metadata=usage_metadata,
            user_message_id=user_message_id,
            bot_message_id=bot_message_id,
        )
        _saved = True

        # ── Wait for the executor to finish ───────────────────────────────
        # The SSE stream stays open while the background executor produces
        # tool events so the frontend renders them live. Once the executor
        # signals done, drain its tool events into the comms ack message's
        # tool_data, then close the SSE. Comms re-narration runs separately
        # in the executor's finally block and is delivered via WebSocket.
        if not is_cancelled and was_executor_spawned(stream_id):
            log.info(f"Waiting for executor completion for stream {stream_id}")
            try:
                await asyncio.wait_for(executor_done.wait(), timeout=1800)
            except TimeoutError:
                log.warning(
                    f"Timed out waiting for executor on stream {stream_id} — "
                    "publishing [DONE] anyway"
                )

            executor_td = _accumulate_executor_tool_data(stream_id)
            if executor_td:
                try:
                    await conversations_collection.update_one(
                        {
                            "user_id": user.get("user_id"),
                            "conversation_id": conversation_id,
                            "messages.message_id": bot_message_id,
                        },
                        {"$push": {"messages.$.tool_data": {"$each": executor_td}}},
                    )
                except Exception as e:
                    log.error(f"Failed to update bot message tool_data: {e}")

        # Await description task if still pending
        if description_task:
            try:
                description = await description_task
                await stream_manager.publish_chunk(
                    stream_id,
                    f"""data: {json.dumps({"conversation_description": description})}\n\n""",
                )
            except Exception as e:
                log.error(f"Failed to get conversation description: {e}")

        # Send [DONE] marker to signal stream completion
        await stream_manager.publish_chunk(stream_id, "data: [DONE]\n\n")
        await stream_manager.complete_stream(stream_id)

    except Exception as e:
        log.error(
            "background_stream_error",
            stream_id=stream_id,
            user_id=user.get("user_id") if isinstance(user, dict) else None,
            conversation_id=conversation_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        await _wait_for_http_subscriber(start_event, stream_id)
        # IMPORTANT: Publish error chunk FIRST, before calling set_error()
        # set_error() publishes STREAM_ERROR_SIGNAL which breaks the subscriber loop
        # If we call set_error() first, the error message never reaches the client
        await stream_manager.publish_chunk(stream_id, f"data: {json.dumps({'error': str(e)})}\n\n")
        await stream_manager.set_error(stream_id, str(e))
    finally:
        deregister_executor_done_event(stream_id)
        deregister_tool_event_collector(stream_id)
        deregister_pending_subagents(stream_id)
        deregister_executor_spawned(stream_id)
        deregister_bg_subagent_results(stream_id)

        if not _saved:
            # Error path: save as fallback. recover_stream_state / merge /
            # inject are safe to call even if partially run in try block.
            try:
                complete_message, tool_data = await recover_stream_state(
                    stream_id, complete_message, tool_data
                )
                merge_tool_outputs(tool_data, tool_outputs)
                inject_todo_progress(tool_data, todo_progress_accumulated)
                reconstruct_subagent_groups(tool_data)
                await _save_conversation_async(
                    body=body,
                    user=user,
                    conversation_id=conversation_id,
                    complete_message=complete_message,
                    tool_data=tool_data,
                    metadata=usage_metadata,
                    user_message_id=user_message_id,
                    bot_message_id=bot_message_id,
                )
            except Exception as save_err:
                log.error(f"Fallback save failed for stream {stream_id}: {save_err}")

        # Cleanup Redis
        await stream_manager.cleanup(stream_id)

        tool_entries = tool_data.get("tool_data", [])
        log.set(
            response_length=len(complete_message),
            tool_calls_count=len(tool_entries),
            tool_types=list({e["tool_name"] for e in tool_entries if "tool_name" in e}),
            todo_progress_sources=list(todo_progress_accumulated.keys()),
        )
        log.debug(f"Background stream {stream_id} completed and saved")


async def _initialize_new_conversation(
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    user_message_id: str,
    bot_message_id: str,
    stream_id: str,
) -> str:
    """Create new conversation and return init chunk."""
    last_message = body.messages[-1] if body.messages else None

    conversation = await create_conversation(
        last_message,
        user=user,
        selectedTool=body.selectedTool,
        selectedWorkflow=body.selectedWorkflow,
        generate_description=False,
        conversation_id=conversation_id,
        is_onboarding_demo=body.is_onboarding_demo,
    )

    init_data = {
        "conversation_id": conversation_id,
        "conversation_description": conversation.get("conversation_description"),
        "user_message_id": user_message_id,
        "bot_message_id": bot_message_id,
        "stream_id": stream_id,
    }

    return f"data: {json.dumps(init_data)}\n\n"


async def _save_conversation_async(
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    complete_message: str,
    tool_data: dict[str, Any],
    metadata: dict[str, Any],
    user_message_id: str,
    bot_message_id: str,
) -> None:
    """Save conversation to MongoDB (called from background task)."""
    user_id = user.get("user_id")

    # Process token usage
    if metadata and user_id:
        try:
            await _process_token_usage_and_cost(user_id, metadata)
        except Exception as e:
            log.error(
                "token_usage_processing_failed",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
                models_in_metadata=list(metadata.keys()) if isinstance(metadata, dict) else [],
                exc_info=True,
            )

    # Get timestamps
    bot_timestamp = datetime.now(UTC)
    user_timestamp = bot_timestamp - timedelta(milliseconds=100)

    # Create user message
    user_content = (
        body.messages[-1].get("content") if body.messages and len(body.messages) > 0 else None
    ) or body.message

    user_message = MessageModel(
        type="user",
        response=user_content,
        date=user_timestamp.isoformat(),
        fileIds=body.fileIds,
        fileData=body.fileData,
        selectedTool=body.selectedTool,
        toolCategory=body.toolCategory,
        selectedWorkflow=body.selectedWorkflow,
        replyToMessage=body.replyToMessage,
    )
    user_message.message_id = user_message_id

    # Create bot message
    bot_message = MessageModel(
        type="bot",
        response=complete_message,
        date=bot_timestamp.isoformat(),
        fileIds=body.fileIds,
        metadata=metadata,
    )
    bot_message.message_id = bot_message_id

    # Apply tool data
    for key, value in tool_data.items():
        setattr(bot_message, key, value)

    # Save to DB
    await update_messages(
        UpdateMessagesRequest(
            conversation_id=conversation_id,
            messages=[user_message, bot_message],
        ),
        user=user,
    )


def _accumulate_executor_tool_data(stream_id: str) -> list[dict[str, Any]]:
    """Drain the executor tool event collector into a flat tool_data list.

    Mirrors the comms-graph accumulation path: tool_calls_data outputs are
    merged in, subagent start/end pairs are grouped via reconstruct_subagent_groups.
    Only tool_calls_data entries get their output backfilled (the comms ack
    message only owns tool_calls_data; other entries belong to the executor).
    """
    collector = get_tool_event_collector(stream_id)
    if not collector:
        return []
    accumulated: dict[str, Any] = {"tool_data": []}
    outputs: dict[str, str] = {}
    for evt in collector:
        absorb_collector_event(evt, accumulated, outputs)
    apply_outputs_to_tool_data(accumulated["tool_data"], outputs, only_tool_name="tool_calls_data")
    reconstruct_subagent_groups(accumulated)
    return accumulated.get("tool_data", [])


async def _process_token_usage_and_cost(user_id: str, metadata: dict[str, Any]) -> None:
    """Process token usage and calculate costs."""
    try:
        subscription = await payment_service.get_user_subscription_status(user_id)
        user_plan = subscription.plan_type or PlanType.FREE

        total_credits = 0.0

        for model_name, usage_data in metadata.items():
            if isinstance(usage_data, dict):
                input_tokens = usage_data.get("input_tokens", 0)
                output_tokens = usage_data.get("output_tokens", 0)
                # Bill cache reads at the discounted rate, not free.
                details = usage_data.get("input_token_details") or {}
                cached_tokens = int(
                    details.get("cache_read") or usage_data.get("cached_content_token_count") or 0
                )

                if input_tokens > 0 or output_tokens > 0:
                    cost_info = await calculate_token_cost(
                        model_name,
                        input_tokens,
                        output_tokens,
                        cached_tokens=cached_tokens,
                    )
                    total_credits += cost_info["total_cost"]

        if total_credits > 0:
            await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key="chat_messages",
                user_plan=user_plan,
                credits_used=total_credits,
            )

        existing_model = log.get().get("model", {})
        log.set(
            model={**existing_model, "cost_usd": round(total_credits, 6)},
            user_plan=str(user_plan),
        )

    except Exception as e:
        log.debug(f"Token usage processing failed: {e}")
