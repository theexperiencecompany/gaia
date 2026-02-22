"""
Follow-up Actions Node for the conversational graph.

This module provides functionality to suggest contextual follow-up actions
to users based on the conversation context and tool usage patterns.
"""

from typing import List, cast

from app.agents.llm.client import get_free_llm_chain, invoke_with_fallback
from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import chat_logger as logger
from app.override.langgraph_bigtool.utils import State
from app.services.integrations.user_integrations import (
    get_user_integration_capabilities,
)
from app.templates.docstrings.follow_up_actions_tool_docs import (
    SUGGEST_FOLLOW_UP_ACTIONS,
)
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field


class FollowUpActions(BaseModel):
    """Data structure for follow-up action suggestions."""

    actions: List[str] = Field(
        description="Array of 3-4 follow-up action suggestions for the user. Each action should be clear, actionable, contextually relevant, and under 50 characters."
    )


async def follow_up_actions_node(
    state: State, config: RunnableConfig, store: BaseStore
) -> State:
    """
    Analyze conversation context and suggest relevant follow-up actions.

    Args:
        state: The current state of the conversation

    Returns:
        Empty dict indicating successful completion (follow-up actions are streamed, not stored in state)
    """
    # Send completion marker as soon as follow-up actions start
    writer = get_stream_writer()
    try:
        writer({"main_response_complete": True})
    except Exception as write_error:
        # Stream is closed (user disconnected), no need to continue
        logger.debug(
            f"Stream already closed when sending completion marker: {write_error}"
        )
        return state

    llm_chain = get_free_llm_chain()

    try:
        messages = state.get("messages", [])

        # Skip if insufficient conversation history for meaningful suggestions
        if not messages or len(messages) < 2:
            try:
                writer({"follow_up_actions": []})
            except Exception as e:
                logger.debug(f"Stream closed when sending empty actions: {e}")
            return state

        # Get user-specific integration capabilities (cached)
        user_id = config.get("configurable", {}).get("user_id")
        if user_id:
            capabilities = await get_user_integration_capabilities(user_id)
            tool_names = capabilities.get("tool_names", [])
        else:
            # Fallback to all tools if user_id not available
            tool_registry = await get_tool_registry()
            tool_names = tool_registry.get_tool_names()

        # Set up structured output parsing
        parser = PydanticOutputParser(pydantic_object=FollowUpActions)
        recent_messages = messages[-4:] if len(messages) > 4 else messages

        prompt = SUGGEST_FOLLOW_UP_ACTIONS.format(
            conversation_summary=recent_messages,
            tool_names=tool_names,
            format_instructions=parser.get_format_instructions(),
        )

        result = await invoke_with_fallback(
            llm_chain,
            [
                SystemMessage(content=prompt),
                HumanMessage(content=_pretty_print_messages(recent_messages)),
            ],
            config=cast(RunnableConfig, {**config, "silent": True}),
        )
        try:
            actions = parser.parse(result if isinstance(result, str) else result.text)
        except Exception:
            try:
                writer({"follow_up_actions": []})
            except Exception as e:
                logger.debug(f"Stream closed when sending error actions: {e}")
            return state

        # Always stream follow-up actions, even if empty
        try:
            writer({"follow_up_actions": actions.actions if actions.actions else []})
        except Exception as e:
            logger.debug(f"Stream closed when sending follow-up actions: {e}")
        return state

    except Exception as e:
        logger.error(f"Error in follow-up actions node: {e}")
        try:
            writer({"follow_up_actions": []})
        except Exception as write_error:
            logger.debug(f"Stream closed in error handler: {write_error}")
        return state


def _pretty_print_messages(
    messages: List[AnyMessage], ignore_system_messages=True
) -> str:
    pretty = ""
    for message in messages:
        if ignore_system_messages and isinstance(message, SystemMessage):
            continue
        pretty += message.pretty_repr()
    return pretty
