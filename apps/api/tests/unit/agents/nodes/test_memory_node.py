from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.core.nodes.memory_node import (
    _check_worth_learning,
    _extract_text_content,
    _format_messages_for_user_memory,
    memory_node,
)


@pytest.mark.unit
class TestCheckWorthLearning:
    def test_too_few_messages(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "Too few messages" in reason

    def test_too_few_tool_calls(self):
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "tool calls" in reason

    def test_worth_learning(self):
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc1", "name": "a", "args": {}},
                    {"id": "tc2", "name": "b", "args": {}},
                ],
            ),
            ToolMessage(content="r1", tool_call_id="tc1"),
            ToolMessage(content="r2", tool_call_id="tc2"),
        ]
        result, reason = _check_worth_learning(msgs)
        assert result is True
        assert reason == "OK"


@pytest.mark.unit
class TestFormatMessagesForUserMemory:
    def test_formats_human_messages(self):
        msgs = [HumanMessage(content="hello world")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 1
        assert formatted[0] == {"role": "user", "content": "hello world"}

    def test_formats_ai_tool_calls(self):
        msgs = [
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "search", "args": {"q": "test"}}],
            )
        ]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 1
        assert formatted[0]["role"] == "assistant"
        assert "[TOOL CALL: search(" in formatted[0]["content"]

    def test_formats_ai_content(self):
        msgs = [AIMessage(content="here is your answer")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 1
        assert formatted[0] == {"role": "assistant", "content": "here is your answer"}

    def test_truncates_tool_outputs(self):
        long_content = "x" * 600
        msgs = [ToolMessage(content=long_content, tool_call_id="tc1")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 1
        assert "... [truncated]" in formatted[0]["content"]
        assert len(formatted[0]["content"]) < len(long_content) + 50

    def test_skips_system_messages(self):
        msgs = [SystemMessage(content="you are helpful")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 0

    def test_empty_messages(self):
        formatted = _format_messages_for_user_memory([])
        assert formatted == []


@pytest.mark.unit
class TestExtractTextContent:
    def test_string_content(self):
        assert _extract_text_content("hello") == "hello"

    def test_list_content(self):
        blocks = [
            {"type": "text", "text": "part1"},
            {"type": "text", "text": "part2"},
        ]
        result = _extract_text_content(blocks)
        assert "part1" in result
        assert "part2" in result

    def test_other_content(self):
        result = _extract_text_content(42)
        assert result == "42"


@pytest.mark.unit
class TestMemoryNode:
    def _make_config(self, user_id=None, thread_id="t1", subagent_id=None):
        configurable = {"thread_id": thread_id}
        if user_id:
            configurable["user_id"] = user_id
        if subagent_id:
            configurable["subagent_id"] = subagent_id
        return {"configurable": configurable}

    def _trivial_state(self):
        return {
            "messages": [
                HumanMessage(content="hi"),
                AIMessage(content="hello"),
            ]
        }

    def _rich_state(self):
        return {
            "messages": [
                HumanMessage(content="q1"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc1", "name": "a", "args": {}},
                        {"id": "tc2", "name": "b", "args": {}},
                    ],
                ),
                ToolMessage(content="r1", tool_call_id="tc1"),
                ToolMessage(content="r2", tool_call_id="tc2"),
            ]
        }

    @pytest.mark.asyncio
    async def test_skips_trivial_conversation(self):
        state = self._trivial_state()
        config = self._make_config(user_id="u1")
        store = MagicMock()

        result = await memory_node(state, config, store)

        assert result is state

    @pytest.mark.asyncio
    async def test_skips_without_user_id(self):
        state = self._rich_state()
        config = self._make_config()
        store = MagicMock()

        with patch(
            "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
            return_value=None,
        ):
            result = await memory_node(state, config, store)

        assert result is state

    @pytest.mark.asyncio
    async def test_spawns_background_task(self):
        state = self._rich_state()
        config = self._make_config(user_id="u1")
        store = MagicMock()

        mock_task = MagicMock()
        mock_task.get_name.return_value = "user_memory"
        mock_task.add_done_callback = MagicMock()

        with (
            patch(
                "app.agents.core.nodes.memory_node.asyncio.create_task",
                return_value=mock_task,
            ) as mock_create,
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)

        mock_create.assert_called_once()
        mock_task.add_done_callback.assert_called_once()
        assert result is state
