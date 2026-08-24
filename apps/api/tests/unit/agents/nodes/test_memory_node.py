from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.core.nodes.memory_node import (
    MAX_TOOL_OUTPUT_SIZE,
    _check_worth_learning,
    _format_messages_for_user_memory,
    _messages_to_ingest,
    _store_user_memory_background,
    memory_node,
)
from app.utils.multimodal import extract_text_content

NODE = "app.agents.core.nodes.memory_node"


def _fake_redis(mark: str | None) -> SimpleNamespace:
    """A stand-in for ``redis_cache`` holding one high-water mark."""
    client = SimpleNamespace(
        get=AsyncMock(return_value=mark),
        set=AsyncMock(return_value=True),
    )
    return SimpleNamespace(client=client)


class TestCheckWorthLearning:
    def test_too_few_messages(self):
        """Short user messages (< MIN_USER_CONTENT_CHARS) are not worth learning."""
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "No substantive user message" in reason

    def test_too_few_tool_calls(self):
        """Short user messages are skipped regardless of turn count."""
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        result, reason = _check_worth_learning(msgs)
        assert result is False
        assert "No substantive user message" in reason

    def test_exactly_one_tool_call_is_too_few(self):
        """Short user message is still skipped even with a tool call present."""
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
        assert "No substantive user message" in reason

    def test_worth_learning(self):
        """A substantive user message (>= MIN_USER_CONTENT_CHARS) is worth learning."""
        msgs = [
            HumanMessage(content="Please summarize my recent emails from the team."),
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
        assert formatted[0]["role"] == "gaia"
        assert formatted[0]["content"] == "[CALLED TOOL: search({'q': 'test'})]"

    def test_formats_ai_content(self):
        msgs = [AIMessage(content="here is your answer")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 1
        assert formatted[0] == {"role": "gaia", "content": "here is your answer"}

    def test_truncates_tool_outputs(self):
        long_content = "x" * 600
        msgs = [ToolMessage(content=long_content, tool_call_id="tc1")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 1
        output = formatted[0]["content"]
        assert output.endswith("... [truncated]")
        raw_content = output[: -len("... [truncated]")]
        assert len(raw_content) == MAX_TOOL_OUTPUT_SIZE

    def test_skips_system_messages(self):
        msgs = [SystemMessage(content="you are helpful")]
        formatted = _format_messages_for_user_memory(msgs)
        assert len(formatted) == 0

    def test_empty_messages(self):
        formatted = _format_messages_for_user_memory([])
        assert formatted == []


class TestExtractTextContent:
    def test_string_content(self):
        assert extract_text_content("hello") == "hello"

    def test_list_content(self):
        blocks = [
            {"type": "text", "text": "part1"},
            {"type": "text", "text": "part2"},
        ]
        result = extract_text_content(blocks)
        assert "part1" in result
        assert "part2" in result

    def test_other_content(self):
        result = extract_text_content(42)
        assert result == "42"


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
                HumanMessage(content="Please summarize my recent emails."),
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
        """memory_node must not spawn a background task when user_id is absent."""
        state = self._rich_state()
        config = self._make_config()  # no user_id, no subagent_id
        store = MagicMock()

        with patch("app.agents.core.nodes.memory_node.spawn_background_task") as mock_spawn:
            result = await memory_node(state, config, store)

        assert result is state
        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_spawns_background_task(self):
        """memory_node must spawn _store_user_memory_background with correct user_id and messages."""
        state = self._rich_state()
        config = self._make_config(user_id="u1")
        store = MagicMock()

        with (
            patch(
                "app.agents.core.nodes.memory_node._store_user_memory_background",
                new_callable=AsyncMock,
            ) as mock_background,
            patch(
                "app.agents.core.nodes.memory_node.spawn_background_task",
                side_effect=lambda coro, **kw: coro.close() or MagicMock(),
            ) as mock_spawn,
        ):
            result = await memory_node(state, config, store)

        mock_spawn.assert_called_once()
        mock_background.assert_called_once()

        call_kwargs = mock_background.call_args.kwargs
        assert call_kwargs["user_id"] == "u1"
        assert call_kwargs["messages"] == state["messages"]
        assert call_kwargs["session_id"] == "t1"
        assert call_kwargs["extraction_prompt"] is None or isinstance(
            call_kwargs["extraction_prompt"], str
        )
        assert result is state

    @pytest.mark.asyncio
    async def test_background_task_exception_is_swallowed(self):
        """retain exceptions must be caught inside _store_user_memory_background."""
        with patch("app.agents.core.nodes.memory_node.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(side_effect=RuntimeError("memory engine is down"))

            # Must not raise — the except block must absorb RuntimeError
            await _store_user_memory_background(
                messages=[
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
                ],
                user_id="u1",
                session_id="s1",
                extraction_prompt=None,
                subagent_id=None,
                user_name=None,
            )

        # If we reach here, the exception was swallowed correctly
        mock_engine.retain.assert_awaited_once()


@pytest.mark.unit
class TestExtractorInput:
    """What the extractor is shown: three roles, and only what is new."""

    @staticmethod
    def _thread() -> list[AIMessage | HumanMessage | ToolMessage]:
        return [
            HumanMessage(content="my anniversary is October 19", id="m1"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "add_memory", "args": {"content": "x"}}],
                id="m2",
            ),
            ToolMessage(content="Memory stored", tool_call_id="tc1", id="m3"),
            AIMessage(content="Noted — I have saved that.", id="m4"),
        ]

    def test_gaia_tool_calls_and_tool_results_are_three_distinct_roles(self) -> None:
        formatted = _format_messages_for_user_memory(self._thread())

        roles = [entry["role"] for entry in formatted]
        assert set(roles) == {"user", "gaia", "tool"}
        assert roles[0] == "user"
        assert roles[-1] == "gaia"

    def test_a_tool_result_is_never_labelled_as_something_gaia_said(self) -> None:
        formatted = _format_messages_for_user_memory(self._thread())

        tool_entries = [entry for entry in formatted if entry["role"] == "tool"]
        assert len(tool_entries) == 1
        assert "Memory stored" in tool_entries[0]["content"]


@pytest.mark.unit
class TestDeltaIngestion:
    """A growing thread is extracted once, not re-extracted every turn."""

    @staticmethod
    def _config(thread_id: str = "t1") -> dict[str, object]:
        return {"configurable": {"user_id": "u1", "thread_id": thread_id, "user_name": "Sam"}}

    async def test_the_first_run_ingests_the_whole_thread(self) -> None:
        messages = [HumanMessage(content="my anniversary is October 19", id="m1")]

        with patch(f"{NODE}.redis_cache", _fake_redis(None)):
            to_ingest, context_count = await _messages_to_ingest("u1", "t1", messages)

        assert to_ingest == messages
        assert context_count == 0

    async def test_a_second_run_only_sees_what_arrived_since(self) -> None:
        messages = [
            HumanMessage(content="my anniversary is October 19", id="m1"),
            AIMessage(content="Noted.", id="m2"),
            HumanMessage(content="I also moved to Bangalore last week", id="m3"),
        ]

        with patch(f"{NODE}.redis_cache", _fake_redis("m2")):
            to_ingest, context_count = await _messages_to_ingest("u1", "t1", messages)

        assert [message.id for message in to_ingest[context_count:]] == ["m3"]
        assert [message.id for message in to_ingest[:context_count]] == ["m1", "m2"]

    async def test_an_unknown_mark_falls_back_to_the_whole_thread(self) -> None:
        messages = [HumanMessage(content="hello there", id="m9")]

        with patch(f"{NODE}.redis_cache", _fake_redis("a-message-that-was-pruned")):
            to_ingest, context_count = await _messages_to_ingest("u1", "t1", messages)

        assert to_ingest == messages
        assert context_count == 0

    async def test_the_mark_advances_only_after_a_successful_ingestion(self) -> None:
        messages = [HumanMessage(content="my anniversary is October 19", id="m1")]

        with (
            patch(f"{NODE}.memory_engine") as engine,
            patch(f"{NODE}.redis_cache", _fake_redis(None)) as fake_redis,
        ):
            engine.retain = AsyncMock(side_effect=RuntimeError("pg down"))
            await _store_user_memory_background(
                messages=messages,
                user_id="u1",
                session_id="t1",
                extraction_prompt=None,
                subagent_id=None,
                user_name="Sam",
            )

        fake_redis.client.set.assert_not_awaited()


@pytest.mark.unit
class TestSystemGeneratedConversations:
    """GAIA talking to itself is not the user disclosing anything."""

    @staticmethod
    async def _ingest(*, system_generated: bool) -> AsyncMock:
        engine = MagicMock()
        engine.retain = AsyncMock(return_value=None)
        with (
            patch(
                f"{NODE}.conversation_repository.is_system_generated",
                AsyncMock(return_value=system_generated),
            ),
            patch(f"{NODE}.memory_engine", engine),
            patch(f"{NODE}.redis_cache", _fake_redis(None)),
        ):
            await _store_user_memory_background(
                messages=[HumanMessage(content="Run the daily digest workflow now", id="m1")],
                user_id="u1",
                session_id="t1",
                extraction_prompt=None,
                subagent_id=None,
                user_name="Sam",
                conversation_id="c1",
            )
        return engine.retain

    async def test_a_system_generated_conversation_is_not_ingested(self) -> None:
        retain = await self._ingest(system_generated=True)
        retain.assert_not_awaited()

    async def test_an_ordinary_conversation_is_ingested(self) -> None:
        retain = await self._ingest(system_generated=False)
        retain.assert_awaited_once()

    async def test_the_conversation_id_reaches_the_background_task(self) -> None:
        state = {"messages": [HumanMessage(content="my anniversary is October 19")]}
        config = {"configurable": {"user_id": "u1", "thread_id": "t1", "conversation_id": "c1"}}

        with (
            patch(f"{NODE}._store_user_memory_background", new_callable=AsyncMock) as background,
            patch(
                f"{NODE}.spawn_background_task",
                side_effect=lambda coro, **kw: coro.close() or MagicMock(),
            ),
        ):
            await memory_node(state, config, MagicMock())

        assert background.call_args.kwargs["conversation_id"] == "c1"
