"""The executor model is shown, with each tool result, the ref its report cites the call by."""

from __future__ import annotations

from typing import Any, cast

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.call_ref import call_ref
from app.agents.middleware.call_ref import CallRefMiddleware

pytestmark = pytest.mark.unit


class _Request:
    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages

    def override(self, **changes: Any) -> _Request:
        return _Request(changes["messages"])


async def _seen_by_model(messages: list[Any]) -> list[Any]:
    seen: list[Any] = []

    async def handler(request: ModelRequest) -> ModelResponse:
        seen.extend(request.messages)
        return ModelResponse(result=[AIMessage(content="")])

    await CallRefMiddleware().awrap_model_call(cast(ModelRequest, _Request(messages)), handler)
    return seen


async def test_a_tool_result_carries_its_ref_in_the_request() -> None:
    thread = [
        HumanMessage(content="add a todo"),
        ToolMessage(content='{"id": "t1"}', tool_call_id="call_Na1Q8", name="create_todo"),
    ]

    seen = await _seen_by_model(thread)

    assert seen[1].content == f'[call {call_ref("call_Na1Q8")}]\n{{"id": "t1"}}'
    assert seen[0] is thread[0]


async def test_the_thread_keeps_the_tool_result_as_the_tool_returned_it() -> None:
    result = ToolMessage(content="ok", tool_call_id="call_1", name="lookup")

    await _seen_by_model([result])

    assert result.content == "ok"


async def test_a_multimodal_tool_result_gets_the_ref_as_a_leading_text_block() -> None:
    result = ToolMessage(
        content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}],
        tool_call_id="call_1",
        name="screenshot",
    )

    seen = await _seen_by_model([result])

    assert seen[0].content[0] == {"type": "text", "text": f"[call {call_ref('call_1')}]"}
    assert len(seen[0].content) == 2
