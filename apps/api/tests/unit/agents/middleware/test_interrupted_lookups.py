"""InterruptedLookupsMiddleware: a lookup called after a user message joined the turn is refused."""

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware.interrupted_lookups import LOOKUPS_CLOSED, InterruptedLookupsMiddleware
from app.agents.middleware.runtime_adapter import BigtoolToolRuntime
from app.constants.conversation import ABSORBED_NOTE_SUFFIX, TURN_CONTEXT_ID_SUFFIX

LOOKUP = "web_search"
CALL_ID = "call-2"
RAN = "the lookup ran"


def _step(call_id: str = CALL_ID) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": LOOKUP, "args": {}}])


def _absorbed(n: int) -> HumanMessage:
    return HumanMessage(content="actually, hotels", id=f"m{n}{ABSORBED_NOTE_SUFFIX}")


def _turn(n: int) -> HumanMessage:
    return HumanMessage(content="turn context", id=f"run{TURN_CONTEXT_ID_SUFFIX}:{n}")


async def _run(name: str, messages: list[AnyMessage]) -> ToolMessage | Command[str]:
    async def handler(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=RAN, tool_call_id=request.tool_call["id"])

    request = ToolCallRequest(
        tool_call={"id": CALL_ID, "name": name, "args": {}},
        tool=None,
        state={"messages": messages},
        runtime=BigtoolToolRuntime.from_graph_context({"configurable": {}}),
    )
    middleware = InterruptedLookupsMiddleware(lookup_tools=frozenset({LOOKUP}))
    return await middleware.awrap_tool_call(request, handler)


@pytest.mark.parametrize(
    "messages",
    [
        [_absorbed(1), _step()],
        [HumanMessage(content="find flights"), _absorbed(1), _step()],
        [_turn(1), _absorbed(1), _step()],
        [_step("call-1"), _absorbed(1), _step()],
        [_absorbed(1), HumanMessage(content="the step is not in state yet", id="m2")],
    ],
    ids=[
        "opening_the_thread",
        "after_an_id_less_message",
        "right_after_the_turn_began",
        "after_an_earlier_step",
        "before_a_step_not_in_state",
    ],
)
async def test_a_lookup_after_a_message_joined_the_turn_is_refused(
    messages: list[AnyMessage],
) -> None:
    result = await _run(LOOKUP, messages)
    assert isinstance(result, ToolMessage)
    assert (result.content, result.status) == (LOOKUPS_CLOSED, "error")
    assert (result.tool_call_id, result.name) == (CALL_ID, LOOKUP)


@pytest.mark.parametrize(
    "messages",
    [
        [HumanMessage(content="find flights", id="m0"), _step(), _absorbed(1)],
        [_absorbed(1), _turn(1), _step()],
        [_turn(1), _absorbed(1), _turn(2), _step()],
    ],
    ids=["the_step_in_flight_when_it_arrived", "an_earlier_turn", "an_earlier_turn_of_many"],
)
async def test_a_lookup_no_message_interrupted_runs(messages: list[AnyMessage]) -> None:
    result = await _run(LOOKUP, messages)
    assert isinstance(result, ToolMessage)
    assert result.content == RAN


async def test_a_tool_that_is_not_a_lookup_still_runs_after_the_interruption() -> None:
    result = await _run("call_executor", [_absorbed(1), _step()])
    assert isinstance(result, ToolMessage)
    assert result.content == RAN
