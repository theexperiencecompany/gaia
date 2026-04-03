"""Shared test utilities for GAIA API tests."""

from typing import Any

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, BaseMessage


class BindableToolsFakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel with bind_tools() support.

    The real agent (create_agent.py) calls llm.bind_tools(tools) before each
    invocation.  FakeMessagesListChatModel raises NotImplementedError for this.
    This subclass returns itself so the fake pre-programmed responses are
    preserved while production code that calls bind_tools() works correctly.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "BindableToolsFakeModel":  # type: ignore[override]
        return self


def create_fake_llm(responses: list[str]) -> BindableToolsFakeModel:
    return BindableToolsFakeModel(responses=[AIMessage(content=r) for r in responses])


def create_fake_llm_with_tool_calls(
    tool_calls_then_response: list[dict[str, Any] | str],
) -> BindableToolsFakeModel:
    messages: list[BaseMessage] = []
    for item in tool_calls_then_response:
        if isinstance(item, dict):
            messages.append(AIMessage(content="", tool_calls=[item]))
        else:
            messages.append(AIMessage(content=item))
    return BindableToolsFakeModel(responses=messages)


def assert_tool_called(messages: list[BaseMessage], tool_name: str) -> None:
    tool_calls = extract_tool_calls(messages)
    names = [tc["name"] for tc in tool_calls]
    assert tool_name in names, (
        f"Tool '{tool_name}' not found in tool calls. Found: {names}"
    )


def extract_tool_calls(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls.extend(msg.tool_calls)  # type: ignore[arg-type]
    return tool_calls
