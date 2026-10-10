from dataclasses import dataclass

from langchain_core.messages import AnyMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str

from app.agents.llm.chatbot import chatbot
from app.agents.prompts.convo_prompts import CONVERSATION_DESCRIPTION_GENERATOR
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationModel
from app.models.message_models import MessageDict, SelectedWorkflowData
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import (
    create_conversation_service,
    update_conversation_description,
)
from shared.py.wide_events import log


class _TurnContent(BaseModel):
    """The ``content`` of one ``MessageDict`` history turn, read once."""

    model_config = ConfigDict(extra="ignore")

    content: str


class _RunMetadata(BaseModel):
    """The user_id a run's config["metadata"] carries (stamped by build_agent_config)."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None


class _RunConfigMetadata(BaseModel):
    """The metadata view of a LangChain RunnableConfig, parsed once."""

    model_config = ConfigDict(extra="ignore")

    metadata: _RunMetadata = Field(default_factory=_RunMetadata)


class _ChatbotReply(BaseModel):
    """The {"messages": [...]} envelope chatbot returns, parsed once."""

    model_config = ConfigDict(extra="ignore")

    messages: list[BaseMessage]


@dataclass(slots=True, frozen=True)
class PromptResponse:
    """What do_prompt_no_stream returns: the model's reply text."""

    response: str


async def _generate_description_from_message(
    last_message: MessageDict | None,
    selectedTool: str | None,
    selectedWorkflow: SelectedWorkflowData | None,
) -> str:
    """Generate a conversation description from message context."""
    user_message = (
        _TurnContent.model_validate(last_message).content
        if last_message
        else "New conversation started"
    )

    workflow_context = f" - Workflow: {selectedWorkflow.title}" if selectedWorkflow else ""

    try:
        response = await do_prompt_no_stream(
            prompt=CONVERSATION_DESCRIPTION_GENERATOR.format(
                user_message=user_message,
                selectedTool=selectedTool,
                workflow_context=workflow_context,
            ),
        )

        return response.response.replace('"', "").strip()
    except Exception as e:
        log.error(
            f"{LogTag.CHAT} Failed to generate description",
            error=str(e),
            error_type=type(e).__name__,
        )
        return "New Chat"


@traceable(name="Create Conversation")
async def create_conversation(
    last_message: MessageDict | None,
    user: AuthenticatedUser,
    selectedTool: str | None | None,
    selectedWorkflow: SelectedWorkflowData | None | None = None,
    generate_description: bool = True,
    conversation_id: str | None = None,
) -> ConversationModel:
    """Create a new conversation with optional description generation.

    Args:
        generate_description: if False, uses "New Chat" as a placeholder instead of generating one
        conversation_id: optional pre-generated id, for background streaming
    """
    log.set(user_id=user.user_id, selected_tool=selectedTool)
    # Use provided ID or generate new one
    uuid_value = conversation_id or uuid7str()

    description = (
        "New Chat"
        if not generate_description
        else await _generate_description_from_message(last_message, selectedTool, selectedWorkflow)
    )

    conversation = ConversationModel(
        conversation_id=str(uuid_value),
        description=description,
    )

    await create_conversation_service(conversation, user)

    return conversation


@traceable(name="Generate Conversation Description")
async def generate_and_update_description(
    conversation_id: str,
    last_message: MessageDict | None,
    user: AuthenticatedUser,
    selectedTool: str | None | None,
    selectedWorkflow: SelectedWorkflowData | None | None = None,
) -> str:
    """Generate a description for an existing conversation and update it."""
    description = await _generate_description_from_message(
        last_message, selectedTool, selectedWorkflow
    )

    try:
        await update_conversation_description(conversation_id, description, user)
    except Exception as e:
        log.error(
            f"{LogTag.CHAT} Failed to persist description to DB for",
            conversation_id=conversation_id,
            error=str(e),
            error_type=type(e).__name__,
        )

    return description


async def do_prompt_no_stream(
    prompt: str,
    system_prompt: str | None = None,
) -> PromptResponse:
    """Execute a single LLM prompt without streaming; returns the AI's reply."""
    messages: list[AnyMessage] = [SystemMessage(content=system_prompt)] if system_prompt else []
    messages.append(HumanMessage(content=prompt))

    response = await chatbot(messages)

    # BaseMessage.text handles both plain-string and list-of-blocks content uniformly.
    ai_message = _ChatbotReply.model_validate(response).messages[0]
    return PromptResponse(response=ai_message.text)


def get_user_id_from_config(config: RunnableConfig) -> str:
    """Extract user ID from the config."""
    if not config:
        log.error(f"{LogTag.CHAT} Tool called without config")
        return ""

    user_id = _RunConfigMetadata.model_validate(config).metadata.user_id or ""

    if not user_id:
        log.error(f"{LogTag.CHAT} No user_id found in config metadata")

    return user_id
