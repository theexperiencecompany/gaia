"""
Workflow subagent factory and runner.

This module provides the dedicated workflow subagent that is:
- NOT registered in oauth_config.py (hidden from handoff discovery)
- Invoked directly by create_workflow tool
- Uses structured JSON output for workflow drafts

The subagent has access to:
- search_triggers: Find integration triggers
- list_workflows: Show existing workflows
- search_memory: Access user memories
"""

import json
from typing import Any, cast

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext
from app.agents.context.tiers import AgentTier
from app.agents.core.subagents.base_subagent import SubAgentFactory
from app.agents.llm.client import init_llm
from app.agents.prompts.subagent_prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from app.agents.tools.workflow_shared_tools import SUBAGENT_WORKFLOW_TOOLS
from app.constants.llm import WORKFLOW_SUBAGENT_RECURSION_LIMIT
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import build_agent_config
from app.helpers.message_helpers import build_current_time_message
from app.models.agent_models import AgentConfigurable, AgentUserContext, agent_configurable
from app.services.workflow.knowledge import build_connected_integrations_hint
from app.services.workflow.subagent_output import parse_subagent_response
from app.utils.workflow_utils import unknown_integration_ids
from shared.py.wide_events import log

# How many times to hand a validation error back to the agent and let it re-emit a
# corrected draft before giving up (the persist-time filter is the final backstop).
MAX_DRAFT_CORRECTIONS = 2

# When the authoring loop exhausts its step budget (a wandering model that keeps
# calling discovery tools without answering), we force one final turn with this
# directive. The step budget resets and filter_messages_node drops the dangling
# tool calls, so the model can only reply with text.
FORCE_FINALIZE_DIRECTIVE = (
    "You have already gathered enough information. STOP calling tools now. "
    "Reply with your final answer as exactly one fenced ```json block and nothing "
    "else: either a finalized workflow, or a clarifying question if the request is "
    "genuinely ambiguous. Do not call any more tools."
)

# Absolute last resort if even the forced-finalize turn fails to converge: a valid
# clarifying draft, so create_workflow always receives parseable JSON instead of a
# raw GraphRecursionError.
FALLBACK_CLARIFY_JSON = (
    "```json\n"
    + json.dumps(
        {
            "type": "clarifying",
            "message": (
                "I had trouble putting this workflow together. Could you restate what "
                "you want it to do, and when it should run: on demand, on a schedule, "
                "or when something happens?"
            ),
        }
    )
    + "\n```"
)

# Singleton for the workflow subagent graph
_workflow_subagent_graph: CompiledStateGraph | None = None


async def get_workflow_subagent() -> CompiledStateGraph:
    """
    Get or create the workflow subagent graph (singleton).

    The workflow subagent is created once and reused for all invocations.
    It uses direct tools binding with search_triggers and list_workflows.
    """
    global _workflow_subagent_graph

    if _workflow_subagent_graph is not None:
        return _workflow_subagent_graph

    log.info(f"{LogTag.WORKFLOW} Creating workflow subagent graph")

    # Register workflow tools in the registry under 'workflow_subagent' space
    from app.agents.tools.core.registry import get_tool_registry

    tool_registry = await get_tool_registry()

    # Add workflow subagent tools as a separate category (if not already exists)
    if "workflow_subagent" not in tool_registry._categories:
        tool_registry._add_category(
            name="workflow_subagent",
            tools=SUBAGENT_WORKFLOW_TOOLS,
            space="workflow_subagent",
        )

    llm = init_llm()

    # Authoring-only: the workflow assistant emits a draft, it does not execute.
    # This strips the always-available execution tools (bash/read/web/research),
    # the plan_tasks/spawn_subagent machinery, and finish_task, so it can only
    # use its discovery tools and then return the finalized JSON.
    _workflow_subagent_graph = await SubAgentFactory.create_provider_subagent(
        provider="workflow",
        name="workflow_agent",
        llm=llm,
        tool_space="workflow_subagent",
        use_direct_tools=True,
        disable_retrieve_tools=True,
        include_finish_task=False,
        authoring_only=True,
    )

    log.info(f"{LogTag.WORKFLOW} Workflow subagent graph created successfully")
    return _workflow_subagent_graph


class WorkflowSubagentRunner:
    """
    Runner for executing the workflow subagent with streaming.

    This replaces the prepare_subagent_execution + execute_subagent_stream
    pattern used for oauth-registered subagents.
    """

    @staticmethod
    async def execute(
        task: str,
        user_id: str,
        thread_id: str,
        user_name: str | None = None,
        user_timezone: str | None = None,
        stream_writer: StreamWriter | None = None,
        base_configurable: AgentConfigurable | None = None,
    ) -> str:
        """Execute the workflow subagent with streaming, returning the complete response text.

        ``base_configurable`` is the parent (executor) configurable so the subagent
        inherits its plan tier, plan-routed model, provider pin, and root_request_id
        — keeping pro users on the paid model and the budget wall enforced across the
        whole turn tree, exactly like other handoff subagents.
        """
        subagent_graph = await get_workflow_subagent()

        # Build config
        subagent_thread_id = f"workflow_{thread_id}"

        user: AgentUserContext = {
            "user_id": user_id,
            "email": None,
            "name": user_name,
            "timezone": user_timezone,
        }

        config = await build_agent_config(
            conversation_id=thread_id,
            user=user,
            thread_id=subagent_thread_id,
            agent_name="workflow_agent",
            subagent_id="workflow_agent",
            base_configurable=base_configurable,
        )
        configurable = agent_configurable(config)

        # Authoring only needs a few discovery calls before it emits JSON. Cap the
        # loop below a full agent's budget so a wandering model can't burn ~20 tool
        # cycles, and so the forced-finalize fallback (see the execute loop) kicks
        # in quickly instead of after a long stall.
        config["recursion_limit"] = WORKFLOW_SUBAGENT_RECURSION_LIMIT

        # Build messages
        system_message = SystemMessage(
            content=WORKFLOW_AGENT_SYSTEM_PROMPT,
            additional_kwargs={"visible_to": {"workflow_agent"}},
        )

        assembled = await assemble_context(
            SectionContext.from_configurable(
                AgentTier.WORKFLOW_AUTHORING,
                configurable,
                query=task,
                user_id=user_id,
            )
        )

        # Compact ground truth (which integrations THIS user has connected) folded
        # into the task. It must NOT be a separate SystemMessage: it would occupy
        # the static slot and evict WORKFLOW_AGENT_SYSTEM_PROMPT, losing the whole
        # role/rules/output-format prompt.
        hint = await build_connected_integrations_hint(user_id)
        human_message = HumanMessage(
            content=f"{hint}\n\n---\n\nRequest: {task}",
            additional_kwargs={"visible_to": {"workflow_agent"}},
        )

        # An authoring agent that cannot tell today's date cannot resolve "every
        # Monday" or "starting next week" — the exact things a workflow schedule
        # is made of. This tier was the only one seeded without a clock.
        time_message = build_current_time_message(user_timezone=user_timezone)

        initial_state: dict[str, Any] = {
            "messages": [
                system_message,
                *assembled.messages(),
                human_message,
                time_message,
            ],
            "intent": task,
            "integration_usernames": {},
        }

        log.info(f"{LogTag.WORKFLOW} Executing workflow subagent task", task_length=len(task))

        # Generate, validate, and correct: if the agent returns invalid json (bad
        # structure or integration_ids that name a non-existent integration), hand the
        # error back and let it re-emit, up to MAX_DRAFT_CORRECTIONS times.
        emitted_tool_calls: set[str] = set()
        state: dict[str, Any] = initial_state
        complete_message = ""
        for attempt in range(MAX_DRAFT_CORRECTIONS + 1):
            complete_message, hit_limit = await WorkflowSubagentRunner._stream_turn(
                subagent_graph, state, config, stream_writer, emitted_tool_calls
            )
            if hit_limit:
                # The model wandered past its step budget without answering. Force a
                # terminal answer so create_workflow never sees a raw crash.
                complete_message = await WorkflowSubagentRunner._forced_finalize(
                    subagent_graph, config, stream_writer, emitted_tool_calls
                )
                break
            correction = await WorkflowSubagentRunner._draft_correction_needed(complete_message)
            if correction is None:
                break
            if attempt == MAX_DRAFT_CORRECTIONS:
                log.warning(
                    f"{LogTag.WORKFLOW} Draft still invalid after corrections; handing off as-is",
                    corrections=attempt,
                    correction_length=len(correction),
                )
                break
            log.info(
                f"{LogTag.WORKFLOW} Draft invalid; re-prompting to correct", attempt=attempt + 1
            )
            state = {
                "messages": [
                    HumanMessage(
                        content=correction,
                        additional_kwargs={"visible_to": {"workflow_agent"}},
                    )
                ]
            }

        log.info(
            f"{LogTag.WORKFLOW} Completed. Response: chars",
            complete_message_count=len(complete_message),
        )
        return complete_message or "Task completed"

    @staticmethod
    async def _forced_finalize(
        subagent_graph: CompiledStateGraph,
        config: RunnableConfig,
        stream_writer: StreamWriter | None,
        emitted_tool_calls: set[str],
    ) -> str:
        """Force a wandering subagent to emit terminal JSON.

        Re-runs the graph with a stop directive: the step budget resets and the
        graph's filter node strips the dangling tool calls, so the model can only
        reply with text. If it still fails to converge, returns a static clarifying
        draft so the caller always receives parseable JSON.
        """
        log.warning(f"{LogTag.WORKFLOW} Authoring loop hit its step budget; forcing a final answer")
        directive_state = {
            "messages": [
                HumanMessage(
                    content=FORCE_FINALIZE_DIRECTIVE,
                    additional_kwargs={"visible_to": {"workflow_agent"}},
                )
            ]
        }
        message, hit_limit = await WorkflowSubagentRunner._stream_turn(
            subagent_graph, directive_state, config, stream_writer, emitted_tool_calls
        )
        if hit_limit or not message.strip():
            log.warning(
                f"{LogTag.WORKFLOW} Forced finalize did not converge; using fallback clarifying draft"
            )
            return FALLBACK_CLARIFY_JSON
        return message

    @staticmethod
    async def _stream_turn(
        subagent_graph: CompiledStateGraph,
        state: dict[str, Any],
        config: RunnableConfig,
        stream_writer: StreamWriter | None,
        emitted_tool_calls: set[str],
    ) -> tuple[str, bool]:
        """Run one turn of the subagent graph, streaming tool/custom events.

        Returns (assistant_text, hit_recursion_limit). hit_recursion_limit is True
        when the model exhausted its step budget without producing a final answer,
        signalling the caller to force a finalize instead of crashing.
        """
        complete_message = ""
        try:
            async for event in subagent_graph.astream(
                state,
                stream_mode=["messages", "custom", "updates"],
                config=config,
            ):
                if len(event) != 2:
                    continue
                # A list `stream_mode` makes astream yield (mode, payload) tuples,
                # which langgraph's own overload return type does not express.
                stream_mode, payload = cast(tuple[str, Any], event)

                if stream_mode == "updates":
                    for _node_name, state_update in payload.items():
                        from app.utils.stream_utils import extract_tool_entries_from_update

                        entries = await extract_tool_entries_from_update(
                            state_update=state_update,
                            emitted_tool_calls=emitted_tool_calls,
                        )
                        for _tc_id, tool_entry in entries:
                            if stream_writer:
                                stream_writer({"tool_data": tool_entry})
                    continue

                if stream_mode == "messages":
                    chunk, metadata = payload
                    if metadata.get("silent"):
                        continue
                    if chunk and isinstance(chunk, AIMessageChunk):
                        content = chunk.text() if hasattr(chunk, "text") else str(chunk.content)
                        if content:
                            complete_message += content
                    elif chunk and isinstance(chunk, ToolMessage):
                        if stream_writer:
                            stream_writer(
                                {
                                    "tool_output": {
                                        "tool_call_id": chunk.tool_call_id,
                                        "output": chunk.text(),
                                    }
                                }
                            )
                    continue

                if stream_mode == "custom" and stream_writer:
                    stream_writer(payload)
        except GraphRecursionError:
            return complete_message, True

        return complete_message, False

    @staticmethod
    async def _draft_correction_needed(text: str) -> str | None:
        """If the agent's reply is a finalized/parseable draft with only real integration
        ids, return None. Otherwise return a correction instruction to hand back to it."""
        result = parse_subagent_response(text)
        if result.mode == "parse_error":
            return (
                f"Your previous reply could not be used: {result.parse_error}. Re-emit exactly "
                "ONE fenced ```json block, either a finalized workflow or a clarifying question."
            )
        if result.mode == "finalized" and result.draft:
            bad = await unknown_integration_ids(result.draft.integration_ids)
            if bad:
                return (
                    f"integration_ids includes ids that are NOT real integrations in GAIA: {bad}. "
                    "Those services do not exist here. Re-emit the FULL finalized json without them, "
                    "or if the workflow truly needs one, return a clarifying json telling the user it "
                    "is not available."
                )
        return None
