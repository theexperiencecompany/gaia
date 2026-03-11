"""
Tests for the follow_up_actions_node.

Mocking strategy:
- KEPT: get_stream_writer (I/O boundary), get_free_llm_chain (external LLM),
        invoke_with_fallback (network call), get_user_integration_capabilities
        and get_tool_registry (external service calls).
- REMOVED: PydanticOutputParser, SUGGEST_FOLLOW_UP_ACTIONS — these are
           internal wiring; tests exercise the real prompt construction
           and parsing pipeline.
"""

import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.core.nodes.follow_up_actions_node import (
    FollowUpActions,
    _pretty_print_messages,
    follow_up_actions_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_llm_response(actions: list[str]) -> str:
    """Return a JSON string that the real PydanticOutputParser can parse."""
    return json.dumps({"actions": actions})


def _make_state(messages=None):
    return {"messages": messages or [], "selected_tool_ids": [], "todos": []}


def _make_config(user_id: str | None = "user-123"):
    cfg: dict = {"configurable": {"thread_id": "thread-abc"}}
    if user_id is not None:
        cfg["configurable"]["user_id"] = user_id
    return cfg


def _make_store():
    return MagicMock()


# ---------------------------------------------------------------------------
# _pretty_print_messages — pure function, no mocking required
# ---------------------------------------------------------------------------

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
        assert _pretty_print_messages([]) == ""

    def test_only_system_messages_returns_empty_by_default(self):
        messages = [SystemMessage(content="only system")]
        assert _pretty_print_messages(messages) == ""


# ---------------------------------------------------------------------------
# follow_up_actions_node
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFollowUpActionsNode:

    # ------------------------------------------------------------------
    # 1. Message slicing: last 4 of 6 messages must reach the LLM
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_message_slicing_takes_last_4(self):
        """
        When the history has 6 messages, only the last 4 must be forwarded
        to the LLM.  If the production slice is changed from [-4:] to [-2:],
        this test fails because messages[2] and messages[3] would be absent
        from the HumanMessage content passed to invoke_with_fallback.
        """
        messages = [
            HumanMessage(content=f"message {i}") for i in range(6)
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        captured_calls: list = []

        async def capture_invoke(chain, msgs, config):
            captured_calls.append(msgs)
            # Return valid JSON so the real parser succeeds.
            return _valid_llm_response(["action1"])

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                side_effect=capture_invoke,
            ),
        ):
            await follow_up_actions_node(state, config, store)

        assert len(captured_calls) == 1, "invoke_with_fallback must be called exactly once"

        # The second element is the message list: [SystemMessage, HumanMessage]
        llm_messages = captured_calls[0]
        human_msg = next(m for m in llm_messages if isinstance(m, HumanMessage))
        human_content = human_msg.content

        # Last 4 messages are indices 2, 3, 4, 5 — all must appear.
        for i in range(2, 6):
            assert f"message {i}" in human_content, (
                f"Expected 'message {i}' in LLM input but it was absent. "
                "Did the slice change from [-4:] to something narrower?"
            )

        # First 2 messages (indices 0 and 1) must NOT appear.
        for i in range(0, 2):
            assert f"message {i}" not in human_content, (
                f"'message {i}' should have been sliced off but was included."
            )

    # ------------------------------------------------------------------
    # 2. Follow-up actions are written to the stream
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_follow_up_actions_written_to_stream(self):
        """
        The node must write the parsed actions to the stream writer,
        not store them in state.
        """
        messages = [
            HumanMessage(content="Can you help me schedule a meeting?"),
            AIMessage(content="Sure, I've scheduled the meeting for tomorrow at 10am."),
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        suggested_actions = ["Schedule another meeting", "Send invites", "Set reminder"]

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": ["calendar", "gmail"]}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(return_value=_valid_llm_response(suggested_actions)),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"main_response_complete": True} in written_values
        assert {"follow_up_actions": suggested_actions} in written_values

        # Actions must NOT be stored in state
        assert "follow_up_actions" not in result

    # ------------------------------------------------------------------
    # 3. Empty / minimal message history
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_messages_handled(self):
        """
        With 0 messages the node must write an empty actions list and
        return state without calling the LLM.
        """
        state = _make_state([])
        config = _make_config()
        store = _make_store()

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        mock_invoke = AsyncMock()

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=mock_invoke,
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": []} in written_values
        mock_invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_message_handled(self):
        """
        With only 1 message (< 2) the node must write an empty actions list
        and return state without calling the LLM.
        """
        state = _make_state([HumanMessage(content="hi")])
        config = _make_config()
        store = _make_store()

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        mock_invoke = AsyncMock()

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=mock_invoke,
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": []} in written_values
        mock_invoke.assert_not_called()

    # ------------------------------------------------------------------
    # 4. LLM failure bubbles / is handled gracefully
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(self):
        """
        When invoke_with_fallback raises, the error must be caught by the
        node's outer handler, an empty actions list must be written to the
        stream, and state must be returned (not re-raised to the caller).
        """
        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
            ),
        ):
            # The node must NOT re-raise — it handles the error internally.
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": []} in written_values

    # ------------------------------------------------------------------
    # 5. Additional behavioural tests (kept from original suite)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stream_closed_on_first_write_returns_state_immediately(self):
        """If the stream is already closed when the completion marker is sent,
        the node must return state immediately without calling the LLM."""
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])
        config = _make_config()
        store = _make_store()

        mock_writer = MagicMock(side_effect=RuntimeError("stream closed"))
        mock_invoke = AsyncMock()

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=mock_invoke,
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        mock_writer.assert_called_once_with({"main_response_complete": True})
        mock_invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_user_id_falls_back_to_tool_registry(self):
        """Without a user_id the node must use get_tool_registry instead of
        get_user_integration_capabilities."""
        messages = [
            HumanMessage(content="What can you do?"),
            AIMessage(content="I can help with many tasks."),
        ]
        state = _make_state(messages)
        config = _make_config(user_id=None)
        store = _make_store()

        suggested_actions = ["Search the web", "Set a reminder"]

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        mock_registry = MagicMock()
        mock_registry.get_tool_names.return_value = ["web_search", "reminder"]

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_tool_registry",
                new=AsyncMock(return_value=mock_registry),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(return_value=_valid_llm_response(suggested_actions)),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        mock_registry.get_tool_names.assert_called_once()
        assert {"follow_up_actions": suggested_actions} in written_values

    @pytest.mark.asyncio
    async def test_parse_failure_writes_empty_actions(self):
        """When the LLM returns unparseable output, the node must write an
        empty actions list and return state without raising."""
        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-123")
        store = _make_store()

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(return_value="this is not valid json {{{{"),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": []} in written_values

    @pytest.mark.asyncio
    async def test_second_write_failure_does_not_raise(self):
        """The writer succeeds for the completion marker but fails for the
        follow_up_actions write; the node must not raise."""
        state = _make_state([HumanMessage(content="hi")])
        config = _make_config()
        store = _make_store()

        call_count = [0]

        def failing_second_write(value):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("stream closed after first write")

        mock_writer = MagicMock(side_effect=failing_second_write)

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_actions_streamed_not_stored_in_state(self):
        """Follow-up actions must be sent via writer only — state must be
        unchanged after the node returns."""
        messages = [
            HumanMessage(content="What meetings do I have?"),
            AIMessage(content="You have a meeting at 3pm."),
        ]
        state = _make_state(messages)
        original_messages = list(state["messages"])
        config = _make_config(user_id="user-456")
        store = _make_store()

        suggested_actions = ["Add another meeting", "Cancel meeting"]

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(return_value=_valid_llm_response(suggested_actions)),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert result["messages"] == original_messages
        assert "follow_up_actions" not in result

    @pytest.mark.asyncio
    async def test_result_with_text_attribute_is_parsed(self):
        """When invoke_with_fallback returns an object with a .text attribute
        (not a bare string), the node must pass result.text to the parser."""
        messages = [
            HumanMessage(content="Summarize my emails"),
            AIMessage(content="You have 3 unread emails."),
        ]
        state = _make_state(messages)
        config = _make_config(user_id="user-789")
        store = _make_store()

        suggested_actions = ["Reply to emails", "Archive all"]

        written_values: list = []
        mock_writer = MagicMock(side_effect=lambda x: written_values.append(x))

        mock_result = MagicMock(spec=[])  # no __class__ override needed
        mock_result.text = _valid_llm_response(suggested_actions)
        # Make isinstance(mock_result, str) return False (default for MagicMock).

        with (
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_free_llm_chain",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                "app.agents.core.nodes.follow_up_actions_node.invoke_with_fallback",
                new=AsyncMock(return_value=mock_result),
            ),
        ):
            result = await follow_up_actions_node(state, config, store)

        assert result is state
        assert {"follow_up_actions": suggested_actions} in written_values
