"""InterruptedLookupsMiddleware: a lookup called after a user message joined the turn is refused."""

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.agents.middleware.interrupted_lookups import LOOKUPS_CLOSED, InterruptedLookupsMiddleware
from app.agents.middleware.runtime_adapter import BigtoolToolRuntime
from app.constants.conversation import ABSORBED_NOTE_SUFFIX

LOOKUP = "web_search"
RAN = "the lookup ran"


def _request(name: str, messages: list[AnyMessage]) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "call-2", "name": name, "args": {}},
        tool=None,
        state={"messages": messages},
        runtime=BigtoolToolRuntime.from_graph_context({"configurable": {}}),
    )


def _interrupted_turn() -> list[AnyMessage]:
    return [
        HumanMessage(content="find flights", id="m1"),
        HumanMessage(content="actually, hotels", id=f"m2{ABSORBED_NOTE_SUFFIX}"),
        AIMessage(content="", tool_calls=[{"id": "call-2", "name": LOOKUP, "args": {}}]),
    ]


async def _run(name: str, messages: list[AnyMessage]) -> ToolMessage | Command[str]:
    async def handler(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=RAN, tool_call_id=request.tool_call["id"])

    middleware = InterruptedLookupsMiddleware(lookup_tools=frozenset({LOOKUP}))
    return await middleware.awrap_tool_call(_request(name, messages), handler)


async def test_a_lookup_after_an_absorbed_message_is_refused() -> None:
    result = await _run(LOOKUP, _interrupted_turn())
    assert isinstance(result, ToolMessage)
    assert (result.content, result.status) == (LOOKUPS_CLOSED, "error")


async def test_a_tool_that_is_not_a_lookup_still_runs_after_the_interruption() -> None:
    result = await _run("call_executor", _interrupted_turn())
    assert isinstance(result, ToolMessage)
    assert result.content == RAN
