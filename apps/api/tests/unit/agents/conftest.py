"""Agent-specific fixtures for unit tests."""

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
import pytest

from app.config.settings import settings

HELPFUL_ASSISTANT_SYSTEM_PROMPT = "You are a helpful assistant."
WEATHER_QUERY = "What is the weather today?"


@pytest.fixture
def stored_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boot as development with local auth: stored credentials outrank env and the dev tools stay on."""
    monkeypatch.setattr(settings, "ENV", "development")
    monkeypatch.setattr(settings, "AUTH_MODE", "local")


@pytest.fixture
def sample_messages() -> list:
    return [
        SystemMessage(content=HELPFUL_ASSISTANT_SYSTEM_PROMPT),
        HumanMessage(content=WEATHER_QUERY),
        AIMessage(content="I can help you check the weather."),
    ]


@pytest.fixture
def messages_with_tool_calls() -> list:
    tool_call_id = "call_weather_123"
    return [
        SystemMessage(content=HELPFUL_ASSISTANT_SYSTEM_PROMPT),
        HumanMessage(content=WEATHER_QUERY),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"location": "San Francisco"},
                    "id": tool_call_id,
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"temperature": 72, "condition": "sunny"}',
            tool_call_id=tool_call_id,
        ),
        AIMessage(content="The weather in San Francisco is 72F and sunny."),
    ]


@pytest.fixture
def messages_with_unanswered_tool_calls() -> list:
    return [
        SystemMessage(content=HELPFUL_ASSISTANT_SYSTEM_PROMPT),
        HumanMessage(content=WEATHER_QUERY),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"location": "San Francisco"},
                    "id": "call_weather_456",
                    "type": "tool_call",
                }
            ],
        ),
    ]


@pytest.fixture
def memory_system_message() -> SystemMessage:
    return SystemMessage(
        content="User prefers metric units.",
        additional_kwargs={"memory_message": True},
    )


@pytest.fixture
def non_memory_system_message() -> SystemMessage:
    return SystemMessage(content=HELPFUL_ASSISTANT_SYSTEM_PROMPT)
