from datetime import datetime, timezone
from typing import List, Optional

from app.agents.prompts.workflow_prompts import (
    EMAIL_TRIGGERED_WORKFLOW_PROMPT,
    WORKFLOW_EXECUTION_PROMPT,
)
from app.agents.templates.agent_template import AGENT_PROMPT_TEMPLATE
from app.config.loggers import llm_logger as logger
from app.models.message_models import FileData, SelectedWorkflowData
from app.services.memory_service import memory_service
from app.services.onboarding_service import get_user_preferences_for_agent
from app.services.workflow import WorkflowService
from langchain_core.messages import SystemMessage


async def create_system_message(
    user_id: Optional[str] = None, user_name: Optional[str] = None
) -> SystemMessage:
    """Create system message with current time and user preferences."""
    formatted_time = datetime.now(timezone.utc).strftime("%A, %B %d, %Y, %H:%M:%S UTC")

    # Include user preferences if available for personalization
    user_preferences = ""
    if user_id and (prefs := await get_user_preferences_for_agent(user_id)):
        user_preferences = f"\n{prefs}\n"

    return SystemMessage(
        content=AGENT_PROMPT_TEMPLATE.format(
            current_datetime=formatted_time,
            user_name=user_name,
            user_preferences=user_preferences,
        )
    )


async def get_memory_message(user_id: str, query: str) -> Optional[SystemMessage]:
    """Retrieve relevant conversation memories and format as system context."""
    try:
        # Search for contextually relevant memories using the query
        if not (
            results := await memory_service.search_memories(
                query=query, user_id=user_id, limit=100
            )
        ):
            return None

        if not (memories := getattr(results, "memories", None)):
            logger.error("No memories found in search results")
            return None

        logger.info(f"Memories are found: {memories}")

        content = "Based on our previous conversations:\n" + "\n".join(
            f"- {mem.content}" for mem in memories
        )
        logger.info(f"Added {len(memories)} memories to context")
        logger.info(f"{content=}")
        return SystemMessage(content=content)

    except Exception as e:
        logger.error(f"Error retrieving memories: {e}")
        return None


def format_tool_selection_message(selected_tool: str, existing_content: str) -> str:
    """Format tool selection message, handling both standalone and combined requests."""
    tool_name = selected_tool.replace("_", " ").title()
    base_instruction = f"The user has selected the {selected_tool} tool and wants you to execute it immediately."

    # If user provided content, append tool instruction to their message
    if existing_content:
        return f"{existing_content}\n\n**TOOL SELECTION:** The user has specifically selected the '{tool_name}' tool and wants you to execute it to handle their request above. {base_instruction} Follow your system prompt instructions for provider-specific tools and use appropriate handoff tools when needed. Do not ask for additional information - execute the selected functionality now."

    # Pure tool execution without user message
    return f"**TOOL EXECUTION REQUEST:** The user has selected the '{tool_name}' tool and wants you to execute it immediately. {base_instruction} Follow your system prompt instructions for provider-specific tools and use appropriate handoff tools when needed. Do not ask for additional information or clarification - proceed with executing the selected tool functionality right away."


async def format_workflow_execution_message(
    selected_workflow: SelectedWorkflowData,
    user_id: Optional[str] = None,
    trigger_context: Optional[dict] = None,
    existing_content: str = "",
) -> str:
    """Format workflow execution message, handling both manual and automated triggers."""
    # Fetch the latest workflow data from database
    workflow = None
    if user_id:
        try:
            workflow = await WorkflowService.get_workflow(selected_workflow.id, user_id)
        except Exception as e:
            logger.error(f"Failed to fetch workflow {selected_workflow.id}: {e}")

    # Use fresh database data if available, otherwise use passed data
    if workflow and workflow.steps:
        steps_text = "\n".join(
            f"{i}. **{step.title}** (Tool: {step.tool_name})\n   Description: {step.description}"
            for i, step in enumerate(workflow.steps, 1)
        )
        tools_text = ", ".join(step.tool_name for step in workflow.steps)
        workflow_title = workflow.title
        workflow_description = workflow.description
    else:
        # Fallback to passed data
        steps_text = "\n".join(
            f"{i}. **{step['title']}** (Tool: {step['tool_name']})\n   Description: {step['description']}"
            for i, step in enumerate(selected_workflow.steps, 1)
        )
        tools_text = ", ".join(step["tool_name"] for step in selected_workflow.steps)
        workflow_title = selected_workflow.title
        workflow_description = selected_workflow.description

    common_args = {
        "workflow_title": workflow_title,
        "workflow_description": workflow_description,
        "workflow_steps": steps_text,
        "tool_names": tools_text,
    }

    # Email-triggered workflows get enhanced context
    if trigger_context and trigger_context.get("type") == "gmail":
        email_data = trigger_context.get("email_data", {})
        msg_text = email_data.get("message_text", "")

        return EMAIL_TRIGGERED_WORKFLOW_PROMPT.format(
            email_sender=email_data.get("sender", "Unknown"),
            email_subject=email_data.get("subject", "No Subject"),
            email_content_preview=msg_text[:200]
            + ("..." if len(msg_text) > 200 else ""),
            trigger_timestamp=trigger_context.get("triggered_at", "Unknown"),
            **common_args,
        )

    # Manual workflow execution
    return WORKFLOW_EXECUTION_PROMPT.format(
        user_message=existing_content or f"Execute workflow: {workflow_title}",
        **common_args,
    )


def format_files_list(
    files_data: Optional[List[FileData]], file_ids: Optional[List[str]] = None
) -> str:
    """Format file information for agent context with usage instructions."""
    if not files_data or (file_ids is not None and not file_ids):
        return "No files uploaded."

    # Filter to specific files if IDs provided, otherwise use all
    files = (
        files_data
        if file_ids is None
        else [f for f in files_data if f.fileId in file_ids]
    )
    if not files:
        return "No files uploaded."

    file_list = "\n".join(
        f"- Name: {file.filename} Id: {file.fileId}" for file in files
    )

    return f"{file_list}\n\nYou can use these files in your conversation. If you need to refer to them, use the file IDs provided.\nYou must use query_files to retrieve file content or metadata."
