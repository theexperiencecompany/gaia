import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import uuid4

from app.agents.core.agent import call_agent
from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.loggers import chat_logger as logger
from app.config.model_pricing import calculate_token_cost
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
from fastapi import BackgroundTasks
from langchain_core.callbacks import UsageMetadataCallbackHandler


async def chat_stream(
    body: MessageRequestWithHistory,
    user: dict,
    background_tasks: BackgroundTasks,
    user_time: datetime,
) -> AsyncGenerator:
    """
    Stream chat messages in real-time.

    Returns:
        StreamingResponse: A streaming response containing the LLM's generated content
    """
    complete_message = ""
    (
        conversation_id,
        init_chunk,
        user_message_id,
        bot_message_id,
    ) = await initialize_conversation(body, user)
    is_new_conversation = body.conversation_id is None

    # Dictionary to collect tool outputs during streaming
    tool_data: Dict[str, Any] = {"tool_data": []}

    if init_chunk:  # Return the conversation id and metadata if new convo
        yield init_chunk

    logger.info(
        f"User {user.get('user_id')} started a conversation with ID {conversation_id}"
    )

    # Start description generation immediately as a background task for new conversations
    description_task = None
    if is_new_conversation:
        last_message = body.messages[-1] if body.messages else None
        selectedTool = body.selectedTool if body.selectedTool else None
        selectedWorkflow = body.selectedWorkflow if body.selectedWorkflow else None

        description_task = asyncio.create_task(
            generate_and_update_description(
                conversation_id,
                last_message,
                user,
                selectedTool,
                selectedWorkflow,
            )
        )

    user_id = user.get("user_id")
    user_model_config = None
    if user_id:
        try:
            user_model_config = await get_user_selected_model(user_id)
        except Exception as e:
            logger.warning(f"Could not get user's selected model, using default: {e}")

    usage_metadata_callback = UsageMetadataCallbackHandler()

    # Stream response from the agent
    async for chunk in await call_agent(
        request=body,
        user=user,
        conversation_id=conversation_id,
        user_time=user_time,
        user_model_config=user_model_config,
        usage_metadata_callback=usage_metadata_callback,
    ):
        # Check if description is ready and send it immediately
        if description_task and description_task.done():
            try:
                description = description_task.result()
                yield f"""data: {json.dumps({"conversation_description": description})}\n\n"""
                description_task = None  # Clear task after yielding
            except Exception as e:
                logger.error(f"Failed to get conversation description: {e}")
                description_task = None  # Clear task to avoid retry

        # Skip [DONE] marker from agent - we'll send it after description generation
        if chunk == "data: [DONE]\n\n":
            continue

        # Process complete message marker (for DB storage)
        if chunk.startswith("nostream: "):
            chunk_json = json.loads(chunk.replace("nostream: ", ""))
            complete_message = chunk_json.get("complete_message", "")

        # Process and yield data chunks (tool outputs, responses, etc.)
        elif chunk.startswith("data: "):
            try:
                # Extract tool data from the chunk
                new_data = extract_tool_data(chunk[6:])
                if new_data:
                    current_time = datetime.now(timezone.utc).isoformat()

                    # Handle unified tool_data format
                    if "tool_data" in new_data:
                        # new_data["tool_data"] is already a list of ToolDataEntry objects
                        for tool_entry in new_data["tool_data"]:
                            tool_data["tool_data"].append(tool_entry)

                            # Check if this is a progress event (tool_calls_data)
                            # Progress events are streamed directly - yield original chunk
                            # and don't re-emit as tool_data to avoid duplication
                            if tool_entry.get("tool_name") == "tool_calls_data":
                                yield chunk
                                continue

                            current_tool_data = {"tool_data": tool_entry}
                            yield f"data: {json.dumps(current_tool_data)}\n\n"
                    else:
                        # Handle legacy individual fields (shouldn't happen with new extract_tool_data, but kept for safety)
                        for key, value in new_data.items():
                            if key == "follow_up_actions":
                                yield chunk
                                continue  # Skip adding follow-up actions to tool_data

                            tool_data_entry: ToolDataEntry = {
                                "tool_name": key,
                                "data": value,
                                "timestamp": current_time,
                            }
                            tool_data["tool_data"].append(tool_data_entry)

                            current_tool_data = {"tool_data": tool_data_entry}
                            yield f"data: {json.dumps(current_tool_data)}\n\n"
                else:
                    yield chunk

            except Exception as e:
                logger.error(f"Error extracting tool data: {e}")

        # Pass through other chunks
        else:
            yield chunk

    # Await and stream description if not already sent
    if description_task:
        try:
            description = await description_task
            # Stream the updated description
            yield f"""data: {json.dumps({"conversation_description": description})}\n\n"""
        except Exception as e:
            logger.error(f"Failed to generate conversation description: {e}")

    # Now send [DONE] marker
    yield "data: [DONE]\n\n"

    # Save the conversation once streaming is complete
    update_conversation_messages(
        background_tasks,
        body,
        user,
        conversation_id,
        complete_message,
        tool_data,
        metadata=usage_metadata_callback.usage_metadata,
        user_message_id=user_message_id,
        bot_message_id=bot_message_id,
    )


def extract_tool_data(json_str: str) -> Dict[str, Any]:
    """
    Parse and extract structured tool output from an agent's JSON response chunk.

    Converts individual tool fields (e.g., calendar_options, search_results, etc.)
    into unified ToolDataEntry array format for consistent frontend handling.

    Returns:
        Dict[str, Any]: A dictionary containing tool_data array with ToolDataEntry objects.

    Notes:
        - This function converts legacy individual tool fields into the unified tool_data array structure
        - If the JSON is malformed or does not match known tool structures, an empty dict is returned
        - This function is tolerant to missing keys and safe for runtime use in an async stream
    """
    try:
        from datetime import datetime, timezone

        data = json.loads(json_str)

        # If tool_data already exists in unified format, return it directly
        if "tool_data" in data:
            return {"tool_data": data["tool_data"]}

        # Handle progress events - convert to tool_calls_data format for persistence
        if "progress" in data and isinstance(data["progress"], dict):
            progress = data["progress"]
            if progress.get("tool_name"):
                timestamp = datetime.now(timezone.utc).isoformat()
                tool_entry: ToolDataEntry = {
                    "tool_name": "tool_calls_data",
                    "data": {
                        "tool_name": progress.get("tool_name"),
                        "tool_category": progress.get("tool_category", ""),
                        "message": progress.get("message", ""),
                        "show_category": progress.get("show_category", True),
                        "tool_call_id": progress.get("tool_call_id"),
                        "inputs": progress.get("inputs"),
                        "icon_url": progress.get("icon_url"),
                        "integration_name": progress.get("integration_name"),
                    },
                    "timestamp": timestamp,
                }
                return {"tool_data": [tool_entry]}

        # Map of legacy field names to their new unified tool names

        tool_data_entries = []
        timestamp = datetime.now(timezone.utc).isoformat()

        # Convert individual tool fields to unified format
        for field_name in tool_fields:
            if field_name in data and data[field_name] is not None:
                tool_entry: ToolDataEntry = {
                    "tool_name": field_name,
                    "data": data[field_name],
                    "timestamp": timestamp,
                }
                tool_data_entries.append(tool_entry)

        # Return unified format if any tool data was found
        if tool_data_entries:
            return {"tool_data": tool_data_entries}

        return {}

    except json.JSONDecodeError:
        return {}


async def initialize_conversation(
    body: MessageRequestWithHistory, user: dict
) -> tuple[str, Optional[str], str, str]:
    """
    Initialize a conversation or use an existing one.

    Args:
        body: The request body
        user: User information

    Returns:
        Tuple of conversation ID and initialization chunk (if any)
    """
    conversation_id = body.conversation_id or None
    init_chunk = None

    # ALWAYS generate message IDs on backend for consistency
    user_message_id = str(uuid4())
    bot_message_id = str(uuid4())

    if conversation_id is None:
        last_message = body.messages[-1] if body.messages else None
        selectedTool = body.selectedTool if body.selectedTool else None
        selectedWorkflow = body.selectedWorkflow if body.selectedWorkflow else None

        # Create conversation with temporary "New Chat" description to start streaming immediately
        # Real description will be generated and streamed after the main response completes
        conversation = await create_conversation(
            last_message,
            user=user,
            selectedTool=selectedTool,
            selectedWorkflow=selectedWorkflow,
            generate_description=False,  # Don't block on LLM description generation
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

    # For existing conversations, send message IDs as first stream event
    init_chunk = f"""data: {
        json.dumps(
            {
                "user_message_id": user_message_id,
                "bot_message_id": bot_message_id,
            }
        )
    }\n\n"""

    # Load files and old messages if conversation_id is provided
    uploaded_files = await get_files(
        user_id=user.get("user_id"),
        conversation_id=conversation_id,
    )

    logger.info(f"{uploaded_files=}")

    return conversation_id, init_chunk, user_message_id, bot_message_id


def update_conversation_messages(
    background_tasks: BackgroundTasks,
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    complete_message: str,
    tool_data: Dict[str, Any] = {},
    metadata: Dict[str, Any] = {},
    user_message_id: Optional[str] = None,
    bot_message_id: Optional[str] = None,
) -> None:
    """
    Schedule conversation update in the background.

    Args:
        background_tasks: FastAPI background task handler
        body: Request body
        user: User information
        conversation_id: ID of the conversation to update
        complete_message: Complete LLM-generated message
        tool_data: Structured tool output data to store with the message
        metadata: Token usage metadata from LLM calls by model
        user_message_id: Optional pre-generated ID for user message
        bot_message_id: Optional pre-generated ID for bot message
    """
    # Process token usage and calculate total cost in background
    if metadata and user.get("user_id"):
        background_tasks.add_task(
            _process_token_usage_and_cost, user_id=user["user_id"], metadata=metadata
        )

    # Get timestamps - user message slightly before bot message to ensure correct ordering
    bot_timestamp = datetime.now(timezone.utc)
    user_timestamp = bot_timestamp - timedelta(milliseconds=100)

    # Create user message - handle case where messages array might be empty due to tool selection
    user_content = body.messages[-1]["content"] if body.messages else body.message
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

    # Set message_id if provided from init_chunk
    if user_message_id:
        user_message.message_id = user_message_id

    # Create bot message with base properties
    bot_message = MessageModel(
        type="bot",
        response=complete_message,
        date=bot_timestamp.isoformat(),
        fileIds=body.fileIds,
        metadata=metadata,
    )

    # Set message_id if provided from init_chunk
    if bot_message_id:
        bot_message.message_id = bot_message_id

    # Apply tool data fields to bot message if available
    if tool_data:
        # Use dictionary unpacking for cleaner application of fields
        for key, value in tool_data.items():
            setattr(bot_message, key, value)

    # Schedule the DB update as a background task
    background_tasks.add_task(
        update_messages,
        UpdateMessagesRequest(
            conversation_id=conversation_id,
            messages=[user_message, bot_message],
        ),
        user=user,
    )


async def _process_token_usage_and_cost(user_id: str, metadata: Dict[str, Any]) -> None:
    """
    Background task to process token usage, calculate total cost, and store in DB.
    This is the main flow: get model + tokens from metadata → calculate total cost → store in DB
    We now track credits (costs) rather than raw token counts for billing purposes.
    """
    try:
        # Get user subscription
        subscription = await payment_service.get_user_subscription_status(user_id)
        user_plan = subscription.plan_type or PlanType.FREE

        total_credits = 0.0

        # Calculate costs for each model and collect totals
        for model_name, usage_data in metadata.items():
            if isinstance(usage_data, dict):
                input_tokens = usage_data.get("input_tokens", 0)
                output_tokens = usage_data.get("output_tokens", 0)

                if input_tokens > 0 or output_tokens > 0:
                    # Calculate cost for this specific model
                    # Note: get_model_pricing handles model name variants
                    cost_info = await calculate_token_cost(
                        model_name, input_tokens, output_tokens
                    )
                    model_cost = cost_info["total_cost"]
                    total_credits += model_cost

        # If credits were used, track them
        if total_credits > 0:
            # Single entry for all usage with credits
            await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key="chat_messages",
                user_plan=user_plan,
                credits_used=total_credits,
            )

    except Exception as e:
        logger.debug(f"Background task failed during deduction: {e}")
