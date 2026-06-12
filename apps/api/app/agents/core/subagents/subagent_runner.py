"""Shared logic for subagent invocation, used by handoff_tools.py and
executor_tool.py.

Lives here (rather than in handoff_tools.py) so those modules import from it,
avoiding a cyclic dependency.
"""

from datetime import datetime
import uuid

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agents.core.graph_manager import GraphManager
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.core.subagents.subagent_helpers import (
    create_agent_context_message,
)
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_AUTO_NOTIFY_SECTION,
    WORKFLOW_SILENT_NOTIFY_SECTION,
)
from app.constants.general import FINISH_TASK_NAME
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config
from app.helpers.message_helpers import (
    build_current_time_message,
    create_system_message,
)
from app.utils.agent_utils import IntegrationMetadata, StreamWriterCallable
from app.utils.stream_utils import extract_tool_entries_from_update, normalize_custom_event
from shared.py.wide_events import log


def _capture_finish_task_content(chunk: ToolMessage, current_message: str) -> str:
    """Return the finish_task chunk's textual content if applicable.

    `finish_task` (when used by a subagent) carries the final answer in its
    return value. Capture it as the complete message so the parent handoff
    returns the actual content rather than the literal "Task completed"
    fallback. Subagents with include_finish_task=False terminate via a
    normal AIMessage and never enter this branch.
    """
    if chunk.name == FINISH_TASK_NAME and isinstance(chunk.content, str):
        return chunk.content
    return current_message


class SubagentExecutionContext:
    """Container for all data needed to execute a subagent."""

    def __init__(
        self,
        subagent_graph,
        agent_name: str,
        config: dict,
        configurable: dict,
        integration_id: str,
        initial_state: dict,
        user_id: str | None = None,
        stream_id: str | None = None,
    ):
        self.subagent_graph = subagent_graph
        self.agent_name = agent_name
        self.config = config
        self.configurable = configurable
        self.integration_id = integration_id
        self.initial_state = initial_state
        self.user_id = user_id
        self.stream_id = stream_id


async def build_initial_messages(
    system_message: SystemMessage,
    agent_name: str,
    configurable: dict,
    task: str,
    user_id: str | None = None,
    subagent_id: str | None = None,
    retrieval_query: str | None = None,
    integration_id: str | None = None,
    memories_text: str | None = None,
    skills_text: str | None = None,
) -> list:
    """Build the [static_prompt, dynamic_context, human_task] triplet.

    The static system prompt is byte-identical across users/channels. The
    dynamic-context message carries user_name, memories, skills, platform
    restrictions, and (for provider subagents) service-specific username
    metadata. ``manage_system_prompts_node`` collapses repeats at run time.

    Args:
        system_message: Pre-built STATIC system message (must not include
            any per-user or per-time content — keeps the cache prefix stable).
        agent_name: Name of the agent (for HumanMessage visibility metadata).
        configurable: Config dict with user_time, user_name, etc.
        task: The task/query to execute (goes into the HumanMessage).
        user_id: Optional user ID for memory retrieval.
        subagent_id: Optional subagent ID for skill retrieval.
        retrieval_query: Query for memory/context retrieval. Defaults to
            ``task`` but should be set to the original unenhanced task when
            ``task`` contains injected hints that would pollute semantic
            search.
        integration_id: When invoking a provider subagent, the underlying
            integration ID — used to fetch provider metadata (GitHub login,
            Gmail address, etc.) for the dynamic-context message.
        memories_text: Pre-fetched memories section. The parent can fetch in
            parallel with its own work and pass it down here to avoid the
            subagent running a duplicate ChromaDB lookup.
        skills_text: Pre-fetched skills section; same rationale.
    """
    log.set(agent_prep={"agent_name": agent_name, "task_length": len(task)})

    context_message = await create_agent_context_message(
        configurable=configurable,
        user_id=user_id,
        query=retrieval_query if retrieval_query is not None else task,
        subagent_id=subagent_id,
        integration_id=integration_id,
        memories_text=memories_text,
        skills_text=skills_text,
    )

    # Current time rides in a HumanMessage so the system_instruction prefix
    # stays stable — minute ticks would otherwise reset the cache boundary
    # at whatever byte position the timestamp occupies.
    time_message = build_current_time_message(
        user_timezone=configurable.get("user_timezone"),
    )

    return [
        system_message,
        context_message,
        time_message,
        HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {agent_name}},
        ),
    ]


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer: StreamWriterCallable | None = None,
    integration_metadata: IntegrationMetadata | None = None,
    subagent_id: str | None = None,
) -> str:
    """Execute a subagent with streaming and tool tracking, returning the
    complete message.

    Stream event flow:
        - "updates": emit tool_data with complete args when a tool is called
        - "messages": stream content, emit tool_output when a ToolMessage arrives
        - "custom": forward custom events (progress, etc.) to the parent
    """
    log.set(subagent={"name": ctx.agent_name, "provider": ctx.integration_id})
    complete_message = ""
    finish_task_result: str | None = None
    emitted_tool_calls: set[str] = set()

    # Inject the UUID subagent_id into configurable so nested spawn_subagent
    # tool calls can read the correct parent_subagent_id via
    # configurable.get("subagent_id").
    run_config = ctx.config
    if subagent_id:
        base_configurable = ctx.config.get("configurable", {})
        run_config = {
            **ctx.config,
            "configurable": {**base_configurable, "subagent_id": subagent_id},
        }

    async for event in ctx.subagent_graph.astream(
        ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        config=run_config,
    ):
        # Check for cancellation
        if ctx.stream_id and await stream_manager.is_cancelled(ctx.stream_id):
            log.info(f"Subagent stream {ctx.stream_id} cancelled by user")
            break

        # Handle 2-tuple format only (no subgraphs)
        if len(event) != 2:
            continue
        stream_mode, payload = event

        if stream_mode == "updates":
            for node_name, state_update in payload.items():
                # Only emit tool_data from the LLM ("agent") node.
                # Pre-model hooks (filter_messages_node, manage_system_prompts_node,
                # etc.) produce "updates" events containing historical AIMessages
                # with tool_calls from previous checkpoint runs — emitting those
                # would replay stale tool cards into the current stream.
                if node_name != "agent":
                    continue
                # Use shared helper to extract and format tool entries
                entries = await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                    integration_metadata=integration_metadata,
                )
                for tc_id, tool_entry in entries:
                    if stream_writer:
                        chunk_data: dict = {"tool_data": tool_entry}
                        if subagent_id:
                            chunk_data["tool_data"] = {**tool_entry, "subagent_id": subagent_id}
                        stream_writer(chunk_data)
            continue

        if stream_mode == "messages":
            chunk, metadata = payload
            if metadata.get("silent"):
                continue

            # Accumulate AI response content
            if chunk and isinstance(chunk, AIMessageChunk):
                content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
                if content:
                    complete_message += content

            # Emit tool_output when ToolMessage arrives
            elif chunk and isinstance(chunk, ToolMessage):
                content_str = (
                    chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                )
                complete_message = _capture_finish_task_content(chunk, complete_message)
                if stream_writer:
                    tool_output_data: dict = {
                        "tool_call_id": chunk.tool_call_id,
                        "output": content_str,
                    }
                    if subagent_id:
                        tool_output_data["subagent_id"] = subagent_id
                    stream_writer({"tool_output": tool_output_data})
            continue

        if stream_mode == "custom":
            if stream_writer:
                stream_writer(normalize_custom_event(payload))

    final_message = (
        finish_task_result
        if finish_task_result is not None
        else complete_message
        if complete_message
        else "Task completed"
    )
    log.set(
        subagent={
            "name": ctx.agent_name,
            "provider": ctx.integration_id,
            "response_length": len(final_message),
            "messages_count": len(ctx.initial_state.get("messages", [])),
        }
    )
    return final_message


async def prepare_executor_execution(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """Prepare execution context for the executor agent.

    Like the platform-subagent prepare flow but resolves the graph via
    GraphManager, uses executor-specific prompts, and injects direct handoff
    hints when selected_tool/tool_category is known.

    Returns (SubagentExecutionContext, None) on success, or (None, error) on
    failure.
    """
    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")

    # Fresh executor thread per call_executor invocation. Architecturally the
    # comms agent owns the conversation thread; the executor is a subroutine
    # invoked with a task description + the last user message. Giving it its
    # own ephemeral thread keeps its context small and prevents stale tool
    # observations from one task bleeding into the next. If a later user turn
    # needs prior context, comms passes it explicitly in the new task
    # description.
    call_scope = uuid.uuid4().hex[:12]
    executor_thread_id = f"executor_{thread_id}_{call_scope}"

    # VFS session stays pinned to the PARENT conversation thread so files
    # written by one executor call are visible to the next — the ephemeral
    # thread only scopes agent reasoning, not persisted artefacts.
    vfs_session_id = configurable.get("vfs_session_id") or thread_id

    # Load executor graph
    executor_graph = await GraphManager.get_graph("executor_agent")
    if not executor_graph:
        return None, "Executor agent not available"

    # Build user dict for config
    user = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }

    # Build config
    config = build_agent_config(
        conversation_id=thread_id,
        user=user,
        user_time=user_time,
        thread_id=executor_thread_id,
        base_configurable=configurable,
        agent_name="executor_agent",
        subagent_id="executor_agent",  # Use agent_name as agent_id in mem0
        vfs_session_id=vfs_session_id,
    )
    new_configurable = config.get("configurable", {})

    # Create system message (executor-specific)
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # When comms provides a known tool_category, hint the executor to go
    # straight to handoff(subagent_id=...) and skip the ChromaDB discovery
    # call. We do NOT pre-bind tools — the target subagent still does its own
    # retrieval. This only removes one redundant round-trip where comms
    # already knows the category.
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    if tool_category and get_subagent_by_id(tool_category):
        tool_hint = f"the '{selected_tool}' tool" if selected_tool else "the user's request"
        enhanced_task = (
            f"{task}\n\n"
            f"DIRECT EXECUTION HINT: This request should be handled by "
            f"'{tool_category}'. Skip retrieve_tools discovery and directly "
            f'call handoff(subagent_id="{tool_category}", task="{task}") to '
            f"route {tool_hint}."
        )
        log.set(
            executor_prep={
                "direct_hint_applied": True,
                "tool_category": tool_category,
                "selected_tool": selected_tool,
            }
        )

    # Workflow runs: the executor owns send_notification, but it only sees the
    # task text comms writes. Inject the notification mode here, keyed off the
    # run's own configurable, so the no-double-notify guarantee never depends
    # on comms forwarding the rule. Skip if the task already carries the section
    # (format_workflow_execution_message embeds it) to avoid duplicating it.
    if configurable.get("workflow_id") and "NOTIFICATIONS:" not in enhanced_task:
        notification_section = (
            WORKFLOW_AUTO_NOTIFY_SECTION
            if configurable.get("workflow_notify_on_completion", True)
            else WORKFLOW_SILENT_NOTIFY_SECTION
        )
        enhanced_task = f"{enhanced_task}\n{notification_section}"

    # Build messages using shared helper.
    # Pass original task as retrieval_query so memory/context semantic search
    # is not polluted by the DIRECT EXECUTION HINT injected into enhanced_task.
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name="executor_agent",
        configurable=new_configurable,
        task=enhanced_task,
        user_id=user_id,
        retrieval_query=task,
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id="executor",
        initial_state={"messages": messages, "todos": []},
        user_id=user_id,
        stream_id=stream_id,
    ), None
