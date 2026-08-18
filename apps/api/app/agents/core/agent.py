"""Agent execution: streaming and silent modes.

- call_agent() returns an AsyncGenerator for SSE streaming (interactive chat).
- call_agent_silent() returns a results tuple (workflows, background tasks).

Both share _core_agent_logic() for common setup (messages, graph, config).
"""

import asyncio
from collections.abc import AsyncGenerator
import json
from typing import Any, cast
from uuid import uuid4

from langchain_core.callbacks import UsageMetadataCallbackHandler

from app.agents.core.background.executor_capture import (
    await_executor_done,
    drain_executor_tool_data,
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.messages import construct_langchain_messages
from app.agents.llm.lane import AgentRole, dev_model_id, dev_option_for
from app.config.langfuse import trace_id_for_message
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import (
    build_agent_config,
    build_initial_state,
    execute_graph_silent,
    execute_graph_streaming,
    recent_user_messages,
)
from app.models.agent_models import (
    AgentConfigurable,
    AgentRunnableConfig,
    ExecutionMode,
    agent_configurable,
)
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.wide_events import log


async def _core_agent_logic(
    request: MessageRequestWithHistory,
    conversation_id: str,
    user: AuthenticatedUser,
    trigger_context: dict[str, Any] | None = None,
    usage_metadata_callback: UsageMetadataCallbackHandler | None = None,
    source: str | None = None,
    langfuse_trace_id: str | None = None,
    langfuse_tags: list[str] | None = None,
) -> tuple[CompiledAgentGraph, dict[str, Any], AgentRunnableConfig]:
    """Shared setup for streaming and silent execution.

    Constructs messages, initializes the graph, builds state, and kicks off
    background memory storage.

    Args:
        request: Message request with conversation history and file data
        conversation_id: Unique identifier for the conversation thread
        user: User information dictionary with ID, email, name, and home timezone
        trigger_context: Optional context data from workflow triggers
        langfuse_trace_id: Seed for the Langfuse trace; forwarded into the
            config metadata + configurable so child agents inherit it.
        langfuse_tags: Tags applied to the Langfuse trace root.

    Returns:
        Tuple containing:
        - graph: Initialized LangGraph instance ready for execution
        - initial_state: Prepared state dictionary with all context
        - config: Configuration dictionary with user settings and tokens
    """
    user_id = user.get("user_id")

    # Extract active todo binding + execution mode from trigger_context (scheduled
    # runs set these; interactive turns leave them unset / "interactive").
    active_todo_id: str | None = None
    execution_mode: ExecutionMode = "interactive"
    if trigger_context:
        active_todo_id = trigger_context.get("active_todo_id") or trigger_context.get("todo_id")
        mode = trigger_context.get("execution_mode")
        if mode in ("interactive", "background"):
            execution_mode = cast(ExecutionMode, mode)

    # Build langchain messages and get graph concurrently
    history, graph = await asyncio.gather(
        construct_langchain_messages(
            messages=request.messages,
            files_data=request.fileData,
            currently_uploaded_file_ids=request.fileIds,
            user_id=user_id,
            query=request.message,
            user_name=user.get("name"),
            user_dict=user,
            selected_tool=request.selectedTool,
            tool_category=request.toolCategory,
            selected_workflow=request.selectedWorkflow,
            selected_calendar_event=request.selectedCalendarEvent,
            reply_to_message=request.replyToMessage,
            trigger_context=trigger_context,
            active_todo_id=active_todo_id,
            execution_mode=execution_mode,
            conversation_id=conversation_id,
            source=source,
        ),
        GraphManager.get_graph("comms_agent"),
    )

    initial_state = build_initial_state(
        request, user_id or "", conversation_id, history, trigger_context
    )

    # DEV-ONLY: the chat-header model selector picks a model per role. It wins over
    # plan routing inside resolve_lane. Never reached in production.
    dev_option = (
        dev_option_for(request.comms_model, request.use_default_models)
        if settings.ENV == "development"
        else None
    )

    # Established here (comms already has the full user document) so the
    # executor and every subagent it hands off to inherit it — the worker
    # tiers' context sections read it off configurable, not off a user doc
    # they never have.
    user_preferences, writing_style = onboarding_preferences(user.get("onboarding"))

    # This is the top-level run, so build_agent_config resolves the comms lane
    # here; the executor and every subagent inherit it whole.
    config = await build_agent_config(
        conversation_id=conversation_id,
        user=user,
        role=AgentRole.COMMS,
        dev_option=dev_option,
        usage_metadata_callback=usage_metadata_callback,
        agent_name="comms_agent",
        selected_tool=request.selectedTool,
        tool_category=request.toolCategory,
        active_todo_id=active_todo_id,
        execution_mode=execution_mode,
        source=source,
        user_messages=recent_user_messages(request.messages, request.message),
        user_preferences=user_preferences,
        writing_style=writing_style,
        langfuse_trace_id=langfuse_trace_id,
        langfuse_tags=langfuse_tags,
    )

    # The live bag build_agent_config just produced — mutated below, so it is
    # indexed (KeyError if absent) rather than read via agent_configurable,
    # whose empty-dict fallback would swallow the writes.
    configurable = cast(AgentConfigurable, config["configurable"])

    # DEV-ONLY: the executor builds its own configurable and would otherwise
    # inherit comms's lane, so the executor's own dev choice rides down here and
    # prepare_executor_execution resolves it into that run's lane.
    if settings.ENV == "development" and (
        executor_dev := dev_model_id(request.executor_model, request.use_default_models)
    ):
        configurable["dev_executor_model"] = executor_dev

    # Workflow runs carry their id/title so the background executor's delivery
    # path can route the final result to the workflow-completion notification
    # instead of a normal conversation message. Absent for interactive chat.
    if trigger_context and trigger_context.get("workflow_id"):
        configurable["workflow_id"] = trigger_context["workflow_id"]
        configurable["workflow_title"] = trigger_context.get("workflow_title", "")
        configurable["workflow_notify_on_completion"] = trigger_context.get(
            "workflow_notify_on_completion", True
        )

    log.set(
        agent=dict(
            model=configurable.get("model"),
            has_workflow=bool(request.selectedWorkflow),
            has_trigger_context=bool(trigger_context),
            has_calendar_event=bool(request.selectedCalendarEvent),
            has_reply=bool(request.replyToMessage),
            history_message_count=len(history),
        )
    )

    return graph, initial_state, config


async def call_agent(
    request: MessageRequestWithHistory,
    conversation_id: str,
    user: AuthenticatedUser,
    usage_metadata_callback: UsageMetadataCallbackHandler | None = None,
    stream_id: str | None = None,
    user_message_id: str | None = None,
    bot_message_id: str | None = None,
    source: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Execute agent in streaming mode for interactive chat.

    Args:
        stream_id: Optional stream ID for Redis-based cancellation checking.
                   When provided, streaming can be cancelled via stream_manager.
        user_message_id: Optional user message ID for reply-to linking in
                         background notifications.
        bot_message_id: Assistant message ID used to seed the Langfuse
                        trace_id so /messages/{id}/feedback can re-derive
                        the same trace_id to attach scores.

    Returns an AsyncGenerator that yields SSE-formatted streaming data.
    """
    user_id = user.get("user_id")
    try:
        langfuse_trace_id = trace_id_for_message(bot_message_id) if bot_message_id else None

        graph, initial_state, config = await _core_agent_logic(
            request,
            conversation_id,
            user,
            usage_metadata_callback=usage_metadata_callback,
            source=source,
            langfuse_trace_id=langfuse_trace_id,
            langfuse_tags=["comms_agent", settings.ENV],
        )

        # The live bag (see the same cast in _core_agent_logic) — mutated, so
        # indexed rather than read through agent_configurable.
        configurable = cast(AgentConfigurable, config["configurable"])

        # Add stream_id to config for cancellation checking
        if stream_id:
            configurable["stream_id"] = stream_id

        # Add user_message_id so executor can link notifications back
        if user_message_id:
            configurable["user_message_id"] = user_message_id

        # Add bot_message_id so a HIL pause on this turn's executor can later
        # resume onto this SAME message instead of minting a rival one.
        if bot_message_id:
            configurable["bot_message_id"] = bot_message_id

        stream = execute_graph_streaming(graph, initial_state, config)
        if not user_id:
            return stream

        capture_event(
            user_id,
            AnalyticsEvents.AGENT_RUN_STARTED,
            {"agent": "comms", "mode": "interactive", "conversation_id": conversation_id},
        )

        async def _tracked_stream() -> AsyncGenerator[str, None]:
            """Yield the comms SSE stream, capturing the run's terminal outcome."""
            try:
                async for chunk in stream:
                    yield chunk
            except Exception:
                capture_event(
                    user_id,
                    AnalyticsEvents.AGENT_RUN_FAILED,
                    {"agent": "comms", "mode": "interactive", "conversation_id": conversation_id},
                )
                raise
            capture_event(
                user_id,
                AnalyticsEvents.AGENT_RUN_COMPLETED,
                {"agent": "comms", "mode": "interactive", "conversation_id": conversation_id},
            )

        return _tracked_stream()

    except Exception as exc:
        log.error(
            f"{LogTag.AGENT} Error when calling agent",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        if user_id:
            capture_event(
                user_id,
                AnalyticsEvents.AGENT_RUN_FAILED,
                {"agent": "comms", "mode": "interactive", "conversation_id": conversation_id},
            )
        error_message = f"Error when calling agent: {exc!s}"

        async def error_generator() -> AsyncGenerator[str, None]:
            """Yield the agent error as one SSE frame followed by [DONE]."""
            error_dict = {"error": error_message}
            yield f"data: {json.dumps(error_dict)}\n\n"
            yield "data: [DONE]\n\n"

        return error_generator()


async def call_agent_silent(
    request: MessageRequestWithHistory,
    conversation_id: str,
    user: AuthenticatedUser,
    usage_metadata_callback: UsageMetadataCallbackHandler | None = None,
    trigger_context: dict[str, Any] | None = None,
    source: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Execute agent in silent mode for background processing.

    Returns a tuple of (complete_message, tool_data_dict).

    The comms agent may delegate to the executor, which runs as a detached
    background task. We register an executor capture for this run's stream_id,
    wait for the executor to finish, then merge its (and its subagents') grouped
    tool_data into the returned tool_data — so background/workflow runs render
    tool calls identically to live chat.
    """
    stream_id = str(uuid4())
    user_id = user.get("user_id")
    try:
        graph, initial_state, config = await _core_agent_logic(
            request,
            conversation_id,
            user,
            trigger_context,
            usage_metadata_callback=usage_metadata_callback,
            source=source,
        )

        # Mirror the live-chat path: comms delegates to the executor (which runs
        # detached and delivers its result as its own message), then we wait for
        # it to finish and fold its reconstructed tool_data onto this comms
        # message — exactly like chat_service attaches it to the comms ack. Bind
        # the stream_id + register the collector before the graph runs so the
        # executor's tool events are captured.
        cast(AgentConfigurable, config["configurable"])["stream_id"] = stream_id
        register_executor_capture(stream_id)

        if user_id:
            capture_event(
                user_id,
                AnalyticsEvents.AGENT_RUN_STARTED,
                {"agent": "comms", "mode": "background", "conversation_id": conversation_id},
            )

        complete_message, tool_data = await execute_graph_silent(graph, initial_state, config)

        # Wait for the detached executor (if one was spawned) and fold its
        # reconstructed tool_data into this message's tool_data.
        await await_executor_done(stream_id)
        executor_tool_data = drain_executor_tool_data(stream_id)
        if executor_tool_data:
            tool_data["tool_data"] = [*tool_data.get("tool_data", []), *executor_tool_data]

        if usage_metadata_callback and hasattr(usage_metadata_callback, "usage_metadata"):
            usage = usage_metadata_callback.usage_metadata or {}
            total_input = sum(
                v.get("input_tokens", 0) for v in usage.values() if isinstance(v, dict)
            )
            total_output = sum(
                v.get("output_tokens", 0) for v in usage.values() if isinstance(v, dict)
            )
            log.set(
                agent={"model": agent_configurable(config).get("model")},
                token_input=total_input,
                token_output=total_output,
                token_total=total_input + total_output,
            )

        if user_id:
            capture_event(
                user_id,
                AnalyticsEvents.AGENT_RUN_COMPLETED,
                {"agent": "comms", "mode": "background", "conversation_id": conversation_id},
            )

        return complete_message, tool_data

    except Exception as exc:
        log.error(
            f"{LogTag.AGENT} Error when calling silent agent",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        if user_id:
            capture_event(
                user_id,
                AnalyticsEvents.AGENT_RUN_FAILED,
                {"agent": "comms", "mode": "background", "conversation_id": conversation_id},
            )
        raise
    finally:
        teardown_executor_capture(stream_id)
