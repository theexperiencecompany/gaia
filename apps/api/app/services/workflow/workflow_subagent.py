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

from datetime import datetime, timezone
from typing import Optional

from app.agents.core.subagents.base_subagent import SubAgentFactory
from app.agents.core.subagents.subagent_helpers import create_agent_context_message
from app.agents.llm.client import init_llm
from app.agents.prompts.subagent_prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from app.agents.tools.workflow_tool import SUBAGENT_WORKFLOW_TOOLS
from app.config.loggers import general_logger as logger
from app.helpers.agent_helpers import build_agent_config
from langchain_core.messages import (
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

# Singleton for the workflow subagent graph
_workflow_subagent_graph = None


async def get_workflow_subagent():
    """
    Get or create the workflow subagent graph (singleton).

    The workflow subagent is created once and reused for all invocations.
    It uses direct tools binding with search_triggers and list_workflows.
    """
    global _workflow_subagent_graph

    if _workflow_subagent_graph is not None:
        return _workflow_subagent_graph

    logger.info("Creating workflow subagent graph")

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

    _workflow_subagent_graph = await SubAgentFactory.create_provider_subagent(
        provider="workflow",
        name="workflow_agent",
        llm=llm,
        tool_space="workflow_subagent",
        use_direct_tools=True,
        disable_retrieve_tools=True,
    )

    logger.info("Workflow subagent graph created successfully")
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
        user_name: Optional[str] = None,
        user_time: Optional[datetime] = None,
        stream_writer=None,
    ) -> str:
        """
        Execute the workflow subagent with streaming.

        Args:
            task: The task description for workflow creation
            user_id: User ID
            thread_id: Thread/conversation ID
            user_name: Optional user name for context
            user_time: Optional user time for context
            stream_writer: Callback for streaming events

        Returns:
            Complete response text from the subagent
        """
        subagent_graph = await get_workflow_subagent()

        # Build config
        user_time = user_time or datetime.now(timezone.utc)
        subagent_thread_id = f"workflow_{thread_id}"

        user = {
            "user_id": user_id,
            "email": None,
            "name": user_name,
        }

        config: RunnableConfig = build_agent_config(
            conversation_id=thread_id,
            user=user,
            user_time=user_time,
            thread_id=subagent_thread_id,
            agent_name="workflow_agent",
            subagent_id="workflow_agent",
        )
        configurable = config.get("configurable", {})

        # Build messages
        system_message = SystemMessage(
            content=WORKFLOW_AGENT_SYSTEM_PROMPT,
            additional_kwargs={"visible_to": {"workflow_agent"}},
        )

        context_message = await create_agent_context_message(
            configurable=configurable,
            user_id=user_id,
            query=task,
            subagent_id=None,  # No subagent_id for skill retrieval
        )

        human_message = HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {"workflow_agent"}},
        )

        initial_state = {"messages": [system_message, context_message, human_message]}

        logger.info(f"[WorkflowSubagent] Executing with task: {task[:100]}...")

        complete_message = ""
        emitted_tool_calls: set[str] = set()

        async for event in subagent_graph.astream(
            initial_state,
            stream_mode=["messages", "custom", "updates"],
            config=config,
        ):
            if len(event) != 2:
                continue
            stream_mode, payload = event

            if stream_mode == "updates":
                # Handle tool updates
                for node_name, state_update in payload.items():
                    from app.utils.stream_utils import extract_tool_entries_from_update

                    entries = await extract_tool_entries_from_update(
                        state_update=state_update,
                        emitted_tool_calls=emitted_tool_calls,
                    )
                    for tc_id, tool_entry in entries:
                        if stream_writer:
                            stream_writer({"tool_data": tool_entry})
                continue

            if stream_mode == "messages":
                chunk, metadata = payload
                if metadata.get("silent"):
                    continue

                # Accumulate AI response content
                if chunk and isinstance(chunk, AIMessageChunk):
                    content = (
                        chunk.text() if hasattr(chunk, "text") else str(chunk.content)
                    )
                    if content:
                        complete_message += content

                # Emit tool_output when ToolMessage arrives
                elif chunk and isinstance(chunk, ToolMessage):
                    if stream_writer:
                        stream_writer(
                            {
                                "tool_output": {
                                    "tool_call_id": chunk.tool_call_id,
                                    "output": chunk.text()[:3000],
                                }
                            }
                        )
                continue

            if stream_mode == "custom":
                if stream_writer:
                    stream_writer(payload)

        logger.info(
            f"[WorkflowSubagent] Completed. Response: {len(complete_message)} chars"
        )
        return complete_message if complete_message else "Task completed"
