"""
Follow-up Actions Node for the conversational graph.

This module provides functionality to suggest contextual follow-up actions
to users based on the conversation context and tool usage patterns.
"""

from typing import List

from app.agents.llm.client import init_llm
from app.config.loggers import chat_logger as logger
from app.templates.docstrings.follow_up_actions_tool_docs import (
    SUGGEST_FOLLOW_UP_ACTIONS,
)
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State
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
    from app.agents.tools.core.registry import get_tool_registry

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

    tool_registry = await get_tool_registry()
    llm = init_llm()

    try:
        messages = state.get("messages", [])

        # Skip if insufficient conversation history for meaningful suggestions
        if not messages or len(messages) < 2:
            try:
                writer({"follow_up_actions": []})
            except Exception:
                pass  # Stream closed, ignore
            return state

        # Set up structured output parsing
        parser = PydanticOutputParser(pydantic_object=FollowUpActions)
        recent_messages = messages[-4:] if len(messages) > 4 else messages

        prompt = SUGGEST_FOLLOW_UP_ACTIONS.format(
            conversation_summary=recent_messages,
            tool_names=tool_registry.get_tool_names(),
            format_instructions=parser.get_format_instructions(),
        )

        result = await llm.ainvoke(
            input=[
                SystemMessage(content=prompt),
                HumanMessage(content=_pretty_print_messages(recent_messages)),
            ],
            config={**config, "silent": True},  # type: ignore
        )
        try:
            actions = parser.parse(result if isinstance(result, str) else result.text())
        except Exception as parse_exc:
            logger.error(f"Error parsing follow-up actions: {parse_exc}")
            try:
                writer({"follow_up_actions": []})
            except Exception:
                pass  # Stream closed, ignore
            return state

        # Always stream follow-up actions, even if empty
        try:
            writer({"follow_up_actions": actions.actions if actions.actions else []})
        except Exception:
            pass  # Stream closed, ignore
        return state

    except Exception as e:
        logger.error(f"Error in follow-up actions node: {e}")
        try:
            writer({"follow_up_actions": []})
        except Exception:
            pass  # Stream closed, client already disconnected
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
