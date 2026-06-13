from typing import Literal

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from app.helpers.message_helpers import (
    build_current_time_message,
    build_dynamic_context_message,
    create_system_message,
    format_calendar_event_context,
    format_files_list,
    format_reply_context,
    format_tool_selection_message,
    format_workflow_execution_message,
    get_onboarding_system_prompt_if_applicable,
)
from app.models.message_models import (
    FileData,
    MessageDict,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)


async def construct_langchain_messages(
    messages: list[MessageDict],
    files_data: list[FileData] | None = None,
    currently_uploaded_file_ids: list[str] | None = [],
    user_id: str | None = None,
    user_name: str | None = None,
    user_dict: dict | None = None,
    query: str | None = None,
    selected_tool: str | None = None,
    tool_category: str | None = None,
    selected_workflow: SelectedWorkflowData | None = None,
    selected_calendar_event: SelectedCalendarEventData | None = None,
    reply_to_message: ReplyToMessageData | None = None,
    trigger_context: dict | None = None,
    agent_type: Literal["comms", "executor"] = "comms",
    active_todo_id: str | None = None,
    execution_mode: Literal["interactive", "background"] = "interactive",
    conversation_id: str | None = None,
    source: str | None = None,
) -> list[AnyMessage]:
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
    # Static per-channel main prompt — byte-identical across every user on
    # this channel, so the provider's implicit prompt cache can match across
    # users. Web/mobile/desktop get the OpenUI-capable variant; text-only
    # platforms get their formatting-restrictions variant.
    system_msg = create_system_message(
        user_id=user_id,
        user_name=user_name,
        agent_type=agent_type,
        source=source,
    )

    user_timezone = user_dict.get("timezone") if user_dict else None
    onboarding = user_dict.get("onboarding", {}) if user_dict else {}
    user_preferences = onboarding.get("preferences") if onboarding else None
    writing_style = onboarding.get("writing_style") if onboarding else None

    # Dynamic-context SystemMessage — user name, preferences, memories,
    # tracked-todos, and (on bound / headless runs) run-binding banners.
    # Intentionally does NOT contain the clock or any output-format
    # instructions; both live elsewhere to protect the cache prefix.
    dynamic_msg = await build_dynamic_context_message(
        user_id=user_id,
        query=query,
        user_name=user_name,
        user_timezone=user_timezone,
        user_preferences=user_preferences,
        writing_style=writing_style,
        source=source,
        active_todo_id=active_todo_id,
        execution_mode=execution_mode,
    )
    # Current time lives in a HumanMessage in ``contents`` (not
    # ``system_instruction``) so minute ticks never invalidate the cache
    # prefix. See ``build_current_time_message`` for the full reasoning.
    time_msg = build_current_time_message(user_timezone=user_timezone)
    chain_msgs: list[AnyMessage] = [system_msg, dynamic_msg, time_msg]

    # Extract user's latest message content
    user_content = (
        messages[-1].get("content", "").strip()
        if messages and messages[-1].get("role") == "user"
        else ""
    )

    # Tagged memory_message so manage_system_prompts_node preserves it alongside
    # the main comms agent prompt.
    if user_id and conversation_id:
        onboarding_prompt = await get_onboarding_system_prompt_if_applicable(
            user_id, conversation_id, latest_user_message=user_content
        )
        if onboarding_prompt:
            chain_msgs.append(SystemMessage(content=onboarding_prompt, memory_message=True))

    # Priority: workflow > calendar event > tool selection > user message
    content = (
        await format_workflow_execution_message(
            selected_workflow, user_id, trigger_context, user_content
        )
        if selected_workflow
        else format_calendar_event_context(selected_calendar_event, user_content)
        if selected_calendar_event
        else format_tool_selection_message(selected_tool, user_content, tool_category)
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
        files_str := format_files_list(files_data, currently_uploaded_file_ids, conversation_id)
    ):
        content += f"\n\n{files_str}"

    human_msg = HumanMessage(content=content)
    return [*chain_msgs, human_msg]
