import pytest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.core.nodes.filter_messages import filter_messages_node


@pytest.mark.unit
class TestFilterMessages:
    def _make_state(self, messages):
        return {"messages": messages}

    def _config(self):
        return {"configurable": {"user_id": "u1", "thread_id": "t1"}}

    def _store(self):
        return MagicMock()

    def test_removes_unanswered_tool_calls(self):
        ai = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc1", "name": "tool_a", "args": {}},
                {"id": "tc2", "name": "tool_b", "args": {}},
            ],
        )
        tool_resp = ToolMessage(content="result", tool_call_id="tc1")
        state = self._make_state([ai, tool_resp])

        result = filter_messages_node(state, self._config(), self._store())

        filtered_ai = result["messages"][0]
        assert len(filtered_ai.tool_calls) == 1
        assert filtered_ai.tool_calls[0]["id"] == "tc1"

    def test_keeps_all_answered_tool_calls(self):
        ai = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc1", "name": "tool_a", "args": {}},
                {"id": "tc2", "name": "tool_b", "args": {}},
            ],
        )
        t1 = ToolMessage(content="r1", tool_call_id="tc1")
        t2 = ToolMessage(content="r2", tool_call_id="tc2")
        state = self._make_state([ai, t1, t2])

        result = filter_messages_node(state, self._config(), self._store())

        filtered_ai = result["messages"][0]
        assert len(filtered_ai.tool_calls) == 2

    def test_preserves_non_ai_messages(self):
        human = HumanMessage(content="hello")
        system = SystemMessage(content="you are helpful")
        tool = ToolMessage(content="result", tool_call_id="tc1")
        state = self._make_state([system, human, tool])

        result = filter_messages_node(state, self._config(), self._store())

        assert len(result["messages"]) == 3
        assert result["messages"][0] == system
        assert result["messages"][1] == human
        assert result["messages"][2] == tool

    def test_empty_messages(self):
        state = self._make_state([])

        result = filter_messages_node(state, self._config(), self._store())

        assert result["messages"] == []

    def test_ai_message_without_tool_calls(self):
        ai = AIMessage(content="just text")
        state = self._make_state([ai])

        result = filter_messages_node(state, self._config(), self._store())

        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "just text"
        assert not result["messages"][0].tool_calls

    def test_mixed_answered_unanswered(self):
        ai1 = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "a", "args": {}}],
        )
        ai2 = AIMessage(
            content="",
            tool_calls=[{"id": "tc2", "name": "b", "args": {}}],
        )
        tool_resp = ToolMessage(content="r", tool_call_id="tc1")
        state = self._make_state([ai1, tool_resp, ai2])

        result = filter_messages_node(state, self._config(), self._store())

        assert len(result["messages"][0].tool_calls) == 1
        assert result["messages"][0].tool_calls[0]["id"] == "tc1"
        assert len(result["messages"][2].tool_calls) == 0

    def test_preserves_ai_content_when_tool_calls_filtered(self):
        ai = AIMessage(
            content="I will use a tool",
            tool_calls=[{"id": "tc1", "name": "a", "args": {}}],
        )
        state = self._make_state([ai])

        result = filter_messages_node(state, self._config(), self._store())

        filtered_ai = result["messages"][0]
        assert filtered_ai.content == "I will use a tool"
        assert len(filtered_ai.tool_calls) == 0

    def test_cross_message_tool_call_deduplication(self):
        """ToolMessages following ai2 must not affect filtering of ai1's tool_calls."""
        ai1 = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "a", "args": {}}])
        tool_for_ai1 = ToolMessage(content="r1", tool_call_id="tc1")
        ai2 = AIMessage(
            content="",
            tool_calls=[
                {"id": "tc2", "name": "b", "args": {}},
                {"id": "tc3", "name": "c", "args": {}},
            ],
        )
        tool_for_tc2 = ToolMessage(content="r2", tool_call_id="tc2")
        state = self._make_state([ai1, tool_for_ai1, ai2, tool_for_tc2])

        result = filter_messages_node(state, self._config(), self._store())

        ai1_filtered = result["messages"][0]
        ai2_filtered = result["messages"][2]
        # tc1 is answered — must be kept
        assert len(ai1_filtered.tool_calls) == 1
        assert ai1_filtered.tool_calls[0]["id"] == "tc1"
        # tc2 answered, tc3 not — only tc2 must be kept
        assert len(ai2_filtered.tool_calls) == 1
        assert ai2_filtered.tool_calls[0]["id"] == "tc2"
