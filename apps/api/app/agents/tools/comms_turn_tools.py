"""How comms ends a turn that is not worth a message: a reaction on the user's message, or nothing.

Each is a tool call, so the choice arrives as arguments its schema validated, never inside
reply text. The comms graph ends the turn after one (turn_ending), so no model call follows.
"""

from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from app.constants.comms import REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from shared.py.analytics.catalog.properties import Emoji


class ReactArgs(BaseModel):
    emoji: Emoji = Field(description="Exactly one emoji, nothing else.")


class StaySilentArgs(BaseModel):
    reason: str = Field(description="Why nothing is worth saying. For the logs, never shown.")


@tool(REACT_TOOL_NAME, args_schema=ReactArgs)
async def react(emoji: str) -> str:
    """Answer with a tap-back reaction on the user's message instead of words; ends your turn.

    It shows as a reaction on their message, or as the bare emoji where the platform has
    none. Write no text beside it.
    """
    return f"Reacted {emoji}."


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


def turn_ending(message: AIMessage) -> ReactArgs | StaySilentArgs | None:
    """Return how a model message ends the turn without words; None when it replies or calls work.

    Only a message whose every call is a turn ending, each valid by its schema, ends the
    turn: an invalid one fails as a tool call and goes back to the model, like any other.
    """
    calls: list[ToolCall] = message.tool_calls
    if not calls or any(call["name"] not in _ENDINGS for call in calls):
        return None
    try:
        endings = [_ENDINGS[call["name"]].model_validate(call["args"]) for call in calls]
    except ValidationError:
        return None
    return endings[0]
