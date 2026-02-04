from datetime import datetime, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from langchain_core.messages import SystemMessage

from app.agents.prompts.workflow_prompts import (
    EMAIL_TRIGGERED_WORKFLOW_PROMPT,
    WORKFLOW_EXECUTION_PROMPT,
)
from app.agents.templates.agent_template import (
    COMMS_PROMPT_TEMPLATE,
    EXECUTOR_PROMPT_TEMPLATE,
)
from app.config.constants import GAIA_MEM0_AGENT_ID
from app.config.loggers import llm_logger as logger
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.services.memory_service import memory_service
from app.services.workflow import WorkflowService
from app.utils.user_preferences_utils import (
    format_user_preferences_for_agent,
)


def create_system_message(
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    agent_type: Literal["comms", "executor"] = "comms",
) -> SystemMessage:
    """Create main system message with user name only.

    Args:
        user_id: User's ID
        user_name: User's full name
        agent_type: Type of agent - "comms", "executor", or "main" (legacy)
    """
    template = {
        "comms": COMMS_PROMPT_TEMPLATE,
        "executor": EXECUTOR_PROMPT_TEMPLATE,
    }.get(agent_type, COMMS_PROMPT_TEMPLATE)

    return SystemMessage(content=template.format(user_name=user_name or "there"))


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

        # Search for agent memories (Gaia's self-knowledge)
        agent_memories_section = ""
        try:
            if GAIA_MEM0_AGENT_ID:
                if agent_results := await memory_service.search_agent_memories(
                    query=query, agent_id=GAIA_MEM0_AGENT_ID, limit=5
                ):
                    if agent_memories := getattr(agent_results, "memories", None):
                        agent_memories_section = (
                            "\n\nAbout Gaia (your identity and capabilities):\n"
                            + "\n".join(f"- {mem.content}" for mem in agent_memories)
                        )
                        logger.info(
                            f"Added {len(agent_memories)} agent memories to context"
                        )
        except Exception as e:
            logger.warning(f"Error retrieving agent memories: {e}")

        # Combine all sections
        content = "\n".join(context_parts) + memories_section + agent_memories_section
        return SystemMessage(content=content, memory_message=True)

    except Exception as e:
        logger.error(f"Error creating memory message: {e}")
        # Return minimal context on error
        utc_time_str = datetime.now(timezone.utc).strftime(
            "%A, %B %d, %Y, %H:%M:%S UTC"
        )
        return SystemMessage(
            content=f"Current UTC Time: {utc_time_str}", memory_message=True
        )


def format_tool_selection_message(
    selected_tool: str, existing_content: str, tool_category: Optional[str] = None
) -> str:
    """Format tool selection message, handling both standalone and combined requests.

    The comms_agent delegates to executor via call_executor. The executor will
    use semantic search to find the right tool/subagent, then execute.
    """
    tool_name = selected_tool.replace("_", " ").title()
    search_hint = f"{selected_tool} {tool_category}" if tool_category else selected_tool

    # If user provided content, append tool instruction to their message
    if existing_content:
        return f"""{existing_content}

**TOOL SELECTION:** The user has specifically selected the '{tool_name}' tool (category: {tool_category or "general"}).

Use call_executor to delegate this task. The executor should:
1. Use `retrieve_tools(query="{search_hint}")` to find the tool or subagent
2. If a subagent is returned (e.g. subagent:{tool_category}), use `handoff(subagent_id="{tool_category}", task="Use {selected_tool} to [user's request]")`
3. If a direct tool is returned, bind it with `retrieve_tools(exact_tool_names=[...])` and execute

Execute immediately without asking for clarification."""

    # Pure tool execution without user message
    return f"""**TOOL EXECUTION REQUEST:** The user has selected the '{tool_name}' tool (category: {tool_category or "general"}).

Use call_executor to delegate this task. The executor should:
1. Use `retrieve_tools(query="{search_hint}")` to find the tool or subagent
2. If a subagent is returned (e.g. subagent:{tool_category}), use `handoff(subagent_id="{tool_category}", task="Use {selected_tool} to execute the user's request")`
3. If a direct tool is returned, bind it with `retrieve_tools(exact_tool_names=[...])` and execute

Execute immediately without asking for clarification."""


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
            f"{i}. **{step.title}** (Category: {step.category})\n   Description: {step.description}"
            for i, step in enumerate(workflow.steps, 1)
        )
        workflow_title = workflow.title
        workflow_description = workflow.description
    else:
        # Fallback to passed data
        steps_text = "\n".join(
            f"{i}. **{step['title']}** (Category: {step['category']})\n   Description: {step['description']}"
            for i, step in enumerate(selected_workflow.steps, 1)
        )
        workflow_title = selected_workflow.title
        workflow_description = selected_workflow.description

    common_args = {
        "workflow_title": workflow_title,
        "workflow_description": workflow_description,
        "workflow_steps": steps_text,
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


def format_reply_context(
    reply_to_message: ReplyToMessageData, existing_content: str = ""
) -> str:
    """Format reply-to-message context for AI conversation.

    This adds context about which message the user is replying to,
    helping the AI understand the conversation thread context.
    """
    role_label = "their own" if reply_to_message.role == "user" else "your"

    context = f"""[The user is responding to {role_label} earlier message: "{reply_to_message.content}"]"""

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

    return f"""
Uploaded Files:
{file_list}

You can use these files in your conversation. If you need to refer to them, use the file IDs provided.
You must use query_files to retrieve file content or metadata.
"""
