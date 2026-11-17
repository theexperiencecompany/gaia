"""How comms says which of the user's messages it dealt with, and ends a turn not worth a message.

Each is a tool call, so the choice arrives as arguments its schema validated, never inside
reply text. Every one names the messages it closes by their [#n] handle; a message stays open
until one does. The comms graph ends the turn after a step whose calls are all of these
(turn_ending), so no model call follows.
"""

from collections.abc import Sequence
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException, tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field, ValidationError

from app.agents.core.comms_ledger import Closing, close
from app.constants.chat import ConversationSource
from app.constants.comms import ANSWERED_TOOL_NAME, REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from app.constants.conversation import LOG_SEQ
from app.constants.reactions import (
    OFFENSIVE_REACTION_EMOJI,
    REACTION_PALETTE_BY_SURFACE,
    surface_reaction,
)
from app.models.agent_config import read_agent_configurable
from app.utils.multimodal import extract_text_content
from shared.py.analytics.catalog.properties import Emoji

_HANDLES = "The [#n] handles of the user's messages, as numbers (#7 is 7)."


class AnsweredArgs(BaseModel):
    message_ids: list[int] = Field(min_length=1, description=_HANDLES)


class ReactArgs(BaseModel):
    emoji: Emoji = Field(description="Exactly one emoji, nothing else.")
    message_id: int = Field(description="The [#n] handle of the message to react to, as a number.")


class StaySilentArgs(BaseModel):
    reason: str = Field(description="Why nothing is worth saying. For the logs, never shown.")
    message_ids: list[int] = Field(
        default_factory=list,
        description=f"{_HANDLES} Empty when no message is open (a background result, a hand-off).",
    )


def reaction_refusal(surface: ConversationSource, emoji: str) -> str:
    """Return why the surface refused emoji (surface_reaction gave None), for the model to pick again."""
    allowed = REACTION_PALETTE_BY_SURFACE.get(surface)
    if emoji in OFFENSIVE_REACTION_EMOJI or allowed is None:
        return f"{emoji} is not a reaction GAIA uses. Pick another emoji, or reply in words."
    return (
        f"{surface.display_name} does not accept {emoji} as a reaction. "
        f"Pick exactly one of: {' '.join(allowed)}"
    )


@tool(ANSWERED_TOOL_NAME)
async def answered(
    message_ids: Annotated[list[int], _HANDLES],
    config: RunnableConfig,
    messages: Annotated[list[AnyMessage], InjectedState("messages")],
) -> str:
    """Name the user's messages your reply answers, when two or more are open; with one open, your reply answers it.

    Write the reply's words in this same message first: this only names them. Alone, it ends
    your turn; beside other calls (a lookup, a hand-off), the turn goes on. Example: "36" with
    answered([6]) beside the next lookup, while #4 stays open for the research.
    """
    unworded = unanswered_in_words(messages, message_ids)
    if unworded:
        raise ToolException(
            f"Nothing you wrote answers {', '.join(f'#{seq}' for seq in unworded)} yet. "
            "Write the answer in your reply, then name it."
        )
    close(config, Closing.ANSWERED, message_ids)
    return "Noted."


def unanswered_in_words(messages: Sequence[AnyMessage], seqs: Sequence[int]) -> list[int]:
    """Return the seqs no reply text written after that message could answer."""
    arrived = {
        seq: index
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
        and isinstance(seq := message.additional_kwargs.get(LOG_SEQ), int)
    }
    worded = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, AIMessage) and extract_text_content(message.content).strip()
    ]
    since = {seq: arrived.get(seq, len(messages)) for seq in seqs}
    # `>=` reads the same: a reply's index is never a user message's, nor len(messages).
    return [seq for seq in seqs if not any(i > since[seq] for i in worded)]  # pragma: no mutate


@tool(REACT_TOOL_NAME, args_schema=ReactArgs)
async def react(emoji: str, message_id: int, config: RunnableConfig) -> str:
    """Answer one message with a tap-back reaction instead of words; ends your turn.

    It shows as a reaction on that message, or as the bare emoji where the platform has
    none. Write no text beside it.
    """
    surface = read_agent_configurable(config).surface()
    spelled = surface_reaction(surface, emoji)
    if spelled is None:
        return reaction_refusal(surface, emoji)
    close(config, Closing.REACTED, [message_id], spelled)
    return f"Reacted {spelled}."


@tool(STAY_SILENT_TOOL_NAME, args_schema=StaySilentArgs)
async def stay_silent(
    reason: str, config: RunnableConfig, message_ids: list[int] | None = None
) -> str:
    """Send the user nothing for these messages; ends your turn. Write no text beside it."""
    del reason
    if message_ids:
        close(config, Closing.SILENT, message_ids)
    return "Sent nothing."


_ENDINGS: dict[str, type[AnsweredArgs | ReactArgs | StaySilentArgs]] = {
    ANSWERED_TOOL_NAME: AnsweredArgs,
    REACT_TOOL_NAME: ReactArgs,
    STAY_SILENT_TOOL_NAME: StaySilentArgs,
}


def turn_ending(
    message: AIMessage, config: RunnableConfig
) -> AnsweredArgs | ReactArgs | StaySilentArgs | None:
    """Return how a model message ends the turn; None when it calls work, or calls nothing.

    Only a message whose every call is a turn ending, each valid by its schema and a reaction
    the run's surface accepts, ends the turn: an invalid one goes back to the model as a failed call.
    A reaction or silence wins over answered when a step makes both: it decides the outcome.
    """
    calls: list[ToolCall] = message.tool_calls
    if not calls or any(call["name"] not in _ENDINGS for call in calls):
        return None
    try:
        endings = [_ENDINGS[call["name"]].model_validate(call["args"]) for call in calls]
    except ValidationError:
        return None
    reactions = [ending.emoji for ending in endings if isinstance(ending, ReactArgs)]
    if reactions:
        surface = read_agent_configurable(config).surface()
        if any(surface_reaction(surface, emoji) is None for emoji in reactions):
            return None
    wordless = [ending for ending in endings if not isinstance(ending, AnsweredArgs)]
    return wordless[0] if wordless else endings[0]
