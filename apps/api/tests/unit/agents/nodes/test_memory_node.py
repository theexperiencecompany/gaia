from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.core.nodes.memory_node import (
    MAX_TOOL_OUTPUT_SIZE,
    _check_worth_learning,
    _format_messages_for_user_memory,
    _mark_ingested,
    _messages_to_ingest,
    _store_user_memory_background,
    memory_node,
)
from app.constants.memory import (
    MEMORY_DELTA_CONTEXT_MESSAGES,
    MEMORY_INGEST_MARK_KEY,
    MEMORY_INGEST_MARK_TTL,
    MemorySourceType,
)
from app.utils.multimodal import extract_text_content
from tests.helpers import WideEventRecorder

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
        # redis_cache.client is a property that ALWAYS builds a live client, so
        # without this patch the high-water-mark read dials a real Redis — and
        # on a host without one the connection error is swallowed by the same
        # suppress() this test is about, retain is never reached, and the
        # assertion below fails for a reason that has nothing to do with it.
        with (
            patch("app.agents.core.nodes.memory_node.memory_engine") as mock_engine,
            patch(f"{NODE}.redis_cache", _fake_redis(None)),
        ):
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


@pytest.mark.unit
class TestTheFencedTranscript:
    """The context/delta fence. It is prose inside a transcript, so a wrong
    marker row is invisible to every type checker and silently tells the
    extractor to re-extract facts it already stored."""

    @staticmethod
    def _thread() -> list[HumanMessage]:
        return [
            HumanMessage(content="my anniversary is October 19", id="m1"),
            HumanMessage(content="I moved to Bangalore last week", id="m2"),
            HumanMessage(content="and I start at Acme on Monday", id="m3"),
        ]

    def test_no_context_means_no_fence_at_all(self) -> None:
        assert _format_messages_for_user_memory(self._thread()) == [
            {"role": "user", "content": "my anniversary is October 19"},
            {"role": "user", "content": "I moved to Bangalore last week"},
            {"role": "user", "content": "and I start at Acme on Monday"},
        ]

    def test_the_fence_opens_the_transcript_and_splits_it_at_the_delta(self) -> None:
        """Pinned verbatim: both marker rows, their exact position, and the
        `transcript` role that separates them from anything a human or a tool
        said. One row out of place and the extractor reads already-stored facts
        as new disclosures."""
        assert _format_messages_for_user_memory(self._thread(), context_count=2) == [
            {
                "role": "transcript",
                "content": "--- earlier context: already extracted, do NOT re-extract ---",
            },
            {"role": "user", "content": "my anniversary is October 19"},
            {"role": "user", "content": "I moved to Bangalore last week"},
            {"role": "transcript", "content": "--- new since the last extraction ---"},
            {"role": "user", "content": "and I start at Acme on Monday"},
        ]

    def test_the_delta_marker_appears_exactly_once(self) -> None:
        formatted = _format_messages_for_user_memory(self._thread(), context_count=1)

        markers = [entry["content"] for entry in formatted if entry["role"] == "transcript"]
        assert markers.count("--- new since the last extraction ---") == 1

    def test_a_tool_call_is_rendered_with_its_arguments(self) -> None:
        """The args are the point: they carry the ids, names and emails the
        extractor mines. Rendering an empty dict loses that silently."""
        formatted = _format_messages_for_user_memory(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc1", "name": "add_memory", "args": {"content": "anniversary"}}
                    ],
                    id="m1",
                )
            ]
        )

        assert formatted == [
            {"role": "gaia", "content": "[CALLED TOOL: add_memory({'content': 'anniversary'})]"}
        ]

    def test_a_long_tool_output_is_truncated_with_a_marker(self) -> None:
        formatted = _format_messages_for_user_memory(
            [ToolMessage(content="x" * (MAX_TOOL_OUTPUT_SIZE + 50), tool_call_id="tc1", id="m1")]
        )

        assert formatted[0]["content"] == "x" * MAX_TOOL_OUTPUT_SIZE + "... [truncated]"


@pytest.mark.unit
class TestTheHighWaterMarkRead:
    """`_messages_to_ingest` decides what the extraction is billed for. Every
    boundary here is an off-by-one that either re-pays for the whole thread or
    drops the one message the user actually disclosed something in."""

    @staticmethod
    def _thread(count: int) -> list[HumanMessage]:
        return [HumanMessage(content=f"message {i}", id=f"m{i}") for i in range(count)]

    async def test_a_threadless_run_ingests_everything_as_new(self) -> None:
        messages = self._thread(2)

        assert await _messages_to_ingest("u1", None, messages) == (messages, 0)

    async def test_no_redis_client_ingests_everything_as_new(self) -> None:
        messages = self._thread(2)

        with patch(f"{NODE}.redis_cache", SimpleNamespace(client=None)):
            assert await _messages_to_ingest("u1", "t1", messages) == (messages, 0)

    async def test_the_mark_is_read_from_this_user_s_own_thread_key(self) -> None:
        """The key namespaces the mark by user AND thread. Collapse either half
        and one conversation's high-water mark suppresses another's ingestion."""
        fake = _fake_redis(None)

        with patch(f"{NODE}.redis_cache", fake):
            await _messages_to_ingest("u1", "t1", self._thread(1))

        fake.client.get.assert_awaited_once_with(
            MEMORY_INGEST_MARK_KEY.format(user_id="u1", thread_id="t1")
        )

    async def test_a_mark_on_the_final_message_leaves_nothing_to_ingest(self) -> None:
        """The whole thread is already extracted, so the run must cost nothing.
        Handing it back re-pays for every message in the conversation."""
        with patch(f"{NODE}.redis_cache", _fake_redis("m2")):
            assert await _messages_to_ingest("u1", "t1", self._thread(3)) == ([], 0)

    async def test_an_empty_thread_with_a_mark_is_not_an_error(self) -> None:
        """A cancelled or pruned turn can leave a mark with no messages behind
        it; walking off the end of an empty list must not raise."""
        with patch(f"{NODE}.redis_cache", _fake_redis("m0")):
            assert await _messages_to_ingest("u1", "t1", []) == ([], 0)

    async def test_the_context_window_is_capped_and_counted(self) -> None:
        """Only MEMORY_DELTA_CONTEXT_MESSAGES of already-extracted history ride
        along, and context_count must say how many — the fence is drawn from it,
        so a wrong count fences off the new material itself."""
        total = MEMORY_DELTA_CONTEXT_MESSAGES + 4
        messages = self._thread(total)
        mark = f"m{MEMORY_DELTA_CONTEXT_MESSAGES + 1}"

        with patch(f"{NODE}.redis_cache", _fake_redis(mark)):
            to_ingest, context_count = await _messages_to_ingest("u1", "t1", messages)

        assert context_count == MEMORY_DELTA_CONTEXT_MESSAGES
        assert [m.id for m in to_ingest[:context_count]] == [
            f"m{i}" for i in range(2, MEMORY_DELTA_CONTEXT_MESSAGES + 2)
        ]
        assert [m.id for m in to_ingest[context_count:]] == [
            f"m{i}" for i in range(MEMORY_DELTA_CONTEXT_MESSAGES + 2, total)
        ]


@pytest.mark.unit
class TestTheHighWaterMarkWrite:
    """`_mark_ingested` is what stops the next turn re-extracting this one. A
    wrong key writes a mark nothing reads; a missing TTL leaks it forever."""

    @staticmethod
    def _messages() -> list[HumanMessage]:
        # Three, not two: with two, messages[1] and messages[-1] are the same
        # entry, so a "last message" that is really an index-1 lookup passes.
        return [
            HumanMessage(content="first", id="m1"),
            HumanMessage(content="second", id="m2"),
            HumanMessage(content="third", id="m3"),
        ]

    async def test_the_mark_names_the_last_message_under_this_thread_s_key(self) -> None:
        fake = _fake_redis(None)

        with patch(f"{NODE}.redis_cache", fake):
            await _mark_ingested("u1", "t1", self._messages())

        fake.client.set.assert_awaited_once_with(
            MEMORY_INGEST_MARK_KEY.format(user_id="u1", thread_id="t1"),
            "m3",
            ex=MEMORY_INGEST_MARK_TTL,
        )

    @pytest.mark.parametrize(
        ("thread_id", "messages"),
        [
            (None, [HumanMessage(content="x", id="m1")]),
            ("t1", []),
            ("t1", [HumanMessage(content="x")]),
        ],
        ids=["no thread to key on", "nothing was ingested", "last message has no id"],
    )
    async def test_nothing_is_written_when_there_is_no_mark_to_write(
        self, thread_id: str | None, messages: list[HumanMessage]
    ) -> None:
        """Each guard stands alone — ANY one failing must stop the write, so a
        mark is never recorded for a turn that was not ingested."""
        fake = _fake_redis(None)

        with patch(f"{NODE}.redis_cache", fake):
            await _mark_ingested("u1", thread_id, messages)

        fake.client.set.assert_not_awaited()

    async def test_nothing_is_written_without_a_redis_client(self) -> None:
        with patch(f"{NODE}.redis_cache", SimpleNamespace(client=None)):
            await _mark_ingested("u1", "t1", self._messages())  # must not raise


@pytest.mark.unit
class TestTheIngestionHandoff:
    """What the background task passes to each collaborator. Every argument here
    is a user id, a thread id or a prompt: swap one and the extraction still
    "succeeds", against the wrong user, the wrong thread, or with no hints."""

    @staticmethod
    def _thread() -> list[HumanMessage]:
        return [
            HumanMessage(content="my anniversary is October 19", id="m1"),
            HumanMessage(content="I moved to Bangalore last week", id="m2"),
        ]

    async def _run(
        self,
        *,
        messages: list[AnyMessage] | None = None,
        user_id: str = "u1",
        session_id: str | None = "t1",
        extraction_prompt: str | None = "pull out slack ids",
        subagent_id: str | None = "slack",
        user_name: str | None = "Sam",
    ) -> dict[str, MagicMock]:
        engine = MagicMock()
        engine.retain = AsyncMock(return_value=None)
        fake = _fake_redis(None)
        with (
            patch(f"{NODE}.memory_engine", engine),
            patch(f"{NODE}.redis_cache", fake),
        ):
            await _store_user_memory_background(
                messages=self._thread() if messages is None else messages,
                user_id=user_id,
                session_id=session_id,
                extraction_prompt=extraction_prompt,
                subagent_id=subagent_id,
                user_name=user_name,
            )
        return {"retain": engine.retain, "redis": fake.client}

    async def test_the_extraction_is_billed_to_the_user_and_thread_it_came_from(self) -> None:
        """user_id keys the memory rows AND the mark; session_id is the memory's
        provenance. Either one wrong files one person's disclosure under
        another's account."""
        calls = await self._run()

        calls["retain"].assert_awaited_once()
        args, kwargs = calls["retain"].await_args
        assert args[0] == "u1"
        assert kwargs["source_id"] == "t1"
        assert kwargs["source_type"] == MemorySourceType.CONVERSATION

    async def test_the_integration_hints_and_user_name_ride_along(self) -> None:
        """The hints are why a Slack turn yields Slack ids. Dropped, extraction
        silently degrades to generic and nothing fails."""
        calls = await self._run()

        _, kwargs = calls["retain"].await_args
        assert kwargs["extraction_hints"] == "pull out slack ids"
        assert kwargs["user_name"] == "Sam"

    async def test_the_transcript_handed_over_is_the_formatted_one(self) -> None:
        calls = await self._run()

        args, _ = calls["retain"].await_args
        assert args[1] == [
            {"role": "user", "content": "my anniversary is October 19"},
            {"role": "user", "content": "I moved to Bangalore last week"},
        ]

    async def test_the_mark_is_read_and_written_under_the_same_user_s_thread(self) -> None:
        calls = await self._run()

        key = MEMORY_INGEST_MARK_KEY.format(user_id="u1", thread_id="t1")
        # Both halves, together: a read keyed to a different user than the write
        # computes the delta against somebody else's progress, and the thread
        # re-ingests forever.
        calls["redis"].get.assert_awaited_once_with(key)
        calls["redis"].set.assert_awaited_once_with(key, "m2", ex=MEMORY_INGEST_MARK_TTL)

    async def test_a_delta_run_hands_the_extractor_a_fenced_transcript(self) -> None:
        """context_count is not just a number — it is what draws the fence in the
        transcript retain() receives. Lose it between the two calls and already
        extracted messages arrive unmarked, which is the re-extraction this whole
        path exists to stop."""
        engine = MagicMock()
        engine.retain = AsyncMock(return_value=None)
        messages = [HumanMessage(content=f"message {i}", id=f"m{i}") for i in range(4)]

        with (
            patch(f"{NODE}.memory_engine", engine),
            patch(f"{NODE}.redis_cache", _fake_redis("m1")),
        ):
            await _store_user_memory_background(
                messages=messages,
                user_id="u1",
                session_id="t1",
                extraction_prompt=None,
                subagent_id=None,
                user_name=None,
            )

        transcript = engine.retain.await_args.args[1]
        assert transcript[0] == {
            "role": "transcript",
            "content": "--- earlier context: already extracted, do NOT re-extract ---",
        }
        assert {
            "role": "transcript",
            "content": "--- new since the last extraction ---",
        } in transcript

    async def test_the_provenance_check_asks_about_this_conversation(self) -> None:
        engine = MagicMock()
        engine.retain = AsyncMock(return_value=None)
        is_system = AsyncMock(return_value=False)

        with (
            patch(f"{NODE}.conversation_repository.is_system_generated", is_system),
            patch(f"{NODE}.memory_engine", engine),
            patch(f"{NODE}.redis_cache", _fake_redis(None)),
        ):
            await _store_user_memory_background(
                messages=self._thread(),
                user_id="u1",
                session_id="t1",
                extraction_prompt=None,
                subagent_id=None,
                user_name=None,
                conversation_id="c1",
            )

        is_system.assert_awaited_once_with("c1")

    async def test_a_skipped_system_conversation_says_so_in_the_wide_event(self) -> None:
        """The only record that a turn was deliberately not learned from. Without
        the reason on the event, a skipped ingestion and a broken one look the
        same in Loki."""
        engine = MagicMock()
        engine.retain = AsyncMock(return_value=None)

        with (
            patch(
                f"{NODE}.conversation_repository.is_system_generated", AsyncMock(return_value=True)
            ),
            patch(f"{NODE}.memory_engine", engine),
            patch(f"{NODE}.redis_cache", _fake_redis(None)),
        ):
            recorder = WideEventRecorder()
            with patch("shared.py.wide_events._loguru", recorder):
                await _store_user_memory_background(
                    messages=self._thread(),
                    user_id="u1",
                    session_id="t1",
                    extraction_prompt=None,
                    subagent_id=None,
                    user_name=None,
                    conversation_id="c1",
                )

        assert recorder.event("memory_retain")["memory_ingest"] == {
            "skipped": "system_generated_conversation"
        }

    async def test_the_wide_event_counts_the_thread_the_delta_and_the_context(self) -> None:
        """These three numbers are how the delta ingestion is monitored — they
        are what showed one conversation being re-extracted 76 times. The delta
        is the SUBTRACTION: add instead and a fully re-ingested thread reports
        as a small delta."""
        messages = [HumanMessage(content=f"message {i}", id=f"m{i}") for i in range(10)]
        engine = MagicMock()
        engine.retain = AsyncMock(return_value=None)

        with (
            patch(f"{NODE}.memory_engine", engine),
            patch(f"{NODE}.redis_cache", _fake_redis("m2")),
        ):
            recorder = WideEventRecorder()
            with patch("shared.py.wide_events._loguru", recorder):
                await _store_user_memory_background(
                    messages=messages,
                    user_id="u1",
                    session_id="t1",
                    extraction_prompt=None,
                    subagent_id=None,
                    user_name=None,
                )

        assert recorder.event("memory_retain")["memory_ingest"] == {
            "thread_messages": 10,
            "ingested_messages": 7,
            "context_messages": 3,
        }


@pytest.mark.unit
class TestWhatTheNodeSpawns:
    """The node's whole job is handing the right arguments to the background
    task. It returns state either way, so a wrong argument is silent."""

    @staticmethod
    def _spawn_capture() -> tuple[MagicMock, MagicMock]:
        spawn = MagicMock(side_effect=lambda coro, **kw: coro.close() or MagicMock())
        return spawn, MagicMock()

    async def test_the_task_is_named_so_it_is_identifiable_in_flight(self) -> None:
        """`spawn_background_task` strong-refs by name and the name is what the
        spawn log line reports; an unnamed task is unattributable in a trace."""
        spawn, store = self._spawn_capture()
        state = {"messages": [HumanMessage(content="my anniversary is October 19")]}
        config = {"configurable": {"user_id": "u1", "thread_id": "t1"}}

        with (
            patch(f"{NODE}._store_user_memory_background", new_callable=AsyncMock),
            patch(f"{NODE}.spawn_background_task", spawn),
        ):
            await memory_node(state, config, store)

        assert spawn.call_args.kwargs["name"] == "user_memory"

    async def test_the_subagent_s_extraction_prompt_reaches_the_task(self) -> None:
        """The prompt is resolved from subagent_id here and nowhere else — drop
        it and every integration turn extracts with generic hints."""
        spawn, store = self._spawn_capture()
        state = {"messages": [HumanMessage(content="my anniversary is October 19")]}
        config = {"configurable": {"user_id": "u1", "thread_id": "t1", "subagent_id": "slack"}}

        with (
            patch(f"{NODE}._store_user_memory_background", new_callable=AsyncMock) as background,
            patch(f"{NODE}.spawn_background_task", spawn),
            patch(f"{NODE}.get_memory_extraction_prompt", return_value="slack hints"),
        ):
            await memory_node(state, config, store)

        assert background.call_args.kwargs["extraction_prompt"] == "slack hints"
        assert background.call_args.kwargs["subagent_id"] == "slack"

    async def test_the_user_name_reaches_the_task(self) -> None:
        """retain uses it to attribute first-person facts to a named person."""
        spawn, store = self._spawn_capture()
        state = {"messages": [HumanMessage(content="my anniversary is October 19")]}
        config = {"configurable": {"user_id": "u1", "thread_id": "t1", "user_name": "Sam"}}

        with (
            patch(f"{NODE}._store_user_memory_background", new_callable=AsyncMock) as background,
            patch(f"{NODE}.spawn_background_task", spawn),
        ):
            await memory_node(state, config, store)

        assert background.call_args.kwargs["user_name"] == "Sam"
