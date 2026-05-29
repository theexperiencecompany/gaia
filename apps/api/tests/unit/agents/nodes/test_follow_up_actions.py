"""Behaviour spec for app/agents/core/nodes/follow_up_actions_node.py.

UNIT: follow_up_actions_node(state, config, store) -> State
EXPECTED: End-of-graph hook. Streams {"main_response_complete": True}, then either
          {"follow_up_actions": []} (no/insufficient history, parse failure, or any
          error) or {"follow_up_actions": [...]} (LLM-produced suggestions). Always
          returns the *same* state object unchanged (actions are streamed, never stored).
MECHANISM:
  writer({"main_response_complete": True})  # if this raises, bail early, return state
  if not messages or len(messages) < 2 -> writer({"follow_up_actions": []}); return
  resolve tool_names: user_id -> get_user_integration_capabilities; else tool_registry
  recent_messages = messages[-4:] if len(messages) > 4 else messages
  dynamic_context = format_instructions + "\n\n" + "Available tools: {names}\n" + "Context: {recent}"
  invoke_with_fallback(chain, [System(prompt), System(dynamic, kwargs={dynamic_context, memory_message}), Human(pretty)], config={**config, silent: True})
  actions = parser.parse(result | result.text); on failure -> writer({"follow_up_actions": []})
  writer({"follow_up_actions": actions or []})
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - completion marker streamed first, with exact key "main_response_complete": True
  - first-write failure short-circuits: no LLM call, returns state         [L50/L51 path]
  - insufficient history (0 or 1 msg) streams [] and never calls the LLM    [L62 Or->And boundary]
  - window boundary: exactly 5 messages keeps only the last 4               [L81 4->5]
  - dynamic_context carries format instructions + "Available tools:" label + tool names [L87/L88]
  - second SystemMessage additional_kwargs == {dynamic_context: True, memory_message: True} [L107/L108]
  - invoke config has silent=True and preserves original config keys        [L113]
  - user_id present -> capabilities path; absent -> tool_registry fallback  [L71 branch]
  - parse failure streams [] (inner except), LLM was reached               [L121-128]
  - LLM raise streams [] (outer except), parser never reached              [L137-143]
  - result with .text attribute -> parser receives result.text             [L122 isinstance branch]
  - actions are streamed, state messages untouched
EQUIVALENT MUTANTS (allowed survivors, justified):
  - All log.debug / log.error message strings (L53, L66, L127, L134, L138, L142):
    log-only side effects, no observable behaviour in a unit boundary.
  - All log.set field keys/values (L94 tool_count, L95 recent_message_count,
    L96 user_id, L120 model): structured-log fields, not returned/streamed.
  - model_name extraction (L116 getattr index 0->1, Or->And, "model_name"/"model"
    attr names): feeds only log.set(agent={"model": ...}); log-only.
  - L38 docstring str->'': documentation only.

UNIT: _pretty_print_messages(messages, ignore_system_messages=True) -> str
EXPECTED: Concatenate pretty_repr() of each message; skip SystemMessages when the
          flag is set (default). Empty in -> empty string out.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from app.agents.core.nodes.follow_up_actions_node import (
    FollowUpActions,
    _pretty_print_messages,
    follow_up_actions_node,
)

NODE = "app.agents.core.nodes.follow_up_actions_node"


def _make_state(messages=None):
    return {"messages": messages or [], "selected_tool_ids": [], "todos": []}


def _make_config(user_id="user-123"):
    return {"configurable": {"user_id": user_id, "thread_id": "thread-abc"}}


def _make_store():
    return MagicMock()


def _recording_writer():
    """A writer that records every streamed frame for assertion."""
    written = []
    return written, MagicMock(side_effect=lambda frame: written.append(frame))


def _stub_parser(actions):
    """PydanticOutputParser stub returning FollowUpActions(actions) on parse."""
    parser = MagicMock()
    parser.get_format_instructions.return_value = "FORMAT_INSTRUCTIONS_SENTINEL"
    parser.parse.return_value = FollowUpActions(actions=actions)
    return parser


@pytest.mark.unit
class TestPrettyPrintMessages:
    def test_excludes_system_messages_by_default(self):
        result = _pretty_print_messages(
            [
                SystemMessage(content="system prompt"),
                HumanMessage(content="hello user"),
                AIMessage(content="hi there"),
            ]
        )
        assert "system prompt" not in result
        assert "hello user" in result
        assert "hi there" in result

    def test_includes_system_messages_when_flag_false(self):
        result = _pretty_print_messages(
            [SystemMessage(content="system prompt")], ignore_system_messages=False
        )
        assert "system prompt" in result

    def test_empty_list_returns_empty_string(self):
        assert _pretty_print_messages([]) == ""

    def test_only_system_messages_returns_empty_by_default(self):
        assert _pretty_print_messages([SystemMessage(content="only system")]) == ""


@pytest.mark.unit
class TestFollowUpActionsNode:
    @pytest.mark.asyncio
    async def test_first_write_failure_short_circuits_before_llm(self):
        """If the completion-marker write raises (stream closed), bail immediately:
        return the same state and never touch the LLM chain."""
        state = _make_state([HumanMessage(content="hi"), AIMessage(content="hello")])
        writer = MagicMock(side_effect=RuntimeError("stream closed"))
        chain_factory = MagicMock()
        invoke = AsyncMock()

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", chain_factory),
            patch(f"{NODE}.invoke_with_fallback", invoke),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        writer.assert_called_once_with({"main_response_complete": True})
        # Short-circuit happens before the LLM chain is even constructed.
        chain_factory.assert_not_called()
        invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_completion_marker_streamed_before_actions(self):
        """The completion marker is the FIRST frame, emitted before follow_up_actions."""
        messages = [HumanMessage(content="schedule a meeting"), AIMessage(content="done")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        parser = _stub_parser(["Reschedule", "Invite team"])

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=AsyncMock(return_value="raw")),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert written[0] == {"main_response_complete": True}
        assert {"follow_up_actions": ["Reschedule", "Invite team"]} in written
        # Completion marker strictly precedes the actions frame.
        marker_idx = written.index({"main_response_complete": True})
        actions_idx = written.index({"follow_up_actions": ["Reschedule", "Invite team"]})
        assert marker_idx < actions_idx

    @pytest.mark.asyncio
    async def test_empty_history_streams_empty_and_skips_llm(self):
        """Zero messages -> stream [] and never invoke the LLM."""
        state = _make_state([])
        written, writer = _recording_writer()
        invoke = AsyncMock()

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(f"{NODE}.invoke_with_fallback", invoke),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"follow_up_actions": []} in written
        invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_message_streams_empty_and_skips_llm(self):
        """Exactly one message is insufficient history. This pins the `not messages or
        len < 2` guard: under an `and` mutation a single message would slip through to
        the LLM, so we assert the LLM is never reached and only [] is streamed."""
        state = _make_state([HumanMessage(content="only one turn")])
        written, writer = _recording_writer()
        invoke = AsyncMock(return_value="raw")
        capabilities = AsyncMock(return_value={"tool_names": ["x"]})

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(f"{NODE}.get_user_integration_capabilities", new=capabilities),
            patch(f"{NODE}.invoke_with_fallback", invoke),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"follow_up_actions": []} in written
        # The guard short-circuits before any tool/LLM work.
        invoke.assert_not_called()
        capabilities.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_two_messages_proceeds_to_llm(self):
        """Exactly two messages is the minimum that proceeds (boundary above the guard).
        Pins the `< 2` threshold against an off-by-one: two messages must NOT be skipped."""
        messages = [HumanMessage(content="question"), AIMessage(content="answer")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        invoke = AsyncMock(return_value="raw")
        parser = _stub_parser(["Follow up"])

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", invoke),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        invoke.assert_awaited_once()
        assert {"follow_up_actions": ["Follow up"]} in written

    @pytest.mark.asyncio
    async def test_user_id_resolves_tool_names_from_capabilities(self):
        """With a user_id, tool names come from get_user_integration_capabilities and
        are embedded in the dynamic-context message; the tool registry is NOT used."""
        messages = [HumanMessage(content="help me"), AIMessage(content="sure")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        parser = _stub_parser(["Schedule another"])
        captured = []

        async def capture(_chain, msgs, config):
            captured.append((msgs, config))
            return "raw"

        capabilities = AsyncMock(return_value={"tool_names": ["calendar", "gmail"]})
        registry = AsyncMock()

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(f"{NODE}.get_user_integration_capabilities", new=capabilities),
            patch(f"{NODE}.get_tool_registry", new=registry),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(user_id="u-1"), _make_store())

        capabilities.assert_awaited_once_with("u-1")
        registry.assert_not_awaited()

        msgs, _config = captured[0]
        dynamic_context = msgs[1].content
        assert "calendar" in dynamic_context
        assert "gmail" in dynamic_context
        # Per-user tools must NOT leak into the static system prefix.
        assert "calendar" not in msgs[0].content
        assert "gmail" not in msgs[0].content

    @pytest.mark.asyncio
    async def test_no_user_id_falls_back_to_tool_registry(self):
        """Without a user_id, tool names come from the global tool registry."""
        messages = [HumanMessage(content="what can you do"), AIMessage(content="lots")]
        state = _make_state(messages)
        config = {"configurable": {"thread_id": "t-1"}}
        written, writer = _recording_writer()
        parser = _stub_parser(["Search the web"])
        captured = []

        async def capture(_chain, msgs, config):
            captured.append(msgs)
            return "raw"

        registry = MagicMock()
        registry.get_tool_names.return_value = ["web_search", "reminder"]
        capabilities = AsyncMock()

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(f"{NODE}.get_user_integration_capabilities", new=capabilities),
            patch(f"{NODE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, config, _make_store())

        registry.get_tool_names.assert_called_once()
        capabilities.assert_not_awaited()
        dynamic_context = captured[0][1].content
        assert "web_search" in dynamic_context
        assert "reminder" in dynamic_context

    @pytest.mark.asyncio
    async def test_window_of_exactly_five_keeps_only_last_four(self):
        """Window boundary: with 5 messages, `len > 4` is True so the slice is messages[-4:].
        Message 0 is dropped; messages 1-4 are kept. This pins the `> 4` against `> 5`
        (under which all 5 would be kept) and against `>= 4`."""
        messages = [HumanMessage(content=f"msg-{i}") for i in range(5)]
        state = _make_state(messages)
        parser = _stub_parser(["a"])
        captured = []

        async def capture(_chain, msgs, config):
            captured.append(msgs)
            return "raw"

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        human_content = captured[0][2].content
        assert "msg-0" not in human_content
        for i in range(1, 5):
            assert f"msg-{i}" in human_content
        # The dynamic-context "Context:" slice reflects the same 4-message window.
        dynamic_context = captured[0][1].content
        assert "msg-0" not in dynamic_context

    @pytest.mark.asyncio
    async def test_window_of_exactly_four_keeps_all_four(self):
        """With exactly 4 messages, `len > 4` is False so all 4 are kept (no slice).
        Complements the 5-message test to pin `> 4` rather than `>= 4`."""
        messages = [HumanMessage(content=f"msg-{i}") for i in range(4)]
        state = _make_state(messages)
        parser = _stub_parser(["a"])
        captured = []

        async def capture(_chain, msgs, config):
            captured.append(msgs)
            return "raw"

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        human_content = captured[0][2].content
        for i in range(4):
            assert f"msg-{i}" in human_content

    @pytest.mark.asyncio
    async def test_dynamic_context_composition_is_exact(self):
        """The dynamic-context message is format_instructions + blank line +
        'Available tools: {names}' + 'Context: {recent}'. Pins the literal joiner
        '\\n\\n' and the 'Available tools:' label, and confirms format instructions
        are included verbatim."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        parser = _stub_parser(["a"])
        captured = []

        async def capture(_chain, msgs, config):
            captured.append(msgs)
            return "raw"

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": ["calendar"]}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        dynamic_context = captured[0][1].content
        expected = (
            f"FORMAT_INSTRUCTIONS_SENTINEL\n\nAvailable tools: ['calendar']\nContext: {messages}"
        )
        assert dynamic_context == expected

    @pytest.mark.asyncio
    async def test_llm_message_structure_and_kwargs(self):
        """The three messages handed to the LLM are [static system prompt, dynamic
        context system message, human pretty-print]. The dynamic message carries the
        exact additional_kwargs contract the downstream memory/caching layer relies on."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        parser = _stub_parser(["a"])
        captured = []

        async def capture(_chain, msgs, config):
            captured.append(msgs)
            return "raw"

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        msgs = captured[0]
        assert len(msgs) == 3
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], SystemMessage)
        assert isinstance(msgs[2], HumanMessage)
        # The exact metadata contract — every key and value must match.
        assert msgs[1].additional_kwargs == {
            "dynamic_context": True,
            "memory_message": True,
        }

    @pytest.mark.asyncio
    async def test_invoke_config_is_silent_and_preserves_config(self):
        """The LLM is invoked silently (silent=True) while the original config keys
        are preserved. Pins both the literal key 'silent' and its True value."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        config = _make_config(user_id="u-9")
        parser = _stub_parser(["a"])
        captured = []

        async def capture(_chain, _msgs, config):
            captured.append(config)
            return "raw"

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=capture),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, config, _make_store())

        invoke_config = captured[0]
        assert invoke_config["silent"] is True
        # Original config must be carried through, not replaced.
        assert invoke_config["configurable"] == config["configurable"]

    @pytest.mark.asyncio
    async def test_parsed_actions_are_streamed_verbatim(self):
        """The exact list parsed from the LLM output is what gets streamed."""
        messages = [HumanMessage(content="emails?"), AIMessage(content="3 unread")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        parser = _stub_parser(["Reply to all", "Archive", "Mark read"])

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=AsyncMock(return_value="raw")),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        assert {"follow_up_actions": ["Reply to all", "Archive", "Mark read"]} in written

    @pytest.mark.asyncio
    async def test_empty_parsed_actions_stream_empty_list(self):
        """When the parser yields an empty actions list, an empty list is streamed
        (the `actions.actions if actions.actions else []` fallthrough)."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        parser = _stub_parser([])

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=AsyncMock(return_value="raw")),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        assert {"follow_up_actions": []} in written

    @pytest.mark.asyncio
    async def test_string_result_parsed_directly(self):
        """When the LLM returns a plain string, the parser receives that string
        (the isinstance(result, str) branch)."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        parser = _stub_parser(["a"])
        parsed_inputs = []
        parser.parse.side_effect = lambda value: (
            parsed_inputs.append(value) or FollowUpActions(actions=["a"])
        )

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=AsyncMock(return_value="STRING_RESULT")),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        assert parsed_inputs == ["STRING_RESULT"]

    @pytest.mark.asyncio
    async def test_non_string_result_parses_text_attribute(self):
        """When the LLM returns a non-string object, parser receives result.text
        (the else branch of the isinstance check)."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        parser = _stub_parser(["a"])
        parsed_inputs = []
        parser.parse.side_effect = lambda value: (
            parsed_inputs.append(value) or FollowUpActions(actions=["a"])
        )

        result_obj = MagicMock()
        result_obj.__class__ = object  # ensure not a str
        result_obj.text = "TEXT_ATTRIBUTE_PAYLOAD"

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=AsyncMock(return_value=result_obj)),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            await follow_up_actions_node(state, _make_config(), _make_store())

        assert parsed_inputs == ["TEXT_ATTRIBUTE_PAYLOAD"]

    @pytest.mark.asyncio
    async def test_parse_failure_streams_empty_after_reaching_llm(self):
        """LLM succeeds but its output cannot be parsed -> inner except streams [].
        The parser WAS invoked (we passed the LLM step), distinguishing this from the
        outer error path."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        parser = _stub_parser(["unused"])
        parser.parse.side_effect = ValueError("malformed JSON")
        invoke = AsyncMock(return_value="garbage")

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", invoke),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"follow_up_actions": []} in written
        invoke.assert_awaited_once()
        parser.parse.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_failure_streams_empty_without_parsing(self):
        """The LLM call itself raises -> outer except streams []. The parser is never
        reached, distinguishing this from the parse-failure path."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        parser = _stub_parser(["unused"])

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(
                f"{NODE}.invoke_with_fallback",
                new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
            ),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"follow_up_actions": []} in written
        parser.parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_capabilities_failure_streams_empty_via_outer_except(self):
        """A failure resolving tool capabilities is swallowed by the outer except,
        which still streams [] and returns the state (no crash propagates out)."""
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        state = _make_state(messages)
        written, writer = _recording_writer()
        invoke = AsyncMock()

        with (
            patch(f"{NODE}.get_stream_writer", return_value=writer),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(side_effect=RuntimeError("integration store down")),
            ),
            patch(f"{NODE}.invoke_with_fallback", invoke),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert {"follow_up_actions": []} in written
        invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_actions_streamed_not_stored_in_state(self):
        """Follow-up actions are streamed via the writer only; the returned state and
        its messages are the unmodified input."""
        messages = [HumanMessage(content="meetings?"), AIMessage(content="one at 3pm")]
        state = _make_state(messages)
        original_messages = list(state["messages"])
        parser = _stub_parser(["Add meeting", "Cancel"])

        with (
            patch(f"{NODE}.get_stream_writer", return_value=MagicMock()),
            patch(f"{NODE}.get_free_llm_chain", return_value=MagicMock()),
            patch(
                f"{NODE}.get_user_integration_capabilities",
                new=AsyncMock(return_value={"tool_names": []}),
            ),
            patch(f"{NODE}.invoke_with_fallback", new=AsyncMock(return_value="raw")),
            patch(f"{NODE}.PydanticOutputParser", return_value=parser),
        ):
            result = await follow_up_actions_node(state, _make_config(), _make_store())

        assert result is state
        assert result["messages"] == original_messages
        assert "follow_up_actions" not in result
