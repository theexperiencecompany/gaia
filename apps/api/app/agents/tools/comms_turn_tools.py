"""How comms ends a turn that is not worth a message: a reaction on the user's message, or nothing.

Each is a tool call, so the choice arrives as arguments its schema validated, never inside
reply text. The comms graph ends the turn after one (turn_ending), so no model call follows.
"""

from langchain_core.messages import AIMessage, ToolCall
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from app.constants.chat import ConversationSource
from app.constants.comms import REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from app.constants.reactions import OFFENSIVE_REACTION_EMOJI, REACTION_PALETTE_BY_SURFACE
from app.models.agent_config import read_agent_configurable
from shared.py.analytics.catalog.properties import Emoji


class ReactArgs(BaseModel):
    emoji: Emoji = Field(description="Exactly one emoji, nothing else.")


class StaySilentArgs(BaseModel):
    reason: str = Field(description="Why nothing is worth saying. For the logs, never shown.")


def reaction_refusal(emoji: str, config: RunnableConfig) -> str | None:
    """Return why emoji cannot be this run's reaction, for the model to pick again; None when it can."""
    if emoji in OFFENSIVE_REACTION_EMOJI:
        return f"{emoji} is not a reaction GAIA uses. Pick another emoji, or reply in words."
    surface = ConversationSource.coerce(read_agent_configurable(config).conversation_source)
    allowed = REACTION_PALETTE_BY_SURFACE.get(surface) if surface is not None else None
    if allowed is None or emoji in allowed:
        return None
    return (
        f"{surface.display_name} does not accept {emoji} as a reaction. "
        f"Pick exactly one of: {' '.join(allowed)}"
    )


@tool(REACT_TOOL_NAME, args_schema=ReactArgs)
async def react(emoji: str, config: RunnableConfig) -> str:
    """Answer with a tap-back reaction on the user's message instead of words; ends your turn.

    It shows as a reaction on their message, or as the bare emoji where the platform has
    none. Write no text beside it.
    """
    return reaction_refusal(emoji, config) or f"Reacted {emoji}."


@tool(STAY_SILENT_TOOL_NAME, args_schema=StaySilentArgs)
async def stay_silent(reason: str) -> str:
    """Send the user nothing this turn; ends your turn. Write no text beside it."""
    del reason
    return "Sent nothing."


_ENDINGS: dict[str, type[ReactArgs | StaySilentArgs]] = {
    REACT_TOOL_NAME: ReactArgs,
    STAY_SILENT_TOOL_NAME: StaySilentArgs,
}

#: The tools whose call ends a comms turn, by name.
TURN_ENDING_TOOL_NAMES = frozenset(_ENDINGS)


def turn_ending(message: AIMessage, config: RunnableConfig) -> ReactArgs | StaySilentArgs | None:
    """Return how a model message ends the turn without words; None when it replies or calls work.

    Only a message whose every call is a turn ending, each valid by its schema and a reaction
    the run's surface accepts, ends the turn: an invalid one goes back to the model as a failed call.
    """
    calls: list[ToolCall] = message.tool_calls
    if not calls or any(call["name"] not in _ENDINGS for call in calls):
        return None
    try:
        endings = [_ENDINGS[call["name"]].model_validate(call["args"]) for call in calls]
    except ValidationError:
        return None
    if any(
        isinstance(ending, ReactArgs) and reaction_refusal(ending.emoji, config)
        for ending in endings
    ):
        return None
    return endings[0]
