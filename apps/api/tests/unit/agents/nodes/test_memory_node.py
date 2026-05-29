"""Behavior spec for the memory-learning end-graph hook.

UNIT: app/agents/core/nodes/memory_node.py
  Public surface exercised: memory_node (the node), plus the pure helpers it
  composes — _check_worth_learning, _format_messages_for_user_memory,
  _extract_text_content — and the fire-and-forget worker
  _store_user_memory_background.

EXPECTED:
  - memory_node is a non-blocking end-graph hook. It returns the SAME state
    object unchanged, and ONLY spawns a background mem0 write when the
    conversation is "worth learning" AND a user_id is present in config.
  - _check_worth_learning gates on conversation richness: >= 4 messages AND
    >= 2 AIMessage tool calls. Otherwise skip with a reason.
  - _format_messages_for_user_memory converts LangChain messages to mem0
    role/content dicts: human -> user, AI-with-tool-calls -> one assistant
    line per call (preserving INPUTS), AI-text -> assistant, tool output ->
    assistant wrapped + truncated past MAX_TOOL_OUTPUT_SIZE. System messages
    and empty content are dropped.
  - _extract_text_content flattens str | multimodal-list | other into a str.
  - _store_user_memory_background persists to the user_id namespace via
    memory_service.store_memory_batch with async_mode and the (optional)
    integration prompt, and never lets a storage failure escape.

MECHANISM:
  memory_node: read messages/state; pull user_id/subagent_id/thread_id from
  config["configurable"]; resolve extraction_prompt via
  get_memory_extraction_prompt(subagent_id) only when subagent_id set;
  gate via _check_worth_learning; if user_id -> asyncio.create_task(
  _store_user_memory_background(messages, user_id, session_id=thread_id,
  extraction_prompt, subagent_id)), retain the task in _background_tasks and
  attach the done-callback; return state.

MUST-CATCH (each maps to >= 1 test + >= 1 killed mutant):
  - len(messages) < 4 is skipped; exactly 4 is the first eligible length.   [gate boundary]
  - tool_calls < 2 is skipped; the reason carries the real count; only
    AIMessage tool_calls count (ToolMessage/Human are ignored).             [gate boundary + filter]
  - "worth learning" + user_id spawns EXACTLY one background task, wired to
    _store_user_memory_background with the real messages / user_id /
    session_id=thread_id, and the task is retained + given the callback.    [spawn contract]
  - no user_id -> NO task spawned, state returned unchanged.                [early-skip branch]
  - trivial conversation -> NO task spawned even with a user_id.            [gate branch]
  - subagent_id drives the extraction prompt lookup (None when absent).     [prompt wiring]
  - human message uses role "user" and its text; empty human content dropped.[format branch]
  - AI tool-call line is "[TOOL CALL: name(args)]" with the real name/args;
    when an AIMessage has BOTH content and tool_calls, tool_calls win.      [format branch + if/elif]
  - AI text line uses role "assistant" with the content.                    [format branch]
  - tool output <= MAX kept verbatim; > MAX truncated to MAX + marker.      [truncation boundary]
  - system messages produce nothing.                                        [format filter]
  - _extract_text_content: str passthrough, list joins only text blocks,
    other -> str().                                                         [3-way branch]
  - empty formatted payload -> store_memory_batch is NOT called.            [worker early-return]
  - source_integration metadata present iff subagent_id set.               [worker metadata branch]
  - store_memory_batch is awaited with user_id + custom_instructions +
    async_mode=True.                                                        [persistence contract]
  - store_memory_batch raising is swallowed (worker never re-raises).       [error path]

EQUIVALENT MUTANTS (allowed survivors, justified):
  All 9 surviving mutants are const_str -> '' applied to a DOCSTRING (the
  first/last line of each function's triple-quoted docstring — lines 33, 38,
  43, 48, 53, 77, 115, 141, 182). Emptying a docstring changes only __doc__,
  never runtime behaviour, so no behavioural test can kill them. Mutation:
  81/90 killed (0.90); the remaining 9 are exactly these docstrings.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.core.nodes.memory_node import (
    MAX_TOOL_OUTPUT_SIZE,
    _background_tasks,
    _check_worth_learning,
    _extract_text_content,
    _format_messages_for_user_memory,
    _store_user_memory_background,
    _task_done_callback,
    memory_node,
)

MODULE = "app.agents.core.nodes.memory_node"


def _ai_with_tools(n: int) -> AIMessage:
    """An AIMessage carrying n tool calls (the only thing the gate counts)."""
    return AIMessage(
        content="",
        tool_calls=[{"id": f"tc{i}", "name": f"tool{i}", "args": {}} for i in range(n)],
    )


def _rich_messages() -> list:
    """4 messages with 2 tool calls — the minimum that is 'worth learning'."""
    return [
        HumanMessage(content="q1"),
        _ai_with_tools(2),
        ToolMessage(content="r1", tool_call_id="tc0"),
        ToolMessage(content="r2", tool_call_id="tc1"),
    ]


@pytest.mark.unit
class TestCheckWorthLearning:
    def test_fewer_than_four_messages_skipped(self):
        # 3 messages, even with enough tool calls, is below the length gate.
        msgs = [
            HumanMessage(content="q"),
            _ai_with_tools(3),
            ToolMessage(content="r", tool_call_id="tc0"),
        ]
        ok, reason = _check_worth_learning(msgs)
        assert ok is False
        assert reason == "Too few messages"

    def test_exactly_four_messages_passes_length_gate(self):
        # Boundary: 4 messages is the first eligible length (kills < -> <=).
        ok, reason = _check_worth_learning(_rich_messages())
        assert ok is True
        assert reason == "OK"

    def test_one_tool_call_is_too_few(self):
        # Boundary: exactly 1 tool call is rejected (threshold is < 2), and the
        # reason must report the real count, not a constant.
        msgs = [
            HumanMessage(content="q1"),
            _ai_with_tools(1),
            ToolMessage(content="r1", tool_call_id="tc0"),
            AIMessage(content="done"),
        ]
        ok, reason = _check_worth_learning(msgs)
        assert ok is False
        assert reason == "Only 1 tool calls - too simple"

    def test_tool_calls_counted_only_on_ai_messages(self):
        # ToolMessages and HumanMessages must not contribute to the tool-call
        # count: 4 messages but the single AIMessage has no tool calls.
        msgs = [
            HumanMessage(content="q1"),
            ToolMessage(content="r1", tool_call_id="x"),
            ToolMessage(content="r2", tool_call_id="y"),
            AIMessage(content="just text"),
        ]
        ok, reason = _check_worth_learning(msgs)
        assert ok is False
        assert reason == "Only 0 tool calls - too simple"

    def test_two_tool_calls_across_messages_passes(self):
        # The count sums across AIMessages; 1 + 1 reaches the >= 2 gate.
        msgs = [
            HumanMessage(content="q1"),
            _ai_with_tools(1),
            _ai_with_tools(1),
            ToolMessage(content="r1", tool_call_id="tc0"),
        ]
        ok, reason = _check_worth_learning(msgs)
        assert ok is True
        assert reason == "OK"


@pytest.mark.unit
class TestFormatMessagesForUserMemory:
    def test_human_message_becomes_user_role(self):
        formatted = _format_messages_for_user_memory([HumanMessage(content="hello world")])
        assert formatted == [{"role": "user", "content": "hello world"}]

    def test_empty_human_content_dropped(self):
        # `if content:` guards human messages — empty text adds nothing.
        formatted = _format_messages_for_user_memory([HumanMessage(content="")])
        assert formatted == []

    def test_ai_tool_call_line_carries_name_and_args(self):
        msgs = [
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "search", "args": {"q": "test"}}],
            )
        ]
        formatted = _format_messages_for_user_memory(msgs)
        assert formatted == [{"role": "assistant", "content": "[TOOL CALL: search({'q': 'test'})]"}]

    def test_ai_multiple_tool_calls_each_emit_a_line(self):
        msgs = [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc1", "name": "a", "args": {}},
                    {"id": "tc2", "name": "b", "args": {}},
                ],
            )
        ]
        formatted = _format_messages_for_user_memory(msgs)
        assert formatted == [
            {"role": "assistant", "content": "[TOOL CALL: a({})]"},
            {"role": "assistant", "content": "[TOOL CALL: b({})]"},
        ]

    def test_ai_tool_calls_take_precedence_over_content(self):
        # if/elif: when an AIMessage has BOTH tool_calls and content, the
        # tool-call branch wins and the plain text is NOT emitted.
        msgs = [
            AIMessage(
                content="i am thinking out loud",
                tool_calls=[{"id": "tc1", "name": "go", "args": {"k": 1}}],
            )
        ]
        formatted = _format_messages_for_user_memory(msgs)
        assert formatted == [{"role": "assistant", "content": "[TOOL CALL: go({'k': 1})]"}]

    def test_ai_text_only_becomes_assistant_role(self):
        formatted = _format_messages_for_user_memory([AIMessage(content="here is your answer")])
        assert formatted == [{"role": "assistant", "content": "here is your answer"}]

    def test_tool_output_at_limit_kept_verbatim(self):
        # Boundary: exactly MAX is NOT truncated (guard is strict `>`).
        content = "y" * MAX_TOOL_OUTPUT_SIZE
        formatted = _format_messages_for_user_memory(
            [ToolMessage(content=content, tool_call_id="tc1")]
        )
        assert formatted == [{"role": "assistant", "content": f"[TOOL RESULT: {content}]"}]

    def test_tool_output_past_limit_truncated(self):
        # One over MAX must truncate to exactly MAX chars + the marker.
        content = "z" * (MAX_TOOL_OUTPUT_SIZE + 1)
        formatted = _format_messages_for_user_memory(
            [ToolMessage(content=content, tool_call_id="tc1")]
        )
        expected_inner = "z" * MAX_TOOL_OUTPUT_SIZE + "... [truncated]"
        assert formatted == [{"role": "assistant", "content": f"[TOOL RESULT: {expected_inner}]"}]

    def test_system_messages_dropped(self):
        assert _format_messages_for_user_memory([SystemMessage(content="you are helpful")]) == []

    def test_empty_input_returns_empty_list(self):
        assert _format_messages_for_user_memory([]) == []

    def test_mixed_conversation_order_preserved(self):
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="reply"),
            ToolMessage(content="small", tool_call_id="t"),
        ]
        formatted = _format_messages_for_user_memory(msgs)
        assert formatted == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "reply"},
            {"role": "assistant", "content": "[TOOL RESULT: small]"},
        ]


@pytest.mark.unit
class TestExtractTextContent:
    def test_string_passthrough(self):
        assert _extract_text_content("hello") == "hello"

    def test_list_joins_text_blocks_only(self):
        blocks = [
            {"type": "text", "text": "part1"},
            {"type": "image", "url": "ignore-me"},
            "raw-string-part",
            {"type": "text", "text": "part2"},
        ]
        # Only str items and dicts with type=="text" survive, space-joined in order.
        assert _extract_text_content(blocks) == "part1 raw-string-part part2"

    def test_non_str_non_list_stringified(self):
        assert _extract_text_content(42) == "42"


@pytest.mark.unit
class TestStoreUserMemoryBackground:
    @pytest.mark.asyncio
    async def test_persists_to_user_namespace_with_prompt(self):
        with (
            patch(f"{MODULE}.memory_service") as svc,
            patch(f"{MODULE}.log") as log,
        ):
            svc.store_memory_batch = AsyncMock(return_value=True)
            await _store_user_memory_background(
                messages=_rich_messages(),
                # 12 chars so the logged prefix proves the exact [:8] slice.
                user_id="abcdefgh-XYZ",
                session_id="sess-9",
                extraction_prompt="learn slack ids",
                subagent_id="slack",
            )

        svc.store_memory_batch.assert_awaited_once()
        kwargs = svc.store_memory_batch.await_args.kwargs
        assert kwargs["user_id"] == "abcdefgh-XYZ"
        assert kwargs["conversation_id"] == "sess-9"
        assert kwargs["custom_instructions"] == "learn slack ids"
        assert kwargs["async_mode"] is True
        assert kwargs["metadata"] == {"memory_type": "user", "source_integration": "slack"}
        # Real formatted payload (not empty) is forwarded.
        assert {"role": "user", "content": "q1"} in kwargs["messages"]
        # Success is logged with the subagent label and an 8-char user-id prefix.
        assert log.info.call_args.args[0] == "[slack] User memory stored for abcdefgh..."

    @pytest.mark.asyncio
    async def test_metadata_omits_source_integration_without_subagent(self):
        with (
            patch(f"{MODULE}.memory_service") as svc,
            patch(f"{MODULE}.log") as log,
        ):
            svc.store_memory_batch = AsyncMock(return_value=True)
            await _store_user_memory_background(
                messages=_rich_messages(),
                user_id="abcdefgh-XYZ",
                session_id=None,
                extraction_prompt=None,
                subagent_id=None,
            )

        kwargs = svc.store_memory_batch.await_args.kwargs
        assert kwargs["metadata"] == {"memory_type": "user"}
        assert "source_integration" not in kwargs["metadata"]
        assert kwargs["conversation_id"] is None
        assert kwargs["custom_instructions"] is None
        # No subagent -> the "agent" fallback label is used in the success log.
        assert log.info.call_args.args[0] == "[agent] User memory stored for abcdefgh..."

    @pytest.mark.asyncio
    async def test_empty_payload_skips_storage(self):
        # Messages that format to nothing (system-only) must not hit mem0.
        with patch(f"{MODULE}.memory_service") as svc:
            svc.store_memory_batch = AsyncMock(return_value=True)
            await _store_user_memory_background(
                messages=[SystemMessage(content="ignored")],
                user_id="user-123",
                session_id="s",
                extraction_prompt=None,
                subagent_id=None,
            )

        svc.store_memory_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_storage_failure_is_swallowed_and_logged(self):
        with (
            patch(f"{MODULE}.memory_service") as svc,
            patch(f"{MODULE}.log") as log,
        ):
            svc.store_memory_batch = AsyncMock(side_effect=RuntimeError("mem0 is down"))
            # Must not raise — the except block absorbs the error.
            await _store_user_memory_background(
                messages=_rich_messages(),
                user_id="user-123",
                session_id="s",
                extraction_prompt=None,
                subagent_id="github",
            )
        svc.store_memory_batch.assert_awaited_once()
        # The failure is logged at error level with the subagent label and the
        # real exception text, and no success log is emitted.
        assert log.error.call_args.args[0] == "[github] User memory storage failed: mem0 is down"
        log.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_storage_failure_uses_agent_label_without_subagent(self):
        # The error log falls back to the "agent" label when no subagent_id.
        with (
            patch(f"{MODULE}.memory_service") as svc,
            patch(f"{MODULE}.log") as log,
        ):
            svc.store_memory_batch = AsyncMock(side_effect=ValueError("boom"))
            await _store_user_memory_background(
                messages=_rich_messages(),
                user_id="user-123",
                session_id="s",
                extraction_prompt=None,
                subagent_id=None,
            )
        assert log.error.call_args.args[0] == "[agent] User memory storage failed: boom"


@pytest.mark.unit
class TestMemoryNode:
    def _config(self, *, user_id=None, thread_id="t1", subagent_id=None):
        configurable = {"thread_id": thread_id}
        if user_id is not None:
            configurable["user_id"] = user_id
        if subagent_id is not None:
            configurable["subagent_id"] = subagent_id
        return {"configurable": configurable}

    @pytest.mark.asyncio
    async def test_trivial_conversation_returns_state_without_spawning(self):
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}
        with (
            patch(f"{MODULE}.asyncio.create_task") as create_task,
            patch(f"{MODULE}.log") as log,
        ):
            result = await memory_node(state, self._config(user_id="u1"), MagicMock())
        assert result is state
        create_task.assert_not_called()
        # The skip reason from _check_worth_learning is surfaced in the log.
        assert log.debug.call_args.args[0] == "Memory learning skipped: Too few messages"

    @pytest.mark.asyncio
    async def test_no_user_id_returns_state_without_spawning(self):
        state = {"messages": _rich_messages()}
        with patch(f"{MODULE}.asyncio.create_task") as create_task:
            result = await memory_node(state, self._config(), MagicMock())
        assert result is state
        create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_spawns_background_task_with_real_arguments(self):
        state = {"messages": _rich_messages()}
        config = self._config(user_id="u1", thread_id="thread-42")

        with (
            patch(f"{MODULE}._store_user_memory_background", new_callable=AsyncMock) as worker,
            patch(f"{MODULE}.asyncio.create_task") as create_task,
            patch(f"{MODULE}.log") as log,
        ):
            fake_task = MagicMock()
            fake_task.get_name.return_value = "user_memory"
            create_task.side_effect = lambda coro, **kw: (coro.close(), fake_task)[1]
            result = await memory_node(state, config, MagicMock())

        assert result is state
        create_task.assert_called_once()
        worker.assert_called_once()
        kwargs = worker.call_args.kwargs
        assert kwargs["user_id"] == "u1"
        assert kwargs["messages"] is state["messages"]
        assert kwargs["session_id"] == "thread-42"
        assert kwargs["subagent_id"] is None
        assert kwargs["extraction_prompt"] is None
        # The task is created under the "user_memory" name (used for tracing).
        assert create_task.call_args.kwargs["name"] == "user_memory"
        # The spawned task is retained (GC-safety) and given the done callback.
        fake_task.add_done_callback.assert_called_once_with(_task_done_callback)
        # Spawn is logged with the agent fallback label and the task name.
        spawn_msg = log.debug.call_args.args[0]
        assert spawn_msg == "[agent] Memory learning spawned: user_memory"

    @pytest.mark.asyncio
    async def test_subagent_id_drives_extraction_prompt_lookup(self):
        state = {"messages": _rich_messages()}
        config = self._config(user_id="u1", subagent_id="slack")

        with (
            patch(f"{MODULE}._store_user_memory_background", new_callable=AsyncMock) as worker,
            patch(f"{MODULE}.asyncio.create_task") as create_task,
            patch(
                f"{MODULE}.get_memory_extraction_prompt", return_value="SLACK PROMPT"
            ) as get_prompt,
        ):
            create_task.side_effect = lambda coro, **kw: (coro.close(), MagicMock())[1]
            await memory_node(state, config, MagicMock())

        get_prompt.assert_called_once_with("slack")
        kwargs = worker.call_args.kwargs
        assert kwargs["extraction_prompt"] == "SLACK PROMPT"
        assert kwargs["subagent_id"] == "slack"

    @pytest.mark.asyncio
    async def test_no_subagent_id_skips_prompt_lookup(self):
        state = {"messages": _rich_messages()}
        config = self._config(user_id="u1")

        with (
            patch(f"{MODULE}._store_user_memory_background", new_callable=AsyncMock),
            patch(f"{MODULE}.asyncio.create_task") as create_task,
            patch(f"{MODULE}.get_memory_extraction_prompt") as get_prompt,
        ):
            create_task.side_effect = lambda coro, **kw: (coro.close(), MagicMock())[1]
            await memory_node(state, config, MagicMock())

        get_prompt.assert_not_called()


@pytest.mark.unit
class TestTaskDoneCallback:
    def test_discards_completed_task_from_registry(self):
        task = MagicMock()
        _background_tasks.add(task)
        _task_done_callback(task)
        assert task not in _background_tasks

    def test_discard_is_safe_when_absent(self):
        # discard (not remove) must not raise on an unknown task.
        _task_done_callback(MagicMock())
