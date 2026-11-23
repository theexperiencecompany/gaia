"""Close a comms run's lookups once the user interrupts it, so the new message is answered now.

Uninterrupted, comms looks up as much as it needs. When a user message is absorbed into the
running turn (its absorbed note lands in state before a model step), every lookup in that
step or later is refused: the model answers the new message and hands the unfinished lookups
to call_executor, or answers the earlier request with what it has. The lookup step already in
flight when the message arrived finishes. A turn starts after the runner's last turn-context
message; a thread with none is one turn.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, AnyMessage, ToolCall, ToolMessage
from langgraph.types import Command

from app.agents.middleware.runtime_adapter import GaiaAgentState
from app.constants.conversation import ABSORBED_NOTE_SUFFIX, TURN_CONTEXT_ID_SUFFIX
from app.services.hil.utils import raw_tool_call
from shared.py.wide_events import log

LOOKUPS_CLOSED = (
    "The user sent a new message: answer it now and hand the unfinished lookups to call_executor."
)


class InterruptedLookupsMiddleware(AgentMiddleware):
    """Refuse a lookup tool called after a user message joined the running turn."""

    def __init__(self, lookup_tools: frozenset[str]) -> None:
        super().__init__()
        self._lookup_tools = lookup_tools

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[str]]],
    ) -> ToolMessage | Command[str]:
        call = raw_tool_call(request)
        state: GaiaAgentState = request.state
        if call.name not in self._lookup_tools or not _interrupted(state["messages"], call.id):
            return await handler(request)
        log.info("comms_lookup_refused_after_interruption", tool_name=call.name)
        return ToolMessage(
            content=LOOKUPS_CLOSED, tool_call_id=call.id, name=call.name, status="error"
        )


def _interrupted(messages: Sequence[AnyMessage], call_id: str) -> bool:
    """Return whether a user message was absorbed into this turn before the step making call_id."""
    step = next(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, AIMessage) and _makes_call(message, call_id)
        ),
        len(messages),
    )
    # An id-less message holds neither suffix, whatever text stands in for its id.
    ids = [message.id or "" for message in messages]  # pragma: no mutate
    turns = [index for index in range(step) if f"{TURN_CONTEXT_ID_SUFFIX}:" in ids[index]]
    start = turns[-1] + 1 if turns else 0
    return any(message_id.endswith(ABSORBED_NOTE_SUFFIX) for message_id in ids[start:step])


def _makes_call(message: AIMessage, call_id: str) -> bool:
    calls: list[ToolCall] = message.tool_calls
    return any(call["id"] == call_id for call in calls)
