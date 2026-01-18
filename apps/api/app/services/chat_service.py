"""
Chat service with Redis-backed background streaming.

This module provides two streaming modes:
1. run_chat_stream_background() - Background execution with Redis pub/sub (new)
2. chat_stream() - Legacy direct streaming (kept for backwards compatibility)

Background streaming decouples LangGraph execution from HTTP request lifecycle,
ensuring conversations are always saved even if client disconnects.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from app.agents.core.agent import call_agent
from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.loggers import chat_logger as logger
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
from app.services.file_service import get_files
from app.services.model_service import get_user_selected_model
from app.services.payments.payment_service import payment_service
from app.utils.chat_utils import create_conversation, generate_and_update_description
from langchain_core.callbacks import UsageMetadataCallbackHandler

# =============================================================================
# Background Streaming (New - Redis Pub/Sub)
# =============================================================================


async def run_chat_stream_background(
    stream_id: str,
    body: MessageRequestWithHistory,
    user: dict,
    user_time: datetime,
    conversation_id: str,
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
    complete_message = ""
    tool_data: Dict[str, Any] = {"tool_data": []}
    user_message_id = str(uuid4())
    bot_message_id = str(uuid4())
    is_new_conversation = body.conversation_id is None
    usage_metadata: Dict[str, Any] = {}

    try:
        # Get user model config
        user_id = user.get("user_id")
        user_model_config = None
        if user_id:
            try:
                user_model_config = await get_user_selected_model(user_id)
            except Exception as e:
                logger.warning(f"Could not get user's selected model: {e}")

        usage_metadata_callback = UsageMetadataCallbackHandler()

        # Initialize conversation if new
        if is_new_conversation:
            init_data = await _initialize_new_conversation(
                body=body,
                user=user,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                bot_message_id=bot_message_id,
                stream_id=stream_id,  # Include stream_id for frontend
            )
            await stream_manager.publish_chunk(stream_id, init_data)
        else:
            # Send message IDs and stream_id for existing conversation
            init_data = f"data: {json.dumps({'user_message_id': user_message_id, 'bot_message_id': bot_message_id, 'stream_id': stream_id})}\n\n"
            await stream_manager.publish_chunk(stream_id, init_data)

        # Stream response from agent
        async for chunk in await call_agent(
            request=body,
            user=user,
            conversation_id=conversation_id,
            user_time=user_time,
            user_model_config=user_model_config,
            usage_metadata_callback=usage_metadata_callback,
            stream_id=stream_id,  # For cancellation checking
        ):
            # Check for cancellation
            if await stream_manager.is_cancelled(stream_id):
                logger.info(f"Stream {stream_id} cancelled by user")
                break

            # Skip [DONE] marker - we send it after description generation
            if chunk == "data: [DONE]\n\n":
                continue

            # Process complete message marker (internal, not sent to client)
            if chunk.startswith("nostream: "):
                chunk_json = json.loads(chunk.replace("nostream: ", ""))
                complete_message = chunk_json.get("complete_message", "")
                continue

            # Process and publish data chunks
            if chunk.startswith("data: "):
                try:
                    new_data = extract_tool_data(chunk[6:])
                    if new_data and "tool_data" in new_data:
                        for tool_entry in new_data["tool_data"]:
                            tool_data["tool_data"].append(tool_entry)
                            await stream_manager.publish_chunk(
                                stream_id,
                                f"data: {json.dumps({'tool_data': tool_entry})}\n\n",
                            )
                    else:
                        await stream_manager.publish_chunk(stream_id, chunk)

                    # Update progress for recovery
                    response_text = _extract_response_text(chunk)
                    if response_text:
                        await stream_manager.update_progress(
                            stream_id,
                            message_chunk=response_text,
                            tool_data=new_data,
                        )
                except Exception as e:
                    logger.error(f"Error processing chunk: {e}")
                    await stream_manager.publish_chunk(stream_id, chunk)
            else:
                await stream_manager.publish_chunk(stream_id, chunk)

        # Get usage metadata
        usage_metadata = usage_metadata_callback.usage_metadata or {}

        # Generate description for new conversations
        if is_new_conversation:
            try:
                last_message = body.messages[-1] if body.messages else None
                description = await generate_and_update_description(
                    conversation_id,
                    last_message,
                    user,
                    body.selectedTool,
                    body.selectedWorkflow,
                )
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'conversation_description': description})}\n\n",
                )
            except Exception as e:
                logger.error(f"Failed to generate description: {e}")

        # Mark stream complete
        await stream_manager.complete_stream(stream_id)

    except Exception as e:
        logger.error(f"Background stream error for {stream_id}: {e}")
        await stream_manager.set_error(stream_id, str(e))
        await stream_manager.publish_chunk(
            stream_id, f"data: {json.dumps({'error': str(e)})}\n\n"
        )
    finally:
        # On cancellation, complete_message may be empty because nostream: marker
        # never arrives. Recover from Redis progress which tracks accumulated text.
        if not complete_message:
            progress = await stream_manager.get_progress(stream_id)
            if progress:
                complete_message = progress.get("complete_message", "")
                # Also recover tool_data if we have it
                if progress.get("tool_data"):
                    tool_data = progress["tool_data"]
                logger.debug(
                    f"Recovered {len(complete_message)} chars from Redis progress"
                )

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

        logger.info(f"Background stream {stream_id} completed and saved")


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
    """
    Save conversation to MongoDB (called from background task).

    This is the async version of update_conversation_messages,
    called directly instead of via BackgroundTasks.
    """
    user_id = user.get("user_id")

    # Process token usage
    if metadata and user_id:
        try:
            await _process_token_usage_and_cost(user_id, metadata)
        except Exception as e:
            logger.error(f"Failed to process token usage: {e}")

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


# =============================================================================
# Shared Utilities
# =============================================================================


def extract_tool_data(json_str: str) -> Dict[str, Any]:
    """
    Parse and extract structured tool output from an agent's JSON response chunk.
    """
    try:
        data = json.loads(json_str)

        if "tool_data" in data:
            return {"tool_data": data["tool_data"]}

        tool_data_entries = []
        timestamp = datetime.now(timezone.utc).isoformat()

        for field_name in tool_fields:
            if field_name in data and data[field_name] is not None:
                tool_entry: ToolDataEntry = {
                    "tool_name": field_name,
                    "data": data[field_name],
                    "timestamp": timestamp,
                }
                tool_data_entries.append(tool_entry)

        if tool_data_entries:
            return {"tool_data": tool_data_entries}

        return {}

    except json.JSONDecodeError:
        return {}


async def initialize_conversation(
    body: MessageRequestWithHistory, user: dict
) -> tuple[str, Optional[str], str, str]:
    """Initialize a conversation or use an existing one."""
    conversation_id = body.conversation_id or None
    init_chunk = None
    user_message_id = str(uuid4())
    bot_message_id = str(uuid4())

    if conversation_id is None:
        last_message = body.messages[-1] if body.messages else None

        conversation = await create_conversation(
            last_message,
            user=user,
            selectedTool=body.selectedTool,
            selectedWorkflow=body.selectedWorkflow,
            generate_description=False,
        )
        conversation_id = conversation.get("conversation_id", "")

        init_chunk = f"""data: {
            json.dumps(
                {
                    "conversation_id": conversation_id,
                    "conversation_description": conversation.get("description"),
                    "user_message_id": user_message_id,
                    "bot_message_id": bot_message_id,
                }
            )
        }\n\n"""

        return conversation_id, init_chunk, user_message_id, bot_message_id

    init_chunk = f"""data: {
        json.dumps(
            {
                "user_message_id": user_message_id,
                "bot_message_id": bot_message_id,
            }
        )
    }\n\n"""

    uploaded_files = await get_files(
        user_id=user.get("user_id"),
        conversation_id=conversation_id,
    )
    logger.info(f"{uploaded_files=}")

    return conversation_id, init_chunk, user_message_id, bot_message_id


def update_conversation_messages(
    background_tasks: Any,
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    complete_message: str,
    tool_data: Dict[str, Any] = {},
    metadata: Dict[str, Any] = {},
    user_message_id: Optional[str] = None,
    bot_message_id: Optional[str] = None,
) -> None:
    """Schedule conversation update in the background (legacy)."""
    if metadata and user.get("user_id"):
        background_tasks.add_task(
            _process_token_usage_and_cost, user_id=user["user_id"], metadata=metadata
        )

    bot_timestamp = datetime.now(timezone.utc)
    user_timestamp = bot_timestamp - timedelta(milliseconds=100)

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

    if user_message_id:
        user_message.message_id = user_message_id

    bot_message = MessageModel(
        type="bot",
        response=complete_message,
        date=bot_timestamp.isoformat(),
        fileIds=body.fileIds,
        metadata=metadata,
    )

    if bot_message_id:
        bot_message.message_id = bot_message_id

    if tool_data:
        for key, value in tool_data.items():
            setattr(bot_message, key, value)

    background_tasks.add_task(
        update_messages,
        UpdateMessagesRequest(
            conversation_id=conversation_id,
            messages=[user_message, bot_message],
        ),
        user=user,
    )


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

    except Exception as e:
        logger.debug(f"Token usage processing failed: {e}")
