import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_boundary_exactly_4_messages_no_tool_calls(self):
        """Exactly 4 messages but no tool calls — threshold met for count, not for tool calls."""
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "tool calls" in reason

    def test_boundary_exactly_4_messages_with_2_tool_calls(self):
        """Exactly 4 messages with exactly 2 tool calls — both thresholds met."""
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

    def test_boundary_exactly_2_tool_calls(self):
        """Exactly 2 tool calls — meets the minimum threshold."""
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
            HumanMessage(content="q2"),
            AIMessage(content="done"),
        ]
        result, reason = _check_worth_learning(msgs)
        assert result is True
        assert reason == "OK"

    def test_boundary_1_tool_call_fails(self):
        """Exactly 1 tool call — does not meet minimum of 2."""
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "a", "args": {}}],
            ),
            ToolMessage(content="r1", tool_call_id="tc1"),
            AIMessage(content="done"),
        ]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "tool calls" in reason

    def test_zero_messages(self):
        """0 messages — too few, no memory storage."""
        result, reason = _check_worth_learning([])
        assert result is False
        assert "Too few messages" in reason

    def test_messages_with_no_tool_calls(self):
        """Many messages but no tool calls at all — no memory storage."""
        msgs = [HumanMessage(content=f"msg{i}") for i in range(10)]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "tool calls" in reason


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

    def _boundary_state_4_messages_2_tool_calls(self):
        """Exactly 4 messages with exactly 2 tool calls — minimum qualifying state."""
        return {
            "messages": [
                HumanMessage(content="q1"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc1", "name": "tool_a", "args": {"key": "value"}},
                        {"id": "tc2", "name": "tool_b", "args": {"key": "value"}},
                    ],
                ),
                ToolMessage(content="result_a", tool_call_id="tc1"),
                ToolMessage(content="result_b", tool_call_id="tc2"),
            ]
        }

    def _zero_messages_state(self):
        return {"messages": []}

    def _no_tool_calls_state(self):
        return {
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="world"),
                HumanMessage(content="how are you"),
                AIMessage(content="fine thanks"),
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
        """Real asyncio.create_task is used — node returns immediately and task runs."""
        state = self._rich_state()
        config = self._make_config(user_id="u1")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            # Drain any pending tasks so the background coroutine completes
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spawns_background_task_stores_correct_content(self):
        """Real task creation — verify memory storage called with formatted messages."""
        state = self._rich_state()
        config = self._make_config(user_id="user_abc", thread_id="thread_xyz")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_awaited_once()
        call_kwargs = mock_store_memory.call_args.kwargs
        assert call_kwargs["user_id"] == "user_abc"
        assert call_kwargs["conversation_id"] == "thread_xyz"
        # messages must be non-empty formatted list
        assert isinstance(call_kwargs["messages"], list)
        assert len(call_kwargs["messages"]) > 0

    @pytest.mark.asyncio
    async def test_boundary_exactly_4_messages_2_tool_calls_triggers_memory(self):
        """Exactly 4 messages with exactly 2 tool calls — memory storage is triggered."""
        state = self._boundary_state_4_messages_2_tool_calls()
        config = self._make_config(user_id="u_boundary")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_boundary_3_messages_skips_memory(self):
        """Exactly 3 messages — below threshold of 4, memory storage skipped."""
        state = {
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
            ]
        }
        config = self._make_config(user_id="u_boundary")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zero_messages_skips_memory(self):
        """0 messages — memory storage must not be triggered."""
        state = self._zero_messages_state()
        config = self._make_config(user_id="u1")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_messages_with_no_tool_calls_skips_memory(self):
        """Messages present but no tool calls — memory storage must not be triggered."""
        state = self._no_tool_calls_state()
        config = self._make_config(user_id="u1")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_boundary_exactly_2_tool_calls_memory_stored(self):
        """Exactly 2 tool calls across messages — memory storage triggered with correct user."""
        state = {
            "messages": [
                HumanMessage(content="please help"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc1", "name": "fetch_calendar", "args": {"date": "today"}},
                        {"id": "tc2", "name": "create_event", "args": {"title": "Meeting"}},
                    ],
                ),
                ToolMessage(content="calendar data", tool_call_id="tc1"),
                ToolMessage(content="event created", tool_call_id="tc2"),
            ]
        }
        config = self._make_config(user_id="u_two_tools", thread_id="sess1")
        store = MagicMock()

        mock_store_memory = AsyncMock(return_value=True)

        with (
            patch(
                "app.agents.core.nodes.memory_node.memory_service.store_memory_batch",
                mock_store_memory,
            ),
            patch(
                "app.agents.core.nodes.memory_node.get_memory_extraction_prompt",
                return_value=None,
            ),
        ):
            result = await memory_node(state, config, store)
            await asyncio.sleep(0)

        assert result is state
        mock_store_memory.assert_awaited_once()
        call_kwargs = mock_store_memory.call_args.kwargs
        assert call_kwargs["user_id"] == "u_two_tools"
        assert call_kwargs["conversation_id"] == "sess1"
        # Verify tool call content appears in formatted messages
        formatted = call_kwargs["messages"]
        all_content = " ".join(m["content"] for m in formatted)
        assert "fetch_calendar" in all_content
        assert "create_event" in all_content
