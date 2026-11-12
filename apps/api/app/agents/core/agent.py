"""Agent execution for the per-turn chat stream: call_agent() yields SSE frames.

_core_agent_logic() does its setup (messages, graph, config).
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
import json
from typing import cast

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langgraph.constants import CONF

from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.messages import (
    MessageAttachments,
    MessageScope,
    construct_langchain_messages,
)
from app.agents.llm.lane import AgentRole, dev_model_id, dev_option_for
from app.config.langfuse import trace_id_for_message
from app.config.settings import settings
from app.constants.graphs import GraphName
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTracing,
    AgentTurn,
    build_agent_config,
    build_initial_state,
    execute_graph_streaming,
    opens_thread,
    recent_user_messages,
)
from app.models.agent_models import (
    AgentConfigurable,
    AgentConfigurableView,
    AgentRunnableConfig,
    agent_user_context,
)
from app.models.message_models import MessageRequestWithHistory
from app.models.presence_models import PresenceSnapshot
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import agent_run_lifecycle
from app.services.delivery.presence import read_presence
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.analytics.catalog.agents import AgentRunStarted
from shared.py.wide_events import log


@dataclass(frozen=True)
class AgentRunOptions:
    """The optional settings of one agent run, shared by every entry point.

    usage_metadata_callback collects token usage; source names the
    surface the turn came from; presence is where the user was before this
    turn; the two langfuse_* fields seed the trace.
    """

    usage_metadata_callback: UsageMetadataCallbackHandler | None = None
    source: str | None = None
    presence: PresenceSnapshot | None = None
    langfuse_trace_id: str | None = None
    langfuse_tags: list[str] | None = None
    #: The tracked todo whose own chat an interactive turn is in, so the turn knows
    #: which todo "this" is.
    active_todo_id: str | None = None
    #: The instant reaction running beside this turn's setup; its result is the emoji placed.
    instant_reaction: asyncio.Task[str | None] | None = None


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
    usage_metadata_callback = options.usage_metadata_callback
    source = options.source
    langfuse_trace_id = options.langfuse_trace_id
    langfuse_tags = options.langfuse_tags

    user_id = user.user_id

    # An interactive turn binds a todo only inside that todo's chat.
    active_todo_id: str | None = options.active_todo_id

    # Read once here, not left to build_agent_config: the comms context below
    # renders it too, and a workflow fire arrives without one. A voice call
    # captures none either; note_is_due keeps its turns noteless by entry surface.
    presence = options.presence or (await read_presence(user_id) if user_id else None)

    # Build langchain messages and get graph concurrently
    history, graph = await asyncio.gather(
        construct_langchain_messages(
            query=request.message,
            scope=MessageScope(
                user_id=user_id,
                user_name=user.name,
                user_dict=user,
                conversation_id=conversation_id,
                source=source,
                active_todo_id=active_todo_id,
                presence=presence,
                opens_thread=opens_thread(request.messages, request.message),
                instant_reaction=options.instant_reaction,
            ),
            attachments=MessageAttachments(
                selected_tool=request.selectedTool,
                tool_category=request.toolCategory,
                selected_workflow=request.selectedWorkflow,
                selected_calendar_event=request.selectedCalendarEvent,
                reply_to_message=request.replyToMessage,
                currently_uploaded_file_ids=request.uploaded_file_ids,
            ),
        ),
        GraphManager.get_graph(GraphName.COMMS),
    )

    initial_state = build_initial_state(request, user_id or "", conversation_id, history)

    # DEV-ONLY: the chat-header model selector picks a model per role. It wins over
    # plan routing inside resolve_lane. Never reached in production.
    dev_option = (
        dev_option_for(request.comms_model, request.use_default_models)
        if settings.deployment.dev_tools
        else None
    )

    # Established here (comms has the full user document) so the executor and
    # every subagent inherit it — worker tiers read it off configurable.
    user_preferences, writing_style = onboarding_preferences(user.onboarding)

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
            execution_mode="interactive",
            source=source,
            user_messages=recent_user_messages(request.messages, request.message),
            user_request=request.message,
            user_preferences=user_preferences,
            writing_style=writing_style,
            presence=presence,
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
    if settings.deployment.dev_tools and (
        executor_dev := dev_model_id(request.executor_model, request.use_default_models)
    ):
        configurable["dev_executor_model"] = executor_dev

    log.set(
        agent={
            "model": AgentConfigurableView.model_validate(configurable).model,
            "has_workflow": bool(request.selectedWorkflow),
            "has_calendar_event": bool(request.selectedCalendarEvent),
            "has_reply": bool(request.replyToMessage),
            "history_message_count": len(history),
        }
    )

    return graph, initial_state, config


def _run_started(conversation_id: str, options: AgentRunOptions) -> AgentRunStarted:
    """Build an interactive comms run's start event."""
    return AgentRunStarted(
        agent="comms",
        mode="interactive",
        conversation_id=conversation_id,
        trigger_type=None,
        source=options.source or None,
    )


async def call_agent(
    request: MessageRequestWithHistory,
    conversation_id: str,
    user: AuthenticatedUser,
    options: AgentRunOptions | None = None,
    ids: StreamMessageIds | None = None,
) -> AsyncGenerator[str, None]:
    """Execute agent in streaming mode for interactive chat, yielding SSE frames.

    ids.bot_message_id seeds the Langfuse trace_id so /messages/{id}/feedback
    can re-derive it to attach scores. A setup failure streams as one error
    frame and [DONE]; a failure mid-stream propagates.
    """
    options = options or AgentRunOptions()
    ids = ids or StreamMessageIds()
    with agent_run_lifecycle(user.user_id, _run_started(conversation_id, options)) as run:
        try:
            graph, initial_state, config = await _core_agent_logic(
                request,
                conversation_id,
                user,
                # The caller's options whole, only the trace stamped here: a field
                # copied over by hand is a field a new option silently loses.
                replace(
                    options,
                    langfuse_trace_id=(
                        trace_id_for_message(ids.bot_message_id) if ids.bot_message_id else None
                    ),
                    langfuse_tags=["comms_agent", settings.ENV],
                ),
            )
        except Exception as exc:
            log.error(
                f"{LogTag.AGENT} Error when calling agent",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            run.failure_reason = type(exc).__name__
            yield f"data: {json.dumps({'error': f'Error when calling agent: {exc!s}'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # The live bag (see the same cast in _core_agent_logic) — mutated, so
        # indexed rather than read through agent_configurable.
        configurable = cast(AgentConfigurable, config[CONF])

        # Add stream_id to config for cancellation checking
        if ids.stream_id:
            configurable["stream_id"] = ids.stream_id

        # Add user_message_id so executor can link notifications back
        if ids.user_message_id:
            configurable["user_message_id"] = ids.user_message_id

        # Add bot_message_id so a HIL pause on this turn's executor can later
        # resume onto this SAME message instead of minting a rival one.
        if ids.bot_message_id:
            configurable["bot_message_id"] = ids.bot_message_id

        async for chunk in execute_graph_streaming(graph, initial_state, config):
            yield chunk
