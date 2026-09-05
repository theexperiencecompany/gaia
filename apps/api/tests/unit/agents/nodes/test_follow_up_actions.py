import contextlib
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
import pytest

from app.agents.core.nodes.follow_up_actions_node import (
    _FOLLOW_UP_CONTEXT_MAX_CHARS,
    _PREVIOUS_ACTIONS_MESSAGE_WINDOW,
    SUGGEST_FOLLOW_UP_ACTIONS,
    FollowUpActions,
    _pretty_print_messages,
    follow_up_actions_node,
    generate_follow_up_actions,
)

_NODE = "app.agents.core.nodes.follow_up_actions_node"


def _make_state(messages=None):
    return {"messages": messages or [], "selected_tool_ids": [], "todos": []}


def _make_config(user_id="user-123"):
    return {"configurable": {"user_id": user_id, "thread_id": "thread-abc"}}


def _make_store():
    return MagicMock()


def _expected_dynamic_context(tool_names, previous_actions, context_text):
    """The exact per-turn context block the node hands the LLM."""
    return (
        f"Available tools: {tool_names}\n"
        f"Previously suggested actions (already shown to the user): {previous_actions}\n"
        f"Context: {context_text}"
    )


@dataclass
class _NodeSeams:
    """Patches every seam the node reaches through, with per-test defaults.

    Arrange only: each test still asserts on ``writes``, ``llm_inputs`` and the
    individual mocks, so nothing here softens what a test pins down.

    A dataclass rather than an explicit ``__init__``: this is a bag of
    per-test settings, and the generated constructor keeps the seam list
    extensible without tripping the argument-count ratchet.
    """

    actions: list[str] | None = None
    capability_tools: list[str] | None = None
    registry_tools: list[str] | None = None
    previous_actions: list[str] | None = None
    previous_error: Exception | None = None
    invoke_error: Exception | None = None
    writer: MagicMock | None = None

    def __post_init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        if self.writer is None:
            self.writer = MagicMock(side_effect=self.writes.append)
        self.llm_inputs: list[list[BaseMessage]] = []
        self.capabilities = AsyncMock(return_value={"tool_names": self.capability_tools or []})
        self.registry = MagicMock()
        self.registry.get_tool_names.return_value = self.registry_tools or []
        self.fetch_previous = AsyncMock(
            return_value=self.previous_actions or [], side_effect=self.previous_error
        )
        self._actions = list(self.actions or [])
        self._invoke_error = self.invoke_error
        self._stack = contextlib.ExitStack()

    async def _ainvoke_structured(self, _schema, msgs, *, label=None, config=None):
        self.llm_inputs.append(msgs)
        if self._invoke_error is not None:
            raise self._invoke_error
        return FollowUpActions(actions=self._actions)

    def __enter__(self) -> "_NodeSeams":
        for target, replacement in (
            (f"{_NODE}.get_user_integration_capabilities", self.capabilities),
            (f"{_NODE}.get_tool_registry", AsyncMock(return_value=self.registry)),
            (
                f"{_NODE}.conversation_repository.get_recent_follow_up_actions",
                self.fetch_previous,
            ),
            (f"{_NODE}.ainvoke_structured", self._ainvoke_structured),
        ):
            self._stack.enter_context(patch(target, new=replacement))
        self._stack.enter_context(patch(f"{_NODE}.get_stream_writer", return_value=self.writer))
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stack.close()


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

    def test_context_under_the_cap_is_returned_whole(self):
        messages = [HumanMessage(content="hello"), AIMessage(content="hi there")]
        expected = "".join(m.pretty_repr() for m in messages)
        assert len(expected) < _FOLLOW_UP_CONTEXT_MAX_CHARS

        assert _pretty_print_messages(messages) == expected

    def test_context_over_the_cap_keeps_exactly_the_newest_chars(self):
        # A maxed-out executor result used to flow verbatim into the follow-up
        # request. The cap trims the HEAD, never the tail: follow-ups react to
        # the newest exchange, so dropping the end would suggest actions for a
        # turn that already scrolled past.
        messages = [HumanMessage(content="A" * 4_000), AIMessage(content="B" * 4_000)]
        full = "".join(m.pretty_repr() for m in messages)
        assert len(full) > _FOLLOW_UP_CONTEXT_MAX_CHARS

        result = _pretty_print_messages(messages)

        assert len(result) == _FOLLOW_UP_CONTEXT_MAX_CHARS
        assert result == full[-_FOLLOW_UP_CONTEXT_MAX_CHARS:]


class TestFollowUpActionsNode:
    @pytest.mark.asyncio
    async def test_stream_closed_on_first_write_returns_state_immediately(self):
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])
        mock_writer = MagicMock(side_effect=RuntimeError("stream closed"))

        with _NodeSeams(writer=mock_writer):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        mock_writer.assert_called_once_with({"main_response_complete": True})

    @pytest.mark.asyncio
    async def test_insufficient_messages_writes_empty_actions(self):
        state = _make_state([HumanMessage(content="hi")])

        with _NodeSeams() as seams:
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"main_response_complete": True} in seams.writes
        assert {"follow_up_actions": []} in seams.writes

    @pytest.mark.asyncio
    async def test_empty_messages_writes_empty_actions(self):
        state = _make_state([])

        with _NodeSeams() as seams:
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"follow_up_actions": []} in seams.writes

    @pytest.mark.asyncio
    async def test_happy_path_with_user_id_streams_actions(self):
        state = _make_state(
            [
                HumanMessage(content="Can you help me schedule a meeting?"),
                AIMessage(content="Sure, I've scheduled the meeting for tomorrow at 10am."),
            ]
        )
        suggested_actions = ["Schedule another meeting", "Send invites", "Set reminder"]

        with _NodeSeams(
            actions=suggested_actions,
            capability_tools=["xyztest_invoice_tool", "xyztest_sms_tool"],
        ) as seams:
            result = await follow_up_actions_node(
                state, _make_config(user_id="user-123"), _make_store()
            )

        assert result is state
        assert {"main_response_complete": True} in seams.writes
        assert {"follow_up_actions": suggested_actions} in seams.writes

        # The node assembles [static_system, dynamic_context]. Tool names live in
        # the dynamic-context message so the static system prefix stays
        # byte-identical across users (prompt-cache friendly). There is no third
        # human message: the context used to be sent twice, and the duplicate was
        # ~350 tokens of uncached per-turn weight for no added information.
        assert len(seams.llm_inputs) == 1
        msgs = seams.llm_inputs[0]
        assert len(msgs) == 2
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
        suggested_actions = ["Search the web", "Set a reminder"]

        with _NodeSeams(
            actions=suggested_actions,
            capability_tools=["never_used"],
            registry_tools=["web_search", "reminder"],
        ) as seams:
            result = await follow_up_actions_node(state, config, _make_store())

        assert result is state
        seams.registry.get_tool_names.assert_called_once()
        # With no user there are no per-user capabilities and no thread to dedup
        # against: the whole tool registry stands in, and nothing is looked up.
        seams.capabilities.assert_not_awaited()
        seams.fetch_previous.assert_not_awaited()
        assert {"follow_up_actions": suggested_actions} in seams.writes
        assert seams.llm_inputs[0][1].content == _expected_dynamic_context(
            ["web_search", "reminder"], [], _pretty_print_messages(messages)
        )

    @pytest.mark.asyncio
    async def test_uses_last_4_messages_when_history_exceeds_4(self):
        messages = [HumanMessage(content=f"message {i}") for i in range(6)]

        with _NodeSeams(actions=["action1"]) as seams:
            await follow_up_actions_node(
                _make_state(messages), _make_config(user_id="user-123"), _make_store()
            )

        assert len(seams.llm_inputs) == 1
        # Two messages, not three — the context is carried once, in the
        # dynamic-context system message, never repeated as a human turn.
        llm_msgs = seams.llm_inputs[0]
        assert len(llm_msgs) == 2

        # The context is the pretty-printed slice of recent_messages. With 6
        # input messages and a window of 4, only messages 2-5 must appear.
        context_msg = llm_msgs[1]
        for i in range(2, 6):
            assert f"message {i}" in context_msg.content

        # Messages 0 and 1 must NOT appear — they were cut off.
        assert "message 0" not in context_msg.content
        assert "message 1" not in context_msg.content

    @pytest.mark.asyncio
    async def test_llm_failure_writes_empty_actions_and_returns_state(self):
        """The structured call raises — the except block degrades to empty actions."""
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])

        with _NodeSeams(invoke_error=RuntimeError("LLM timeout")) as seams:
            result = await follow_up_actions_node(
                state, _make_config(user_id="user-123"), _make_store()
            )

        assert result is state
        assert {"follow_up_actions": []} in seams.writes

    @pytest.mark.asyncio
    async def test_second_write_failure_does_not_raise(self):
        """Writer succeeds for completion marker but fails for follow_up_actions."""
        state = _make_state([HumanMessage(content="hi")])
        call_count = [0]

        def failing_second_write(value):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("stream closed after first write")

        with _NodeSeams(writer=MagicMock(side_effect=failing_second_write)):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_actions_streamed_not_stored_in_state(self):
        """Follow-up actions must be sent via writer, never modifying state."""
        state = _make_state(
            [
                HumanMessage(content="What meetings do I have?"),
                AIMessage(content="You have a meeting at 3pm."),
            ]
        )
        original_messages = list(state["messages"])

        with _NodeSeams(actions=["Add another meeting", "Cancel meeting"]):
            result = await follow_up_actions_node(
                state, _make_config(user_id="user-456"), _make_store()
            )

        assert result is state
        # State messages should be unchanged — actions go only through the writer
        assert result["messages"] == original_messages

    @pytest.mark.asyncio
    async def test_thread_id_from_config_drives_the_previous_actions_lookup(self):
        """The dedup lookup is keyed on the run's user and its thread_id."""
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])

        with _NodeSeams(actions=["Reply to Sam"]) as seams:
            await follow_up_actions_node(state, _make_config(user_id="user-123"), _make_store())

        seams.fetch_previous.assert_awaited_once_with(
            "user-123", "thread-abc", window=_PREVIOUS_ACTIONS_MESSAGE_WINDOW
        )
        # Exactly two frames, in this order: the completion marker first (so the
        # UI can close the bubble immediately), the chips second.
        assert seams.writes == [
            {"main_response_complete": True},
            {"follow_up_actions": ["Reply to Sam"]},
        ]

    @pytest.mark.asyncio
    async def test_config_without_configurable_skips_the_lookup_and_still_streams(self):
        """A run carrying no ``configurable`` has no thread to dedup against."""
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])

        with _NodeSeams(
            actions=["Search the web"],
            registry_tools=["web_search"],
            previous_actions=["never shown"],
        ) as seams:
            result = await follow_up_actions_node(state, {}, _make_store())

        assert result is state
        seams.fetch_previous.assert_not_awaited()
        assert seams.writes == [
            {"main_response_complete": True},
            {"follow_up_actions": ["Search the web"]},
        ]

    @pytest.mark.asyncio
    async def test_exactly_four_messages_are_all_sent_as_context(self):
        """At the window boundary nothing is trimmed — four in, four out."""
        messages = [HumanMessage(content=f"message {i}") for i in range(4)]

        with _NodeSeams(actions=["action1"]) as seams:
            await follow_up_actions_node(_make_state(messages), _make_config(), _make_store())

        context = seams.llm_inputs[0][1].content
        for i in range(4):
            assert f"message {i}" in context

    @pytest.mark.asyncio
    async def test_fifth_message_pushes_the_oldest_out_of_the_context(self):
        """One past the boundary — the window keeps the newest four."""
        messages = [HumanMessage(content=f"message {i}") for i in range(5)]

        with _NodeSeams(actions=["action1"]) as seams:
            await follow_up_actions_node(_make_state(messages), _make_config(), _make_store())

        context = seams.llm_inputs[0][1].content
        assert "message 0" not in context
        for i in range(1, 5):
            assert f"message {i}" in context


class TestPreviousActionsContext:
    """Suggestions already shown this conversation ride in the dynamic context."""

    @pytest.mark.asyncio
    async def test_previous_actions_are_fetched_for_the_thread_and_rendered_verbatim(self):
        with _NodeSeams(
            actions=["Draft the reply"],
            capability_tools=["mail_tool"],
            previous_actions=["Book the room", "Invite Sam"],
        ) as seams:
            actions = await generate_follow_up_actions(
                "CONTEXT", "user-123", {"configurable": {}}, "thread-abc"
            )

        assert actions == ["Draft the reply"]
        # The window is a trailing-message count the repository slices on — a
        # wrong or missing value silently changes what counts as "already shown".
        assert _PREVIOUS_ACTIONS_MESSAGE_WINDOW == 10
        seams.fetch_previous.assert_awaited_once_with("user-123", "thread-abc", window=10)

        msgs = seams.llm_inputs[0]
        assert len(msgs) == 2
        assert msgs[0].content == SUGGEST_FOLLOW_UP_ACTIONS
        assert msgs[1].content == _expected_dynamic_context(
            ["mail_tool"], ["Book the room", "Invite Sam"], "CONTEXT"
        )
        assert msgs[1].additional_kwargs == {"dynamic_context": True, "memory_message": True}

    @pytest.mark.parametrize(
        ("user_id", "conversation_id", "expected_tools"),
        [
            ("user-123", None, ["cap_tool"]),
            (None, "thread-abc", ["registry_tool"]),
        ],
    )
    @pytest.mark.asyncio
    async def test_lookup_needs_both_a_user_and_a_conversation(
        self, user_id, conversation_id, expected_tools
    ):
        """Either half missing means no thread to dedup against — skip, don't guess."""
        with _NodeSeams(
            actions=["Draft the reply"],
            capability_tools=["cap_tool"],
            registry_tools=["registry_tool"],
            previous_actions=["never shown"],
        ) as seams:
            await generate_follow_up_actions(
                "CONTEXT", user_id, {"configurable": {}}, conversation_id
            )

        seams.fetch_previous.assert_not_awaited()
        assert seams.llm_inputs[0][1].content == _expected_dynamic_context(
            expected_tools, [], "CONTEXT"
        )

    @pytest.mark.asyncio
    async def test_lookup_failure_degrades_to_an_empty_list_and_still_suggests(self):
        """Dedup context is an enhancement — losing it must not cost the chips."""
        with _NodeSeams(
            actions=["Draft the reply"],
            capability_tools=["mail_tool"],
            previous_error=RuntimeError("mongo down"),
        ) as seams:
            actions = await generate_follow_up_actions(
                "CONTEXT", "user-123", {"configurable": {}}, "thread-abc"
            )

        assert actions == ["Draft the reply"]
        assert seams.llm_inputs[0][1].content == _expected_dynamic_context(
            ["mail_tool"], [], "CONTEXT"
        )
