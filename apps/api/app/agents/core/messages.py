from typing import List, Literal, Optional

from app.helpers.message_helpers import (
    create_system_message,
    format_calendar_event_context,
    format_files_list,
    format_reply_context,
    format_tool_selection_message,
    format_workflow_execution_message,
    get_memory_message,
)
from app.models.message_models import (
    FileData,
    MessageDict,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from langchain_core.messages import AnyMessage, HumanMessage


async def construct_langchain_messages(
    messages: List[MessageDict],
    files_data: List[FileData] | None = None,
    currently_uploaded_file_ids: Optional[List[str]] = [],
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    user_dict: Optional[dict] = None,
    query: Optional[str] = None,
    selected_tool: Optional[str] = None,
    selected_workflow: Optional[SelectedWorkflowData] = None,
    selected_calendar_event: Optional[SelectedCalendarEventData] = None,
    reply_to_message: Optional[ReplyToMessageData] = None,
    trigger_context: Optional[dict] = None,
    agent_type: Literal["comms", "executor"] = "comms",
) -> List[AnyMessage]:
    """
    Construct LangChain messages for agent interaction.

    Builds a conversation from system prompt + optional memory + human message.
    LangChain checkpointer handles conversation history, so we only process current input.

    Args:
        messages: Raw message history (only latest user message is used)
        files_data: Available file objects
        currently_uploaded_file_ids: IDs of files to include in context
        user_id: For retrieving user preferences and memories
        user_name: Personalization for system prompt
        user_dict: Complete user dictionary with timezone, preferences, etc. (from auth)
        query: Search query for memory retrieval (typically latest user message)
        selected_tool: Tool chosen via slash command (overrides normal flow)
        selected_workflow: Workflow to execute (overrides everything else)
        selected_calendar_event: Calendar event selected for context
        reply_to_message: Message being replied to (adds conversation thread context)
        trigger_context: Email/automation context for workflows
        agent_type: Type of agent - "comms", "executor", or "main" (legacy)

    Returns:
        List of LangChain messages ready for agent processing
    """
    # Start with system message containing user name and instructions
    system_msg = create_system_message(user_id, user_name, agent_type)
    chain_msgs = [system_msg]

    # Add relevant memories if user context available
    if user_id and query:
        user_timezone = user_dict.get("timezone") if user_dict else None
        user_preferences = (
            user_dict.get("onboarding", {}).get("preferences") if user_dict else None
        )

        memory_msg = await get_memory_message(
            user_id=user_id,
            query=query,
            user_name=user_name,
            user_timezone=user_timezone,
            user_preferences=user_preferences,
        )

        if memory_msg:
            chain_msgs.append(memory_msg)

    # Extract user's latest message content
    user_content = (
        messages[-1].get("content", "").strip()
        if messages and messages[-1].get("role") == "user"
        else ""
    )

    # Priority: workflow > calendar event > tool selection > user message
    content = (
        await format_workflow_execution_message(
            selected_workflow, user_id, trigger_context, user_content
        )
        if selected_workflow
        else format_calendar_event_context(selected_calendar_event, user_content)
        if selected_calendar_event
        else format_tool_selection_message(selected_tool, user_content)
        if selected_tool
        else user_content
    )

    if not content:
        raise ValueError("No human message or selected tool")

    # Add reply-to-message context if present
    if reply_to_message:
        content = format_reply_context(reply_to_message, content)

    # Append file context if files are uploaded
    if currently_uploaded_file_ids and (
        files_str := format_files_list(files_data, currently_uploaded_file_ids)
    ):
        content += f"\n\n{files_str}"

    human_msg = HumanMessage(content=content)
    return [*chain_msgs, human_msg]
