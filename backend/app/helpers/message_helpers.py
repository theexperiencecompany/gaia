from datetime import datetime, timezone
from typing import List, Optional

from app.agents.prompts.workflow_prompts import (
    EMAIL_TRIGGERED_WORKFLOW_PROMPT,
    WORKFLOW_EXECUTION_PROMPT,
)
from app.agents.templates.agent_template import AGENT_PROMPT_TEMPLATE
from app.config.loggers import llm_logger as logger
from app.models.message_models import (
    FileData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.services.memory_service import memory_service
from app.services.workflow import WorkflowService
from app.utils.user_preferences_utils import (
    format_user_preferences_for_agent,
)
from langchain_core.messages import SystemMessage


def create_system_message(
    user_id: Optional[str] = None, user_name: Optional[str] = None
) -> SystemMessage:
    """Create main system message with user name only."""
    return SystemMessage(
        content=AGENT_PROMPT_TEMPLATE.format(
            user_name=user_name or "there",
        ),
        additional_kwargs={"visible_to": {"main_agent"}},
    )


async def get_memory_message(
    user_id: str,
    query: str,
    user_name: Optional[str] = None,
    user_timezone: Optional[str] = None,
    user_preferences: Optional[dict] = None,
) -> SystemMessage:
    """Create memory system message with user context (preferences, timezone, times) and optional memories.

    This message ALWAYS returns (even if no memories exist) to provide:
    - User preferences (profession, response style, custom instructions)
    - User's name
    - Current UTC time
    - User's local timezone and time
    - Conversation memories (if available)

    Args:
        user_id: User's ID for memory search
        query: Search query for retrieving relevant memories
        user_name: User's full name (already available from user dict)
        user_timezone: User's timezone (already available from user dict)
        user_preferences: User's onboarding preferences (already available from user dict)

    Returns:
        SystemMessage with user context and memories
    """
    from zoneinfo import ZoneInfo

    try:
        context_parts = []

        # Add user name context
        if user_name:
            context_parts.append(f"User Name: {user_name}")

        # Add user preferences if available
        if user_preferences:
            if formatted_prefs := format_user_preferences_for_agent(user_preferences):
                context_parts.append(f"\nUser Preferences:\n{formatted_prefs}")

        # Add time information
        utc_time = datetime.now(timezone.utc)
        formatted_utc_time = utc_time.strftime("%A, %B %d, %Y, %H:%M:%S UTC")
        context_parts.append(f"\nCurrent UTC Time: {formatted_utc_time}")

        # Add user's local timezone and time if available
        if user_timezone:
            try:
                user_tz = ZoneInfo(user_timezone)
                local_time = datetime.now(user_tz)
                formatted_local_time = local_time.strftime("%A, %B %d, %Y, %H:%M:%S")
                context_parts.append(f"User Timezone: {user_timezone}")
                context_parts.append(f"User Local Time: {formatted_local_time}")
            except Exception as e:
                logger.warning(f"Error formatting user local time: {e}")

        # Search for conversation memories
        memories_section = ""
        try:
            if results := await memory_service.search_memories(
                query=query, user_id=user_id, limit=5
            ):
                if memories := getattr(results, "memories", None):
                    memories_section = (
                        "\n\nBased on our previous conversations:\n"
                        + "\n".join(f"- {mem.content}" for mem in memories)
                    )
                    logger.info(f"Added {len(memories)} memories to context")
        except Exception as e:
            logger.warning(f"Error retrieving memories: {e}")

        # Combine all sections
        content = "\n".join(context_parts) + memories_section
        return SystemMessage(
            content=content,
            memory_message=True,
            additional_kwargs={"visible_to": {"main_agent"}},
        )

    except Exception as e:
        logger.error(f"Error creating memory message: {e}")
        # Return minimal context on error
        utc_time_str = datetime.now(timezone.utc).strftime(
            "%A, %B %d, %Y, %H:%M:%S UTC"
        )
        return SystemMessage(
            content=f"Current UTC Time: {utc_time_str}",
            memory_message=True,
            additional_kwargs={"visible_to": {"main_agent"}},
        )


def format_tool_selection_message(selected_tool: str, existing_content: str) -> str:
    """Format tool selection message, handling both standalone and combined requests."""
    tool_name = selected_tool.replace("_", " ").title()
    retrieval_instruction = f"FIRST, call retrieve_tools with exact_tool_names=['{selected_tool}'] to make the tool available, THEN execute it."

    # If user provided content, append tool instruction to their message
    if existing_content:
        return f"""{existing_content}

**TOOL SELECTION:** The user has specifically selected the '{tool_name}' tool (exact name: {selected_tool}) to handle their request above.

{retrieval_instruction} Do not use semantic search queries - use the exact tool name provided. Follow your system prompt instructions for provider-specific tools and use appropriate handoff tools when needed. Do not ask for additional information - execute the selected functionality now."""

    # Pure tool execution without user message
    return f"""**TOOL EXECUTION REQUEST:** The user has selected the '{tool_name}' tool (exact name: {selected_tool}) and wants you to execute it immediately.

{retrieval_instruction} Do not use semantic search queries - use the exact tool name provided. Follow your system prompt instructions for provider-specific tools and use appropriate handoff tools when needed. Do not ask for additional information or clarification - proceed with executing the selected tool functionality right away."""


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


def format_calendar_event_context(
    selected_calendar_event: SelectedCalendarEventData, existing_content: str = ""
) -> str:
    """Format calendar event context for AI conversation."""
    event = selected_calendar_event

    # Format time
    if event.isAllDay:
        time = f"All day on {event.start.get('date', 'Unknown date')}"
    else:
        time = f"{event.start.get('dateTime', 'Unknown')} to {event.end.get('dateTime', 'Unknown')}"

    # Build context
    context = f"""**CALENDAR EVENT:** {event.summary}
Description: {event.description or "None"}
Time: {time}"""

    if event.calendarTitle:
        context += f"\nCalendar: {event.calendarTitle}"

    return f"{context}\n\n{existing_content}" if existing_content else context


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
