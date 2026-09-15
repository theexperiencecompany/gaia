from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from prometheus_client import REGISTRY

from app.agents.core.nodes.filter_messages import filter_messages_node


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
        # Include an AIMessage whose tool call has NO matching ToolMessage so
        # the filtering branch is actually entered. Without this, deleting the
        # entire AI-message filtering path would still let the test pass.
        unanswered_ai = AIMessage(
            content="",
            tool_calls=[{"id": "tc_unanswered", "name": "tool_x", "args": {}}],
        )
        state = self._make_state([system, human, tool, unanswered_ai])

        result = filter_messages_node(state, self._config(), self._store())

        # Non-AI messages must survive intact.
        assert result["messages"][0] == system
        assert result["messages"][1] == human
        assert result["messages"][2] == tool
        # The unanswered AIMessage must still be present but with its tool
        # call stripped — proving the filtering path ran.
        assert len(result["messages"]) == 4
        filtered_ai = result["messages"][3]
        assert isinstance(filtered_ai, AIMessage)
        assert len(filtered_ai.tool_calls) == 0

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

    def test_tool_call_answered_by_later_message_in_sequence(self):
        """Matching is set-based, so the ToolMessage pairs with its own AIMessage regardless of position."""
        ai1 = AIMessage(
            content="",
            tool_calls=[{"id": "A", "name": "tool_a", "args": {}}],
        )
        ai2 = AIMessage(
            content="",
            tool_calls=[{"id": "B", "name": "tool_b", "args": {}}],
        )
        tool_for_a = ToolMessage(content="result_a", tool_call_id="A")
        state = self._make_state([ai1, ai2, tool_for_a])

        result = filter_messages_node(state, self._config(), self._store())

        ai1_filtered = result["messages"][0]
        ai2_filtered = result["messages"][1]

        # AIMessage1: call "A" IS answered — must be kept.
        assert len(ai1_filtered.tool_calls) == 1
        assert ai1_filtered.tool_calls[0]["id"] == "A"

        # AIMessage2: call "B" is NOT answered — must be removed.
        assert len(ai2_filtered.tool_calls) == 0

    def test_malformed_tool_call_degrades_to_unchanged_state_and_logs(self):
        """A tool_call that is not a dict (a corrupted checkpoint shape) is swallowed, logged, and state is returned unchanged."""
        malformed = AIMessage.model_construct(content="", tool_calls=["not-a-dict"])
        messages = [HumanMessage(content="hello"), malformed]
        state = self._make_state(messages)

        with patch("app.agents.core.nodes.filter_messages.log") as mock_log:
            result = filter_messages_node(state, self._config(), self._store())

        assert result is state
        assert result["messages"] is messages

        mock_log.error.assert_called_once()
        logged = mock_log.error.call_args.args[0]
        kwargs = mock_log.error.call_args.kwargs
        assert "filter messages node" in logged
        assert "has no attribute 'get'" in kwargs.get("error", ""), (
            f"The swallowed exception must be named in the log, got: {kwargs}"
        )

    async def test_node_emits_latency_span_labelled_by_agent(self):
        """ensure_config relocates top-level agent_name into configurable; the label survives it."""
        config = {
            "agent_name": "node-test-agent",
            "configurable": {"user_id": "u1", "thread_id": "t1"},
        }
        before = (
            REGISTRY.get_sample_value(
                "graph_node_seconds_count",
                {"node": "filter_messages", "agent": "node-test-agent"},
            )
            or 0.0
        )
        graph = StateGraph(MessagesState)
        graph.add_node("filter", filter_messages_node)
        graph.add_edge(START, "filter")
        graph.add_edge("filter", END)
        await graph.compile().ainvoke(
            self._make_state([HumanMessage(content="hello")]), config=config
        )
        assert (
            REGISTRY.get_sample_value(
                "graph_node_seconds_count",
                {"node": "filter_messages", "agent": "node-test-agent"},
            )
            == before + 1
        )

    def test_node_records_the_exact_elapsed_seconds(self):
        # Two pinned clock reads make the recorded duration deterministic: a
        # start/end subtraction lands exactly 0.5. A sign error (end + start)
        # would record 10.5 here instead, so this pins the direction of the
        # elapsed-time arithmetic, not merely that an observation happened.
        config = {
            "agent_name": "span-test-agent",
            "configurable": {"user_id": "u1", "thread_id": "t1"},
        }
        labels = {"node": "filter_messages", "agent": "span-test-agent"}
        before = REGISTRY.get_sample_value("graph_node_seconds_sum", labels) or 0.0

        with patch(
            "app.agents.core.nodes.filter_messages.time.perf_counter",
            side_effect=[5.0, 5.5],
        ):
            filter_messages_node(
                self._make_state([HumanMessage(content="hello")]), config, self._store()
            )

        assert REGISTRY.get_sample_value("graph_node_seconds_sum", labels) == before + 0.5

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
