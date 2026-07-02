from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from app.agents.core.nodes.follow_up_actions_node import (
    SUGGEST_FOLLOW_UP_ACTIONS,
    FollowUpActions,
    _pretty_print_messages,
    follow_up_actions_node,
)


def _make_state(messages=None):
    return {"messages": messages or [], "selected_tool_ids": [], "todos": []}


def _make_config(user_id="user-123"):
    return {"configurable": {"user_id": user_id, "thread_id": "thread-abc"}}


def _make_store():
    return MagicMock()


@pytest.mark.unit
class TestPrettyPrintMessages:
    def test_excludes_system_messages_by_default(self):
        messages = [
            SystemMessage(content="system prompt"),
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
        ]
        result = _pretty_print_messages(messages)
        assert "system prompt" not in result
        assert "hello" in result
        assert "hi there" in result

    def test_includes_system_messages_when_flag_false(self):
        messages = [SystemMessage(content="system prompt")]
        result = _pretty_print_messages(messages, ignore_system_messages=False)
        assert "system prompt" in result

    def test_empty_list_returns_empty_string(self):
        result = _pretty_print_messages([])
        assert result == ""

    def test_only_system_messages_returns_empty_by_default(self):
        messages = [SystemMessage(content="only system")]
        result = _pretty_print_messages(messages)
        assert result == ""


@pytest.mark.unit
class TestFollowUpActionsNode:
    @pytest.mark.asyncio
    async def test_stream_closed_on_first_write_returns_state_immediately(self):
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])
        config = _make_config()
        store = _make_store()

        mock_writer = MagicMock(side_effect=RuntimeError("stream closed"))

        with patch(
            "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        mock_writer.assert_called_once_with({"main_response_complete": True})

    @pytest.mark.asyncio
    async def test_insufficient_messages_writes_empty_actions(self):
        state = _make_state([HumanMessage(content="hi")])
        config = _make_config()
        store = _make_store()

        written_values = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        with patch(
            "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"main_response_complete": True} in written_values
        assert {"follow_up_actions": []} in written_values

    @pytest.mark.asyncio
    async def test_empty_messages_writes_empty_actions(self):
        state = _make_state([])
        config = _make_config()
        store = _make_store()

        written_values = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        with patch(
            "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": []} in written_values

    @pytest.mark.asyncio
    async def test_happy_path_with_user_id_streams_actions(self):
        messages = [
            HumanMessage(content="Can you help me schedule a meeting?"),
            AIMessage(content="Sure, I've scheduled the meeting for tomorrow at 10am."),
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        suggested_actions = ["Schedule another meeting", "Send invites", "Set reminder"]
        follow_up = FollowUpActions(actions=suggested_actions)

        written_values = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        captured_llm_inputs = []

        async def capture_invoke(_schema, msgs, *, label=None, config=None):
            captured_llm_inputs.append(msgs)
            return follow_up

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(
                    return_value={"tool_names": ["xyztest_invoice_tool", "xyztest_sms_tool"]}
                ),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.ainvoke_structured",
                new=capture_invoke,
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"main_response_complete": True} in written_values
        assert {"follow_up_actions": suggested_actions} in written_values

        # The node assembles [static_system, dynamic_context, human]. Tool names
        # live in the dynamic-context message so the static system prefix stays
        # byte-identical across users (prompt-cache friendly).
        assert len(captured_llm_inputs) == 1
        msgs = captured_llm_inputs[0]
        assert len(msgs) == 3
        dynamic_context = msgs[1].content
        assert "xyztest_invoice_tool" in dynamic_context
        assert "xyztest_sms_tool" in dynamic_context
        assert msgs[0].content == SUGGEST_FOLLOW_UP_ACTIONS

    @pytest.mark.asyncio
    async def test_happy_path_no_user_id_falls_back_to_tool_registry(self):
        messages = [
            HumanMessage(content="What can you do?"),
            AIMessage(content="I can help with many tasks."),
        ]
        state = _make_state(messages)
        config = _make_config(user_id=None)
        config["configurable"].pop("user_id")
        store = _make_store()

        suggested_actions = ["Search the web", "Set a reminder"]
        follow_up = FollowUpActions(actions=suggested_actions)

        written_values = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        mock_registry = MagicMock()
        mock_registry.get_tool_names.return_value = ["web_search", "reminder"]

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.ainvoke_structured",
                new=AsyncMock(return_value=follow_up),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        mock_registry.get_tool_names.assert_called_once()
        assert {"follow_up_actions": suggested_actions} in written_values

    @pytest.mark.asyncio
    async def test_uses_last_4_messages_when_history_exceeds_4(self):
        messages = [HumanMessage(content=f"message {i}") for i in range(6)]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        captured_invocations = []
        follow_up = FollowUpActions(actions=["action1"])

        async def capture_invoke(_schema, msgs, *, label=None, config=None):
            captured_invocations.append(msgs)
            return follow_up

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.ainvoke_structured",
                new=capture_invoke,
            ),
        ):
            await follow_up_actions_node(state, config, store)

        assert len(captured_invocations) == 1
        # [static_system, dynamic_context, human_message]
        llm_msgs = captured_invocations[0]
        assert len(llm_msgs) == 3

        # The HumanMessage content is the pretty-printed slice of recent_messages.
        # With 6 input messages and a window of 4, only messages 2-5 must appear.
        human_msg = llm_msgs[2]
        for i in range(2, 6):
            assert f"message {i}" in human_msg.content

        # Messages 0 and 1 must NOT appear — they were cut off.
        assert "message 0" not in human_msg.content
        assert "message 1" not in human_msg.content

    @pytest.mark.asyncio
    async def test_llm_failure_writes_empty_actions_and_returns_state(self):
        """The structured call raises — the except block degrades to empty actions."""
        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        written_values = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.ainvoke_structured",
                new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": []} in written_values

    @pytest.mark.asyncio
    async def test_second_write_failure_does_not_raise(self):
        """Writer succeeds for completion marker but fails for follow_up_actions."""
        state = _make_state([HumanMessage(content="hi")])
        config = _make_config()
        store = _make_store()

        call_count = [0]

        def failing_second_write(value):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("stream closed after first write")

        mock_writer = MagicMock(side_effect=failing_second_write)

        with patch(
            "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_actions_streamed_not_stored_in_state(self):
        """Follow-up actions must be sent via writer, never modifying state."""
        messages = [
            HumanMessage(content="What meetings do I have?"),
            AIMessage(content="You have a meeting at 3pm."),
        ]
        state = _make_state(messages)
        original_messages = list(state["messages"])
        config = _make_config(user_id="user-456")
        store = _make_store()

        follow_up = FollowUpActions(actions=["Add another meeting", "Cancel meeting"])

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.ainvoke_structured",
                new=AsyncMock(return_value=follow_up),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        # State messages should be unchanged — actions go only through the writer
        assert result["messages"] == original_messages
