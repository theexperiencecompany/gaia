from typing import List, Optional

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable
from uuid_extensions import uuid7str

from app.agents.core.state import State
from app.agents.llm.chatbot import chatbot
from app.agents.prompts.convo_prompts import CONVERSATION_DESCRIPTION_GENERATOR
from app.config.loggers import chat_logger as logger
from app.models.message_models import MessageDict, SelectedWorkflowData
from app.services.conversation_service import (
    ConversationModel,
    create_conversation_service,
    update_conversation_description,
)


async def _generate_description_from_message(
    last_message: MessageDict | None,
    selectedTool: Optional[str],
    selectedWorkflow: Optional[SelectedWorkflowData],
) -> str:
    """Helper to generate conversation description from message context."""
    user_message = (
        last_message.get("content")
        if last_message and "content" in last_message
        else "New conversation started"
    )

    workflow_context = (
        f" - Workflow: {selectedWorkflow.title}" if selectedWorkflow else ""
    )

    try:
        response = await do_prompt_no_stream(
            prompt=CONVERSATION_DESCRIPTION_GENERATOR.format(
                user_message=user_message,
                selectedTool=selectedTool,
                workflow_context=workflow_context,
            ),
        )

        if not isinstance(response, dict) or "response" not in response:
            logger.error("Invalid response from LLM for description generation")
            return "New Chat"

        return response.get("response", "New Chat").replace('"', "").strip()
    except Exception as e:
        logger.error(f"Failed to generate description: {e}")
        return "New Chat"


@traceable(name="Create Conversation")
async def create_conversation(
    last_message: MessageDict | None,
    user: dict,
    selectedTool: Optional[str] | None,
    selectedWorkflow: Optional[SelectedWorkflowData] | None = None,
    generate_description: bool = True,
    conversation_id: Optional[str] = None,
) -> dict:
    """
    Create a new conversation with optional description generation.

    Args:
        last_message: The user's message to generate description from
        user: User information
        selectedTool: Optional tool selection
        selectedWorkflow: Optional workflow selection
        generate_description: If False, uses "New Chat" as placeholder
        conversation_id: Optional pre-generated conversation ID (for background streaming)

    Returns:
        dict with conversation_id and conversation_description
    """
    # Use provided ID or generate new one
    uuid_value = conversation_id or uuid7str()

    description = (
        "New Chat"
        if not generate_description
        else await _generate_description_from_message(
            last_message, selectedTool, selectedWorkflow
        )
    )

    conversation = ConversationModel(
        conversation_id=str(uuid_value), description=description
    )

    await create_conversation_service(conversation, user)

    return {
        "conversation_id": conversation.conversation_id,
        "conversation_description": conversation.description,
    }


@traceable(name="Generate Conversation Description")
async def generate_and_update_description(
    conversation_id: str,
    last_message: MessageDict | None,
    user: dict,
    selectedTool: Optional[str] | None,
    selectedWorkflow: Optional[SelectedWorkflowData] | None = None,
) -> str:
    """
    Generate a description for an existing conversation and update it.

    Args:
        conversation_id: ID of the conversation to update
        last_message: The user's message to generate description from
        user: User information
        selectedTool: Optional tool selection
        selectedWorkflow: Optional workflow selection

    Returns:
        The generated description
    """
    description = await _generate_description_from_message(
        last_message, selectedTool, selectedWorkflow
    )

    await update_conversation_description(conversation_id, description, user)

    return description


async def do_prompt_no_stream(
    prompt: str,
    system_prompt: str | None = None,
    use_tools: bool = False,
) -> dict:
    """
    Execute a single LLM prompt without streaming.

    Args:
        prompt: The user prompt to send to the LLM
        system_prompt: Optional system message
        use_tools: Whether tools should be available (currently unused)

    Returns:
        dict with "response" key containing the AI's response content
    """
    messages: List[AnyMessage] = (
        [SystemMessage(content=system_prompt)] if system_prompt else []
    )
    messages.append(HumanMessage(content=prompt))

    state = State(messages=messages)
    response = await chatbot(state)

    # Extract the AI's response content
    ai_message = response["messages"][0]

    return {"response": ai_message.content}


def get_user_id_from_config(config: RunnableConfig) -> str:
    """Extract user ID from the config."""
    if not config:
        logger.error("Tool called without config")
        return ""

    metadata = config.get("metadata", {})
    user_id = metadata.get("user_id", "")

    if not user_id:
        logger.error("No user_id found in config metadata")

    return user_id


def get_user_name_from_config(config: RunnableConfig) -> str:
    """Extract user name from the config."""
    if not config:
        logger.error("Tool called without config")
        return ""

    metadata = config.get("metadata", {})
    user_name = metadata.get("user_name", "")

    if not user_name:
        logger.error("No user_name found in config metadata")

    return user_name
