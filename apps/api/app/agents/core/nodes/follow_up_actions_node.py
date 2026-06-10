"""Follow-up actions node: suggests contextual follow-up actions from
conversation context and tool usage."""

from typing import cast

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore
from langgraph.types import StreamWriter
from pydantic import BaseModel, Field

from app.agents.llm.client import get_free_llm_chain, invoke_with_fallback
from app.agents.tools.core.registry import get_tool_registry
from app.constants.general import CALL_EXECUTOR_NAME
from app.override.langgraph_bigtool.utils import State
from app.services.integrations.user_integrations import (
    get_user_integration_capabilities,
)
from app.templates.docstrings.follow_up_actions_tool_docs import (
    SUGGEST_FOLLOW_UP_ACTIONS,
)
from shared.py.wide_events import log


class FollowUpActions(BaseModel):
    """Data structure for follow-up action suggestions."""

    actions: list[str] = Field(
        description="Array of 3-4 follow-up action suggestions for the user. Each action should be clear, actionable, contextually relevant, and under 50 characters."
    )


async def generate_follow_up_actions(
    context_text: str,
    user_id: str | None,
    config: RunnableConfig,
) -> list[str]:
    """Generate 3-4 contextual follow-up suggestions from conversation context.

    Shared by the comms end-graph hook and the background executor's final
    result message so suggestions are produced consistently in both paths.
    Returns an empty list on any failure (never raises).
    """
    if user_id:
        capabilities = await get_user_integration_capabilities(user_id)
        tool_names = capabilities.get("tool_names", [])
    else:
        # Fallback to all tools if user_id not available
        tool_registry = await get_tool_registry()
        tool_names = tool_registry.get_tool_names()

    parser = PydanticOutputParser(pydantic_object=FollowUpActions)

    # STATIC prompt prefix + DYNAMIC per-user/per-turn context message.
    # Static byte-identical prefix lets even this free-tier chain benefit
    # from any upstream caching and reduces throughput/latency.
    dynamic_context = (
        f"{parser.get_format_instructions()}\n\n"
        f"Available tools: {tool_names}\n"
        f"Context: {context_text}"
    )

    llm_chain = get_free_llm_chain()
    try:
        result = await invoke_with_fallback(
            llm_chain,
            [
                SystemMessage(content=SUGGEST_FOLLOW_UP_ACTIONS),
                SystemMessage(
                    content=dynamic_context,
                    additional_kwargs={
                        "dynamic_context": True,
                        "memory_message": True,
                    },
                ),
                HumanMessage(content=context_text),
            ],
            config=cast(RunnableConfig, {**config, "silent": True}),
        )
        actions = parser.parse(result if isinstance(result, str) else result.text)
        return actions.actions if actions.actions else []
    except Exception as e:
        log.debug(f"Follow-up action generation failed: {e}")
        return []


async def follow_up_actions_node(state: State, config: RunnableConfig, store: BaseStore) -> State:
    """Analyze conversation context and stream relevant follow-up actions.

    Follow-up actions are streamed, not stored in state.
    """
    # Send completion marker as soon as follow-up actions start
    writer = get_stream_writer()
    try:
        writer({"main_response_complete": True})
    except Exception as write_error:
        # Stream is closed (user disconnected), no need to continue
        log.debug(f"Stream already closed when sending completion marker: {write_error}")
        return state

    messages = state.get("messages", [])

    # When this turn delegated to a background executor, the executor produces
    # the user-visible answer as a separate message and attaches its own
    # follow-up actions there. Emitting them here would attach them to the
    # intermediate comms acknowledgement, where they flash then vanish once the
    # executor's result message supersedes it.
    if _delegated_to_executor(messages):
        log.debug("Skipping comms follow-ups: turn delegated to executor")
        return state

    # Skip if insufficient conversation history for meaningful suggestions
    if not messages or len(messages) < 2:
        _safe_write_actions(writer, [])
        return state

    user_id = config.get("configurable", {}).get("user_id")
    recent_messages = messages[-4:] if len(messages) > 4 else messages

    log.set(
        follow_up_actions={
            "recent_message_count": len(recent_messages),
            "user_id": user_id,
        }
    )

    actions = await generate_follow_up_actions(
        _pretty_print_messages(recent_messages), user_id, config
    )
    _safe_write_actions(writer, actions)
    return state


def _safe_write_actions(writer: StreamWriter, actions: list[str]) -> None:
    """Stream follow-up actions, swallowing closed-stream errors."""
    try:
        writer({"follow_up_actions": actions})
    except Exception as e:
        log.debug(f"Stream closed when sending follow-up actions: {e}")


def _delegated_to_executor(messages: list[AnyMessage]) -> bool:
    """True if the current turn invoked the ``call_executor`` tool.

    Scoped to messages after the last human turn so a delegation from an
    earlier turn doesn't suppress follow-ups on a later, non-delegating turn.
    """
    last_human = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human = i
            break

    for message in messages[last_human + 1 :]:
        tool_calls = getattr(message, "tool_calls", None) or []
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name == CALL_EXECUTOR_NAME:
                return True
    return False


def _pretty_print_messages(messages: list[AnyMessage], ignore_system_messages=True) -> str:
    pretty = ""
    for message in messages:
        if ignore_system_messages and isinstance(message, SystemMessage):
            continue
        pretty += message.pretty_repr()
    return pretty
