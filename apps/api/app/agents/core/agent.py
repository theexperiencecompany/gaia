"""Agent execution: streaming and silent modes.

- call_agent() returns an AsyncGenerator for SSE streaming (interactive chat).
- call_agent_silent() returns a results tuple (workflows, background tasks).

Both share _core_agent_logic() for common setup (messages, graph, config).
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
import json
from typing import Any, cast
from uuid import uuid4

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langgraph.constants import CONF
from pydantic import BaseModel, ConfigDict, Field

from app.agents.core.background.executor_capture import (
    await_executor_done,
    drain_executor_tool_data,
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.messages import (
    MessageAttachments,
    MessageScope,
    construct_langchain_messages,
)
from app.agents.llm.lane import AgentRole, dev_model_id, dev_option_for
from app.config.langfuse import trace_id_for_message
from app.config.settings import settings
from app.constants.agents import (
    PLAYBOOK_FALLBACK_CONTEXT_KEY,
    PLAYBOOK_REPLAYED_CALLS_KEY,
    WORKFLOW_LOCK_CONTEXT_KEY,
)
from app.constants.cache import BACKGROUND_EXECUTOR_WAIT_TIMEOUT
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTracing,
    AgentTurn,
    background_authorization,
    build_agent_config,
    build_initial_state,
    execute_graph_silent,
    execute_graph_streaming,
    recent_user_messages,
)
from app.models.agent_models import (
    AgentConfigurable,
    AgentConfigurableView,
    AgentRunnableConfig,
    ExecutionMode,
    SilentRunResult,
    agent_user_context,
    read_agent_configurable,
)
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.chat.state import aggregate_usage_metadata
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.wide_events import log


class _AgentTriggerContext(BaseModel):
    """The agent-owned keys of a background run's ``trigger_context``, parsed once.

    The bag is open — schedulers spread provider trigger data through it — so
    this reads only the keys the scheduling task itself sets.
    ``execution_mode`` stays ``object``: an unrecognised mode falls back to
    interactive below rather than failing the run.
    """

    model_config = ConfigDict(extra="ignore")

    active_todo_id: str | None = None
    todo_id: str | None = None
    todo_title: str | None = None
    execution_mode: object = None
    workflow_id: str | None = None
    workflow_title: str = ""
    workflow_notify_on_completion: bool = True
    playbook_fallback: str | None = Field(
        default=None, validation_alias=PLAYBOOK_FALLBACK_CONTEXT_KEY
    )
    playbook_replayed_calls: list[dict[str, object]] | None = Field(
        default=None, validation_alias=PLAYBOOK_REPLAYED_CALLS_KEY
    )
    executor_lock_reservation: str | None = Field(
        default=None, validation_alias=WORKFLOW_LOCK_CONTEXT_KEY
    )


@dataclass(frozen=True)
class AgentRunOptions:
    """The optional settings of one agent run, shared by every entry point.

    trigger_context is the workflow/todo/trigger data of a background run;
    usage_metadata_callback collects token usage; source names the
    surface the turn came from; the two langfuse_* fields seed the trace.
    """

    usage_metadata_callback: UsageMetadataCallbackHandler | None = None
    trigger_context: dict[str, Any] | None = None
    source: str | None = None
    langfuse_trace_id: str | None = None
    langfuse_tags: list[str] | None = None


@dataclass(frozen=True)
class StreamMessageIds:
    """The ids a streaming turn carries.

    The stream (for cancellation), the user's message (for reply linking)
    and the assistant's message (for the Langfuse trace and HIL resume).
    """

    stream_id: str | None = None
    user_message_id: str | None = None
    bot_message_id: str | None = None


async def _core_agent_logic(
    request: MessageRequestWithHistory,
    conversation_id: str,
    user: AuthenticatedUser,
    options: AgentRunOptions | None = None,
) -> tuple[CompiledAgentGraph, dict[str, object], AgentRunnableConfig]:
    """Shared setup for streaming and silent execution.

    Constructs messages, initializes the graph, builds state, and kicks off
    background memory storage. langfuse_trace_id is forwarded into the
    config metadata + configurable so child agents inherit it.
    """
    options = options or AgentRunOptions()
    trigger_context = options.trigger_context
    usage_metadata_callback = options.usage_metadata_callback
    source = options.source
    langfuse_trace_id = options.langfuse_trace_id
    langfuse_tags = options.langfuse_tags

    user_id = user.user_id

    # Extract active todo binding + execution mode from trigger_context (scheduled
    # runs set these; interactive turns leave them unset / "interactive").
    trigger = _AgentTriggerContext.model_validate(trigger_context or {})
    active_todo_id: str | None = None
    execution_mode: ExecutionMode = "interactive"
    if trigger_context:
        active_todo_id = trigger.active_todo_id or trigger.todo_id
        if trigger.execution_mode == "background":
            execution_mode = "background"

    # Build langchain messages and get graph concurrently
    history, graph = await asyncio.gather(
        construct_langchain_messages(
            messages=request.messages,
            query=request.message,
            scope=MessageScope(
                user_id=user_id,
                user_name=user.name,
                user_dict=user,
                conversation_id=conversation_id,
                source=source,
                active_todo_id=active_todo_id,
                execution_mode=execution_mode,
            ),
            attachments=MessageAttachments(
                selected_tool=request.selectedTool,
                tool_category=request.toolCategory,
                selected_workflow=request.selectedWorkflow,
                selected_calendar_event=request.selectedCalendarEvent,
                reply_to_message=request.replyToMessage,
                files_data=request.fileData,
                currently_uploaded_file_ids=request.fileIds,
                trigger_context=trigger_context,
            ),
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

    # Established here (comms has the full user document) so the executor and
    # every subagent inherit it — worker tiers read it off configurable.
    user_preferences, writing_style = onboarding_preferences(user.onboarding)
    workflow = request.selectedWorkflow

    # This is the top-level run, so build_agent_config resolves the comms lane
    # here; the executor and every subagent inherit it whole.
    config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id=conversation_id,
            user=agent_user_context(user),
            agent_name="comms_agent",
        ),
        lane=AgentLane(role=AgentRole.COMMS, dev_option=dev_option),
        turn=AgentTurn(
            selected_tool=request.selectedTool,
            tool_category=request.toolCategory,
            active_todo_id=active_todo_id,
            execution_mode=execution_mode,
            source=source,
            user_messages=background_authorization(
                recent_user_messages(request.messages, request.message),
                execution_mode=str(execution_mode),
                workflow_title=workflow.title if workflow else "",
                workflow_description=workflow.description if workflow else "",
                todo_title=trigger.todo_title or "",
            ),
            user_request=request.message,
            user_preferences=user_preferences,
            writing_style=writing_style,
            workflow_id=trigger.workflow_id,
        ),
        tracing=AgentTracing(
            usage_metadata_callback=usage_metadata_callback,
            langfuse_trace_id=langfuse_trace_id,
            langfuse_tags=langfuse_tags,
        ),
    )

    # The live bag build_agent_config just produced — mutated below, so it is
    # indexed (KeyError if absent) rather than read via agent_configurable,
    # whose empty-dict fallback would swallow the writes.
    configurable = cast(AgentConfigurable, config[CONF])

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
    if trigger_context and trigger.workflow_id:
        configurable["workflow_id"] = trigger.workflow_id
        configurable["workflow_title"] = trigger.workflow_title
        configurable["workflow_notify_on_completion"] = trigger.workflow_notify_on_completion
        configurable["playbook_fallback"] = trigger.playbook_fallback
        configurable["playbook_replayed_calls"] = trigger.playbook_replayed_calls
        configurable["executor_lock_reservation"] = trigger.executor_lock_reservation

    log.set(
        agent={
            "model": AgentConfigurableView.model_validate(configurable).model,
            "has_workflow": bool(request.selectedWorkflow),
            "has_trigger_context": bool(trigger_context),
            "has_calendar_event": bool(request.selectedCalendarEvent),
            "has_reply": bool(request.replyToMessage),
            "history_message_count": len(history),
        }
    )

    return graph, initial_state, config


async def call_agent(
    request: MessageRequestWithHistory,
    conversation_id: str,
    user: AuthenticatedUser,
    options: AgentRunOptions | None = None,
    ids: StreamMessageIds | None = None,
) -> AsyncGenerator[str, None]:
    """Execute agent in streaming mode for interactive chat.

    ids.bot_message_id seeds the Langfuse trace_id so
    /messages/{id}/feedback can re-derive it to attach scores. Returns an
    AsyncGenerator yielding SSE-formatted streaming data.
    """
    options = options or AgentRunOptions()
    ids = ids or StreamMessageIds()
    usage_metadata_callback, source = options.usage_metadata_callback, options.source
    stream_id, user_message_id, bot_message_id = (
        ids.stream_id,
        ids.user_message_id,
        ids.bot_message_id,
    )

    user_id = user.user_id
    try:
        langfuse_trace_id = trace_id_for_message(bot_message_id) if bot_message_id else None

        graph, initial_state, config = await _core_agent_logic(
            request,
            conversation_id,
            user,
            AgentRunOptions(
                usage_metadata_callback=usage_metadata_callback,
                source=source,
                langfuse_trace_id=langfuse_trace_id,
                langfuse_tags=["comms_agent", settings.ENV],
            ),
        )

        # The live bag (see the same cast in _core_agent_logic) — mutated, so
        # indexed rather than read through agent_configurable.
        configurable = cast(AgentConfigurable, config[CONF])

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
    options: AgentRunOptions | None = None,
) -> SilentRunResult:
    """Execute agent in silent mode for background processing.

    Comms may delegate to a detached background executor; this waits for it
    and merges its tool_data so background/workflow runs render like live
    chat, or carries the queued task_id if delegation was queued instead.
    """
    options = options or AgentRunOptions()
    usage_metadata_callback = options.usage_metadata_callback
    trigger_context = options.trigger_context
    source = options.source

    stream_id = str(uuid4())
    user_id = user.user_id
    try:
        graph, initial_state, config = await _core_agent_logic(
            request,
            conversation_id,
            user,
            AgentRunOptions(
                usage_metadata_callback=usage_metadata_callback,
                trigger_context=trigger_context,
                source=source,
            ),
        )

        # Mirror the live-chat path: wait for the detached executor and fold
        # its tool_data onto this message. Bind stream_id + register the
        # collector before the graph runs so tool events are captured.
        cast(AgentConfigurable, config[CONF])["stream_id"] = stream_id
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
        await await_executor_done(stream_id, timeout=BACKGROUND_EXECUTOR_WAIT_TIMEOUT)
        executor_tool_data = drain_executor_tool_data(stream_id)
        if executor_tool_data:
            tool_data = [*tool_data, *executor_tool_data]

        if usage_metadata_callback and hasattr(usage_metadata_callback, "usage_metadata"):
            totals = aggregate_usage_metadata(usage_metadata_callback.usage_metadata or {})
            total_input, total_output = totals.input_tokens, totals.output_tokens
            log.set(
                agent={"model": read_agent_configurable(config).model},
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

        return SilentRunResult(
            message=complete_message,
            tool_data=tool_data,
        )

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
