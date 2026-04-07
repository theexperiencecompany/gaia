"""
Chat service with Redis-backed background streaming.

This module provides two streaming modes:
1. run_chat_stream_background() - Background execution with Redis pub/sub (new)
2. chat_stream() - Legacy direct streaming (kept for backwards compatibility)

Background streaming decouples LangGraph execution from HTTP request lifecycle,
ensuring conversations are always saved even if client disconnects.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.agents.core.agent import call_agent
from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from shared.py.wide_events import ChatContext, ModelContext, log, wide_task
from app.config.model_pricing import calculate_token_cost
from app.core.stream_manager import stream_manager
from app.models.chat_models import (
    MessageModel,
    ToolDataEntry,
    UpdateMessagesRequest,
    tool_fields,
)
from app.models.message_models import MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.services.conversation_service import update_messages
from app.services.payments.payment_service import payment_service
from app.utils.chat_utils import create_conversation, generate_and_update_description
from langchain_core.callbacks import UsageMetadataCallbackHandler


async def run_chat_stream_background(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    source: Optional[str] = None,
    start_event: Optional[asyncio.Event] = None,
) -> None:
    """
    Run chat streaming in background, publishing chunks to Redis.

    This function runs independently of the HTTP request lifecycle.
    Progress is saved to MongoDB on completion, even if client disconnects.

    Args:
        stream_id: Unique stream identifier for Redis pub/sub
        body: Message request with history
        user: User information dict
        user_time: User's local time
        conversation_id: Conversation ID (may be new or existing)
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


def _set_stream_log_context(
    body: MessageRequestWithHistory,
    user_id: Optional[str],
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
            selected_workflow_id=body.selectedWorkflow.id
            if body.selectedWorkflow
            else None,
        ),
        user_message_length=len(body.messages[-1]["content"]) if body.messages else 0,
        selected_tool=body.selectedTool,
    )


def _start_description_task(
    is_new_conversation: bool,
    body: MessageRequestWithHistory,
    conversation_id: str,
    user: dict,
) -> Optional[asyncio.Task]:
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
    description_task: Optional[asyncio.Task],
) -> Optional[asyncio.Task]:
    """Publish conversation description chunk if the task has completed. Returns None to clear it."""
    if not description_task or not description_task.done():
        return description_task
    try:
        description = description_task.result()
        await stream_manager.publish_chunk(
            stream_id,
            f"""data: {json.dumps({"conversation_description": description})}\n\n""",
        )
    except Exception as e:
        log.error(f"Failed to get conversation description: {e}")
    return None  # Clear to prevent duplicate sends


async def _process_data_chunk(
    stream_id: str,
    chunk: str,
    tool_data: Dict[str, Any],
    tool_outputs: Dict[str, str],
    todo_progress_accumulated: Dict[str, Any],
    follow_up_actions: List[str],
) -> tuple[List[str], bool]:
    """
    Process a 'data: ' prefixed agent chunk.

    Extracts tool data, follow-up actions, todo progress, and tool outputs,
    publishes appropriate sub-chunks to Redis, and updates stream progress.

    Returns (follow_up_actions, published) where published indicates whether
    the chunk was already sent (True) or should be sent as-is (False).
    """
    chunk_payload = chunk[6:]

    chunk_json: Optional[Dict[str, Any]] = None
    try:
        chunk_json = json.loads(chunk_payload)
    except json.JSONDecodeError:
        chunk_json = None

    if chunk_json and "todo_progress" in chunk_json:
        snapshot = chunk_json["todo_progress"]
        source = snapshot.get("source", "executor")
        todo_progress_accumulated[source] = snapshot

    new_data = extract_tool_data(chunk_payload)
    if new_data:
        if "other_data" in new_data:
            other_data_dict = new_data["other_data"]
            if "follow_up_actions" in other_data_dict:
                follow_up_actions = other_data_dict["follow_up_actions"]
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'follow_up_actions': follow_up_actions})}\n\n",
                )

        if "tool_data" in new_data:
            for tool_entry in new_data["tool_data"]:
                tool_data["tool_data"].append(tool_entry)
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'tool_data': tool_entry})}\n\n",
                )

        # Capture tool_output events for merging before save
        # AND stream to frontend for real-time UI updates
        if "tool_output" in new_data:
            output_data = new_data["tool_output"]
            tool_call_id = output_data.get("tool_call_id")
            output = output_data.get("output")
            if tool_call_id and output:
                tool_outputs[tool_call_id] = output
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'tool_output': output_data})}\n\n",
            )

        if chunk_json and "todo_progress" in chunk_json:
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'todo_progress': chunk_json['todo_progress']})}\n\n",
            )

        response_text = _extract_response_text(chunk)
        if response_text or new_data:
            await stream_manager.update_progress(
                stream_id,
                message_chunk=response_text,
                tool_data=new_data,
            )
        return follow_up_actions, True

    # No tool data — pass through as-is
    await stream_manager.publish_chunk(stream_id, chunk)
    response_text = _extract_response_text(chunk)
    if response_text:
        await stream_manager.update_progress(
            stream_id,
            message_chunk=response_text,
            tool_data=None,
        )
    return follow_up_actions, True


def _aggregate_usage_metadata(
    usage_metadata: Dict[str, Any],
) -> tuple[int, int]:
    """Sum input and output tokens across all model entries in usage metadata."""
    total_input = sum(
        v.get("input_tokens", 0) for v in usage_metadata.values() if isinstance(v, dict)
    )
    total_output = sum(
        v.get("output_tokens", 0)
        for v in usage_metadata.values()
        if isinstance(v, dict)
    )
    return total_input, total_output


async def _recover_stream_state(
    stream_id: str,
    complete_message: str,
    tool_data: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """
    Recover complete_message and tool_data from Redis progress when the nostream
    marker was never delivered (e.g. on cancellation).
    """
    if complete_message:
        return complete_message, tool_data

    progress = await stream_manager.get_progress(stream_id)
    if not progress:
        return complete_message, tool_data

    complete_message = progress.get("complete_message", "")
    progress_tool_data = progress.get("tool_data")
    if (
        isinstance(progress_tool_data, dict)
        and progress_tool_data.get("tool_data")
        and not tool_data.get("tool_data")
    ):
        tool_data = progress_tool_data
    log.debug(f"Recovered {len(complete_message)} chars from Redis progress")
    return complete_message, tool_data


def _merge_tool_outputs(
    tool_data: Dict[str, Any],
    tool_outputs: Dict[str, str],
) -> None:
    """Merge captured tool outputs into the tool_data entries before saving."""
    for entry in tool_data.get("tool_data", []):
        if entry.get("tool_name") == "tool_calls_data":
            data = entry.get("data", {})
            if isinstance(data, dict):
                tool_call_id = data.get("tool_call_id")
                if tool_call_id and tool_call_id in tool_outputs:
                    data["output"] = tool_outputs[tool_call_id]


def _inject_todo_progress(
    tool_data: Dict[str, Any],
    todo_progress_accumulated: Dict[str, Any],
) -> None:
    """Inject accumulated todo_progress snapshots as a single tool_data entry."""
    if todo_progress_accumulated:
        tool_data["tool_data"].append(
            {
                "tool_name": "todo_progress",
                "data": todo_progress_accumulated,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


async def _run_chat_stream(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
    source: Optional[str] = None,
    start_event: Optional[asyncio.Event] = None,
) -> None:
    complete_message = ""
    tool_data: Dict[str, Any] = {"tool_data": []}
    tool_outputs: Dict[str, str] = {}
    todo_progress_accumulated: Dict[str, Any] = {}
    user_message_id = str(uuid4())
    bot_message_id = str(uuid4())
    is_new_conversation = body.conversation_id is None
    usage_metadata: Dict[str, Any] = {}
    follow_up_actions: List[str] = []
    is_cancelled = False

    try:
        description_task = _start_description_task(
            is_new_conversation, body, conversation_id, user
        )

        user_id = user.get("user_id")
        _set_stream_log_context(
            body,
            user_id,
            conversation_id,
            stream_id,
            is_new_conversation,
        )

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
            init_data = f"data: {json.dumps({'user_message_id': user_message_id, 'bot_message_id': bot_message_id, 'stream_id': stream_id})}\n\n"

        if start_event:
            try:
                # Wait for HTTP StreamingResponse to subscribe to Redis Pub/Sub
                await asyncio.wait_for(start_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning(
                    f"Stream {stream_id} HTTP subscriber timeout, proceeding anyway"
                )

        await stream_manager.publish_chunk(stream_id, init_data)
        async for chunk in await call_agent(
            request=body,
            user=user,
            conversation_id=conversation_id,
            user_time=user_time,
            usage_metadata_callback=usage_metadata_callback,
            stream_id=stream_id,
            source=source,
        ):
            if await stream_manager.is_cancelled(stream_id):
                is_cancelled = True
                log.info(f"Stream {stream_id} cancelled by user")
                break

            # Skip [DONE] marker - we send it after description generation
            if chunk == "data: [DONE]\n\n":
                continue

            description_task = await _publish_description_if_ready(
                stream_id, description_task
            )

            # Process complete message marker (internal, not sent to client)
            if chunk.startswith("nostream: "):
                nostream_json = json.loads(chunk.replace("nostream: ", ""))
                if (
                    isinstance(nostream_json, dict)
                    and "complete_message" in nostream_json
                ):
                    complete_message = str(nostream_json["complete_message"])
                else:
                    complete_message = ""
                continue

            if chunk.startswith("data: "):
                try:
                    follow_up_actions, _ = await _process_data_chunk(
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
        total_input, total_output = _aggregate_usage_metadata(usage_metadata)
        log.set(
            model=ModelContext(
                tokens_used=total_input + total_output,
                input_tokens=total_input,
                output_tokens=total_output,
            ),
            response_length=len(complete_message),
            follow_up_actions_count=len(follow_up_actions),
            is_cancelled=is_cancelled,
        )

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
        log.error(f"Background stream error for {stream_id}: {e}")
        # IMPORTANT: Publish error chunk FIRST, before calling set_error()
        # set_error() publishes STREAM_ERROR_SIGNAL which breaks the subscriber loop
        # If we call set_error() first, the error message never reaches the client
        await stream_manager.publish_chunk(
            stream_id, f"data: {json.dumps({'error': str(e)})}\n\n"
        )
        await stream_manager.set_error(stream_id, str(e))
    finally:
        # On cancellation, complete_message may be empty because nostream: marker
        # never arrives. Recover from Redis progress which tracks accumulated text.
        complete_message, tool_data = await _recover_stream_state(
            stream_id, complete_message, tool_data
        )

        # Merge tool outputs into tool_data entries and inject todo_progress before saving
        _merge_tool_outputs(tool_data, tool_outputs)
        _inject_todo_progress(tool_data, todo_progress_accumulated)

        # Always save conversation to MongoDB
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
        conversation_id=conversation_id,  # Use provided ID
    )

    init_data = {
        "conversation_id": conversation_id,
        "conversation_description": conversation.get("description"),
        "user_message_id": user_message_id,
        "bot_message_id": bot_message_id,
        "stream_id": stream_id,  # Include for frontend cancellation
    }

    return f"data: {json.dumps(init_data)}\n\n"


def _extract_response_text(chunk: str) -> str:
    """Extract response text from a data chunk."""
    try:
        if chunk.startswith("data: "):
            chunk = chunk[6:]
        data = json.loads(chunk)
        return data.get("response", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


async def _save_conversation_async(
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    complete_message: str,
    tool_data: Dict[str, Any],
    metadata: Dict[str, Any],
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
            log.error(f"Failed to process token usage: {e}")

    # Get timestamps
    bot_timestamp = datetime.now(timezone.utc)
    user_timestamp = bot_timestamp - timedelta(milliseconds=100)

    # Create user message
    user_content = (
        body.messages[-1].get("content")
        if body.messages and len(body.messages) > 0
        else None
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


def extract_tool_data(json_str: str) -> Dict[str, Any]:
    """
    Parse and extract structured tool output from an agent's JSON response chunk.

    Converts individual tool fields (e.g., calendar_options, search_results, etc.)
    into unified ToolDataEntry array format for consistent frontend handling.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - "tool_data": Array of ToolDataEntry objects (if any tool data found)
            - "other_data": Dict with non-tool fields like follow_up_actions

    Notes:
        - This function converts legacy individual tool fields into the unified tool_data array structure
        - If the JSON is malformed or does not match known tool structures, an empty dict is returned
        - This function is tolerant to missing keys and safe for runtime use in an async stream
    """
    try:
        data = json.loads(json_str)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Step 1: Extract non-tool data (e.g., follow_up_actions)
        other_data: Dict[str, Any] = {}
        if data.get("follow_up_actions") is not None:
            other_data["follow_up_actions"] = data["follow_up_actions"]

        # Step 2: Extract tool_data from one of two sources (in priority order)
        tool_data_entries: List[ToolDataEntry] = []

        # Source A: Already in unified format (from backend tool_data emission)
        if "tool_data" in data:
            # Single entry or list
            td = data["tool_data"]
            if isinstance(td, list):
                tool_data_entries = td
            else:
                tool_data_entries = [td]

        # Source B: Legacy individual tool fields
        else:
            for field_name in tool_fields:
                if data.get(field_name) is not None:
                    tool_data_entries.append(
                        {
                            "tool_name": field_name,
                            "data": data[field_name],
                            "timestamp": timestamp,
                        }
                    )

        # Step 3: Build result from collected data
        result: Dict[str, Any] = {}

        if tool_data_entries:
            result["tool_data"] = tool_data_entries
        if other_data:
            result["other_data"] = other_data

        # Step 4: Extract tool_output events (for merging into tool_data before save)
        if "tool_output" in data:
            result["tool_output"] = data["tool_output"]

        return result

    except json.JSONDecodeError:
        return {}


async def _process_token_usage_and_cost(user_id: str, metadata: Dict[str, Any]) -> None:
    """Process token usage and calculate costs."""
    try:
        subscription = await payment_service.get_user_subscription_status(user_id)
        user_plan = subscription.plan_type or PlanType.FREE

        total_credits = 0.0

        for model_name, usage_data in metadata.items():
            if isinstance(usage_data, dict):
                input_tokens = usage_data.get("input_tokens", 0)
                output_tokens = usage_data.get("output_tokens", 0)

                if input_tokens > 0 or output_tokens > 0:
                    cost_info = await calculate_token_cost(
                        model_name, input_tokens, output_tokens
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
