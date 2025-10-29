from typing import List, Optional

from app.helpers.message_helpers import (
    create_system_message,
    format_files_list,
    format_tool_selection_message,
    format_workflow_execution_message,
    get_memory_message,
)
from app.models.message_models import FileData, MessageDict, SelectedWorkflowData
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
    trigger_context: Optional[dict] = None,
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
        trigger_context: Email/automation context for workflows

    Returns:
        List of LangChain messages ready for agent processing
    """
    # Start with system message containing user name and instructions
    system_msg = await create_system_message(user_id, user_name)
    chain_msgs = [system_msg]

    # Add relevant memories if user context available
    if user_id and query and (memory_msg := await get_memory_message(user_id, query)):
        # Set agent name so memory messages pass through filtering and trimming
        memory_msg.name = "main_agent"
        chain_msgs.append(memory_msg)

    # Extract user's latest message content
    user_content = (
        messages[-1].get("content", "").strip()
        if messages and messages[-1].get("role") == "user"
        else ""
    )

    # Priority: workflow > tool selection > user message
    content = (
        await format_workflow_execution_message(
            selected_workflow, user_id, trigger_context, user_content
        )
        if selected_workflow
        else format_tool_selection_message(selected_tool, user_content)
        if selected_tool
        else user_content
    )

    if not content:
        raise ValueError("No human message or selected tool")

    # Append file context if files are uploaded
    if currently_uploaded_file_ids and (
        files_str := format_files_list(files_data, currently_uploaded_file_ids)
    ):
        content += f"\n\n{files_str}"

    human_msg = HumanMessage(content=content)
    human_msg.name = "main_agent"
    return [*chain_msgs, human_msg]
