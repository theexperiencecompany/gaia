"""Core agent helper functions for LangGraph execution and configuration.

Provides essential building blocks for agent execution including configuration
building, state initialization, and graph execution in both streaming and silent modes.

These functions are tightly coupled to agent-specific logic and LangGraph execution.
"""

import json
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.messages import AIMessageChunk, ToolMessage
from langsmith import traceable
from opik.integrations.langchain import OpikTracer
from posthog.ai.langchain import CallbackHandler as PostHogCallbackHandler

from app.config.settings import settings
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
)
from app.core.lazy_loader import providers
from app.models.models_models import ModelConfig
from app.utils.agent_utils import (
    format_sse_data,
    format_sse_response,
    format_tool_progress,
    process_custom_event_for_tools,
    store_agent_progress,
)


def build_agent_config(
    conversation_id: str,
    user: dict,
    user_time: datetime,
    agent_name: str,
    user_model_config: Optional[ModelConfig] = None,
    usage_metadata_callback: Optional[UsageMetadataCallbackHandler] = None,
    thread_id: Optional[str] = None,
    base_configurable: Optional[dict] = None,
    selected_tool: Optional[str] = None,
    tool_category: Optional[str] = None,
) -> dict:
    """Build configuration for graph execution with optional authentication tokens.

    Creates a comprehensive configuration object for LangGraph execution that includes
    user context, model settings, authentication tokens, and execution parameters.

    Args:
        conversation_id: Unique identifier for the conversation thread
        user: User information dictionary containing user_id and email
        user_time: Current datetime for the user's timezone
        user_model_config: Optional model configuration with provider and token limits
        thread_id: Optional override for thread_id (defaults to conversation_id)
        base_configurable: Optional base configurable to inherit from (for child agents)
        selected_tool: Optional tool name selected via slash command
        tool_category: Optional category of the selected tool

    Returns:
        Configuration dictionary formatted for LangGraph execution with configurable
        parameters, metadata, and recursion limits
    """

    callbacks: list[BaseCallbackHandler] = []

    # Add OpikTracer in production, or in development only if configured
    # This prevents cluttered error logs when Opik isn't set up locally
    is_opik_configured = settings.OPIK_API_KEY and settings.OPIK_WORKSPACE
    if settings.ENV == "production" or is_opik_configured:
        callbacks.append(
            OpikTracer(
                tags=["langchain", settings.ENV],
                thread_id=conversation_id,
                metadata={
                    "user_id": user.get("user_id"),
                    "conversation_id": conversation_id,
                    "agent_name": agent_name,
                },
                project_name="GAIA",
            )
        )
    posthog_client = providers.get("posthog")

    if posthog_client is not None:
        callbacks.append(
            PostHogCallbackHandler(
                client=posthog_client,
                distinct_id=user.get("user_id"),
                properties={
                    "conversation_id": conversation_id,
                    "agent_name": agent_name,
                },
                privacy_mode=False,
            ),
        )

    if usage_metadata_callback:
        callbacks.append(usage_metadata_callback)

    model_name = (
        user_model_config.provider_model_name
        if user_model_config
        else DEFAULT_MODEL_NAME
    )
    provider_name = (
        user_model_config.inference_provider.value
        if user_model_config
        else DEFAULT_LLM_PROVIDER
    )
    max_tokens = (
        user_model_config.max_tokens if user_model_config else DEFAULT_MAX_TOKENS
    )

    # Cherry-pick specific keys from base_configurable if provided
    # Only inherit model config and user context, not LangChain internal state
    if base_configurable:
        # Inherit model config from parent if not overridden
        provider_name = base_configurable.get("provider", provider_name)
        max_tokens = base_configurable.get("max_tokens", max_tokens)
        model_name = base_configurable.get("model_name", model_name)
        selected_tool = selected_tool or base_configurable.get("selected_tool")
        tool_category = tool_category or base_configurable.get("tool_category")

    configurable = {
        "thread_id": thread_id or conversation_id,
        "user_id": user.get("user_id"),
        "email": user.get("email"),
        "user_name": user.get("name", ""),
        "user_time": user_time.isoformat(),
        "provider": provider_name,
        "max_tokens": max_tokens,
        "model_name": model_name,
        "model": model_name,
        "selected_tool": selected_tool,
        "tool_category": tool_category,
    }

    config = {
        "configurable": configurable,
        "recursion_limit": 25,
        "metadata": {"user_id": user.get("user_id")},
        "callbacks": callbacks,
        "agent_name": agent_name,
    }

    return config


def build_initial_state(
    request,
    user_id: str,
    conversation_id: str,
    history,
    trigger_context: Optional[dict] = None,
) -> dict:
    """Construct initial state dictionary for LangGraph execution.

    Builds the starting state containing all necessary context for the agent
    including user query, conversation history, tool selections, and optional
    workflow trigger context.

    Args:
        request: Message request object containing user message and selections
        user_id: Unique identifier for the user
        conversation_id: Unique identifier for the conversation thread
        history: List of previous messages in LangChain format
        trigger_context: Optional context data from workflow triggers

    Returns:
        State dictionary with query, messages, datetime, user context, and
        selected tools/workflows for graph processing
    """
    state = {
        "query": request.message,
        "messages": history,
        "current_datetime": datetime.now(timezone.utc).isoformat(),
        "mem0_user_id": user_id,
        "conversation_id": conversation_id,
        "selected_tool": request.selectedTool,
        "selected_workflow": request.selectedWorkflow,
        "selected_calendar_event": request.selectedCalendarEvent,
    }

    if trigger_context:
        state["trigger_context"] = trigger_context

    return state


@traceable(run_type="llm", name="Call Agent Silent")
async def execute_graph_silent(
    graph,
    initial_state: dict,
    config: dict,
) -> tuple[str, dict]:
    """Execute LangGraph in silent mode with real-time progress storage.

    Runs the agent graph asynchronously and accumulates all results including
    the complete message content and extracted tool data. Used for background
    processing and workflow triggers where real-time streaming is not needed.

    Stores intermediate messages and tool outputs as they happen during execution,
    using the same storage patterns as normal chat.

    Args:
        graph: LangGraph instance to execute
        initial_state: Starting state dictionary with query and context
        config: Configuration dictionary with user context and settings

    Returns:
        Tuple containing:
        - complete_message: Full response text accumulated from all chunks
        - tool_data: Dictionary of extracted tool execution data and results
    """
    complete_message = ""
    tool_data = {}

    # Get storage context from config
    conversation_id = config.get("configurable", {}).get("thread_id")
    user_id = config.get("configurable", {}).get("user_id")

    async for event in graph.astream(
        initial_state,
        stream_mode=["messages", "custom"],
        config=config,
        subgraphs=True,
    ):
        ns, stream_mode, payload = event

        if stream_mode == "messages":
            chunk, metadata = payload

            if metadata.get("silent"):
                continue  # Skip silent chunks (e.g. follow-up actions generation)

            if chunk and isinstance(chunk, AIMessageChunk):
                content = str(chunk.content)
                if content:
                    complete_message += content

        elif stream_mode == "custom":
            new_data = process_custom_event_for_tools(payload)
            if new_data:
                tool_data.update(new_data)

                # Store progress immediately when tool completes (same pattern as chat)
                if conversation_id and user_id:
                    await store_agent_progress(
                        conversation_id, user_id, complete_message, tool_data
                    )

    return complete_message, tool_data


@traceable(run_type="llm", name="Call Agent")
async def execute_graph_streaming(
    graph,
    initial_state: dict,
    config: dict,
) -> AsyncGenerator[str, None]:
    """Execute LangGraph in streaming mode with real-time output.

    Runs the agent graph and yields Server-Sent Events (SSE) formatted updates
    as they occur. Handles both message content streaming and tool execution
    progress updates. Only yields content from the main agent to avoid duplication
    from subgraphs.

    Tool progress is emitted incrementally:
    1. When tool_call first detected: emit name/category (progress event)
    2. When ToolMessage arrives: emit inputs (tool_inputs event) + output (tool_output event)

    Args:
        graph: LangGraph instance to execute
        initial_state: Starting state dictionary with query and context
        config: Configuration dictionary with user context and settings

    Yields:
        SSE-formatted strings containing:
        - Real-time message content as it's generated
        - Tool execution progress updates
        - Custom events from tool executions
        - Final completion marker and accumulated message
    """
    complete_message = ""
    # Track pending tool calls: id -> {name, args}
    pending_tool_calls: dict[str, dict] = {}

    async for event in graph.astream(
        initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=config,
        subgraphs=True,
    ):
        # Handle both 2-tuple and 3-tuple (with subgraphs=True)
        if len(event) == 3:
            ns, stream_mode, payload = event
        elif len(event) == 2:
            stream_mode, payload = event
        else:
            continue

        # Capture complete tool_calls args from updates stream
        if stream_mode == "updates":
            # Updates contain node_name -> state_update
            for node_name, state_update in payload.items():
                if isinstance(state_update, dict) and "messages" in state_update:
                    for msg in state_update["messages"]:
                        # Check if it's an AIMessage with tool_calls
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tc_id = tc.get("id")
                                if tc_id:
                                    # Store complete args for this tool call
                                    pending_tool_calls[tc_id] = {
                                        "name": tc.get("name"),
                                        "args": tc.get("args", {}),
                                    }
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            if chunk and isinstance(chunk, AIMessageChunk):
                content = str(chunk.content)
                tool_calls = chunk.tool_calls

                # Track tool calls and emit progress on first detection
                if tool_calls:
                    for tool_call in tool_calls:
                        tc_id = tool_call.get("id")
                        if tc_id and tc_id not in pending_tool_calls:
                            # First time seeing this tool call - emit progress
                            progress_data = await format_tool_progress(tool_call)
                            if progress_data:
                                yield format_sse_data(progress_data)

                            # Store for later when ToolMessage arrives
                            pending_tool_calls[tc_id] = {
                                "name": tool_call.get("name"),
                                "args": tool_call.get("args", {}),
                            }
                        elif tc_id:
                            # Update stored args (they accumulate across chunks)
                            pending_tool_calls[tc_id]["args"] = tool_call.get(
                                "args", {}
                            )

                # Only yield content from main agent to avoid duplication
                if content and metadata.get("agent_name") == "comms_agent":
                    yield format_sse_response(content)
                    complete_message += content

            # Capture tool outputs from ToolMessage
            elif chunk and isinstance(chunk, ToolMessage):
                tc_id = chunk.tool_call_id

                # Emit tool_inputs now that tool has executed with complete args
                if tc_id and tc_id in pending_tool_calls:
                    stored_call = pending_tool_calls[tc_id]
                    if stored_call.get("args"):
                        tool_inputs_data = {
                            "tool_inputs": {
                                "tool_call_id": tc_id,
                                "inputs": stored_call["args"],
                            }
                        }
                        yield format_sse_data(tool_inputs_data)
                    del pending_tool_calls[tc_id]

                # Emit tool output
                tool_output_data = {
                    "tool_output": {
                        "tool_call_id": tc_id,
                        "output": chunk.content[:1000]
                        if isinstance(chunk.content, str)
                        else str(chunk.content)[:1000],
                    }
                }
                yield format_sse_data(tool_output_data)

        elif stream_mode == "custom":
            # Skip progress events that have tool_call_id - they're already handled
            # via messages stream. This prevents duplication from subagent forwarding.
            # Progress without tool_call_id (like handoff messages) are allowed through.
            if isinstance(payload, dict) and "progress" in payload:
                progress = payload.get("progress", {})
                if isinstance(progress, dict) and progress.get("tool_call_id"):
                    continue
            # Forward other custom events as-is
            yield f"data: {json.dumps(payload)}\n\n"

    # Get token metadata after streaming completes and yield complete message for DB storage
    message_data = {"complete_message": complete_message}

    message_data = {**message_data}

    yield f"nostream: {json.dumps(message_data)}"
    yield "data: [DONE]\n\n"
