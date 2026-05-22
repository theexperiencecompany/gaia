"""Tests for manage_system_prompts_node after the prompt-ordering rework.

The node now keeps exactly ONE static main prompt and ONE dynamic-context
prompt. Stacking every turn's timestamped dynamic-context message would
shatter the implicit-cache prefix, so older ones are dropped. The legacy
``memory_message=True`` marker is still recognised as a dynamic-context flag
for back-compat with older persisted state.
"""

from typing import cast
from unittest.mock import MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.core.nodes.manage_system_prompts import (
    _is_dynamic_context,
    manage_system_prompts_node,
)
from app.override.langgraph_bigtool.utils import State


def _static(content: str) -> SystemMessage:
    return SystemMessage(content=content)


def _dynamic(content: str, marker: str = "dynamic_context") -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={marker: True})


def _config() -> RunnableConfig:
    return cast(RunnableConfig, {"configurable": {"user_id": "u1", "thread_id": "t1"}})


def _store() -> MagicMock:
    return MagicMock()


@pytest.mark.unit
class TestIsDynamicContext:
    def test_dynamic_context_marker(self) -> None:
        msg = SystemMessage(content="ctx", additional_kwargs={"dynamic_context": True})
        assert _is_dynamic_context(msg) is True

    def test_legacy_memory_message_marker_treated_as_dynamic(self) -> None:
        msg = SystemMessage(content="ctx", additional_kwargs={"memory_message": True})
        assert _is_dynamic_context(msg) is True

    def test_marker_in_model_extra(self) -> None:
        class FakeMsg:
            additional_kwargs: dict = {}
            model_extra = {"dynamic_context": True}

        assert _is_dynamic_context(cast(AnyMessage, FakeMsg())) is True

    def test_plain_system_message(self) -> None:
        assert _is_dynamic_context(SystemMessage(content="plain")) is False


@pytest.mark.unit
class TestManageSystemPrompts:
    def test_keeps_latest_static_prompt(self) -> None:
        msgs = [
            _static("old prompt"),
            HumanMessage(content="hi"),
            _static("latest prompt"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "latest prompt"

    def test_keeps_only_latest_dynamic_context(self) -> None:
        msgs = [
            _dynamic("ctx1"),
            _dynamic("ctx2"),
            _dynamic("ctx3"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "ctx3"

    def test_keeps_latest_of_each_kind(self) -> None:
        """Stacked main + dynamic prompts collapse to one of each, latest."""
        msgs = [
            _static("old main"),
            _dynamic("old ctx"),
            HumanMessage(content="q"),
            _dynamic("new ctx"),
            _static("new main"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        contents = [m.content for m in result["messages"] if m.type == "system"]
        assert set(contents) == {"new main", "new ctx"}

    def test_empty_messages(self) -> None:
        state = cast(State, {"messages": []})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result["messages"] == []

    def test_non_system_messages_preserved(self) -> None:
        msgs = [
            _static("prompt"),
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        types = [m.type for m in result["messages"]]
        assert types.count("human") == 1
        assert types.count("ai") == 1
        assert types.count("tool") == 1
        assert types.count("system") == 1

    def test_system_messages_moved_to_front(self) -> None:
        """Kept system messages must appear BEFORE any human/ai message.

        ``langchain-google-genai``'s ``_parse_chat_history`` silently drops any
        ``SystemMessage`` that appears after a non-system message in the list
        — so leaving system messages in their original position would wipe
        out the system prompt and destroy implicit caching. The node
        rewrites the list as ``[static, dynamic, ...non_system...]``.
        """
        msgs = [
            _static("old prompt"),
            _dynamic("ctx1"),
            HumanMessage(content="hello"),
            _dynamic("ctx2"),
            AIMessage(content="reply"),
            _static("latest prompt"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        actual = [m.content for m in result["messages"]]
        # Output: static first, dynamic second, then the non-system messages in
        # their original relative order.
        assert actual == ["latest prompt", "ctx2", "hello", "reply"]

    def test_silent_exception_returns_unmodified_state(self) -> None:
        msgs = [HumanMessage(content="hello"), _static("latest prompt")]
        state = cast(State, {"messages": msgs})
        with patch(
            "app.agents.core.nodes.manage_system_prompts._is_dynamic_context",
            side_effect=RuntimeError("unexpected failure"),
        ):
            result = manage_system_prompts_node(state, _config(), _store())
        assert result is state
        assert result["messages"] is msgs
