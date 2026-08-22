from typing import Any, Literal

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import ONBOARDING_MARKER, mark
from app.agents.context.tiers import AgentTier
from app.helpers.message_helpers import (
    build_current_time_message,
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
from app.models.user_models import AuthenticatedUser
from app.services.files import FileService
from app.utils.user_preferences_utils import onboarding_preferences


async def construct_langchain_messages(
    messages: list[MessageDict],
    files_data: list[FileData] | None = None,
    currently_uploaded_file_ids: list[str] | None = None,
    user_id: str | None = None,
    user_name: str | None = None,
    user_dict: AuthenticatedUser | None = None,
    query: str | None = None,
    selected_tool: str | None = None,
    tool_category: str | None = None,
    selected_workflow: SelectedWorkflowData | None = None,
    selected_calendar_event: SelectedCalendarEventData | None = None,
    reply_to_message: ReplyToMessageData | None = None,
    # Open by construction: schedulers spread arbitrary provider trigger data
    # through this alongside the agent's own keys, so there is no fixed shape.
    trigger_context: dict[str, Any] | None = None,
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
    user_preferences, writing_style = onboarding_preferences(
        user_dict.get("onboarding") if user_dict else None
    )

    # Extract user's latest message content
    user_content = (
        messages[-1].get("content", "").strip()
        if messages and messages[-1].get("role") == "user"
        else ""
    )

    assembled = await assemble_context(
        SectionContext(
            tier=AgentTier.COMMS,
            user_id=user_id,
            user_name=user_name,
            user_timezone=user_timezone,
            user_preferences=user_preferences,
            writing_style=writing_style,
            query=query,
            active_todo_id=active_todo_id,
            execution_mode=execution_mode,
            source=source,
        )
    )

    # Its own slot, not the dynamic one. Tagged `memory_message` it competed with
    # the stable identity block for a single-occupant slot and — being emitted
    # later — won, so every onboarding turn silently reached the model with no
    # user name, timezone, preferences or integrations manifest.
    onboarding_msg: SystemMessage | None = None
    if user_id and conversation_id:
        onboarding_prompt = await get_onboarding_system_prompt_if_applicable(
            user_id, conversation_id, latest_user_message=user_content
        )
        if onboarding_prompt:
            onboarding_msg = mark(SystemMessage(content=onboarding_prompt), ONBOARDING_MARKER)

    # Current time lives in a HumanMessage in ``contents`` (not
    # ``system_instruction``) so minute ticks never invalidate the cache
    # prefix. See ``build_current_time_message``.
    time_msg = build_current_time_message(user_timezone=user_timezone)
    # Emitted in canonical slot order, so the hook chain's reordering is a
    # normalisation of correct input rather than a correction this tier relies on.
    chain_msgs: list[AnyMessage] = [system_msg, assembled.stable]
    if onboarding_msg is not None:
        chain_msgs.append(onboarding_msg)
    if assembled.volatile is not None:
        chain_msgs.append(assembled.volatile)

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

    # Append file context if files are uploaded. The summary is read server-side
    # from MongoDB (authoritative) — never trusted from the inbound request — in
    # a single batched query, then surfaced inline so comms knows each file's
    # content without a tool round-trip.
    if currently_uploaded_file_ids and files_data and user_id:
        descriptions = await FileService.get_descriptions(currently_uploaded_file_ids, user_id)
        for file in files_data:
            if file.fileId in descriptions:
                file.description = descriptions[file.fileId]

    if currently_uploaded_file_ids and (
        files_str := format_files_list(
            files_data,
            currently_uploaded_file_ids,
            conversation_id,
            include_processing_guide=False,
        )
    ):
        content += f"\n\n{files_str}"

    human_msg = HumanMessage(content=content)
    return [*chain_msgs, human_msg, time_msg]
