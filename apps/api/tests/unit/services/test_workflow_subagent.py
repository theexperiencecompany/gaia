"""What the workflow-authoring subagent hands back, and the lane it runs on.

The runner replaces the prepare/execute pair the oauth-registered subagents use,
so the two things every handoff has to get right are its own here: it must
inherit the executor's configurable (and with it the run's resolved lane), and it
must never hand ``create_workflow`` an empty string as if it were a draft.
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessageChunk, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
import pytest

from app.agents.context.assemble import AssembledContext
from app.constants.llm import WORKFLOW_SUBAGENT_RECURSION_LIMIT
from app.services.workflow.workflow_subagent import SubagentRunContext, WorkflowSubagentRunner

_MOD = "app.services.workflow.workflow_subagent"

# The runner still consumes messages through the deprecated ``.text()`` method
# call; the suite escalates warnings to errors, so the tests exercising it
# locally silence exactly that warning.
_TEXT_DEPRECATION = "ignore::langchain_core._api.deprecation.LangChainDeprecationWarning"


class _NoTextChunk(AIMessageChunk):
    """A chunk whose ``text`` attribute is absent, forcing the str(content) path."""

    @property
    def text(self) -> str:
        raise AttributeError("no text here")


class _FalsyToolMessage(ToolMessage):
    def __bool__(self) -> bool:
        return False


@dataclass
class _Run:
    """One execute() call: what it returned and the two calls it made."""

    result: str
    build_config: AsyncMock
    stream_turn: AsyncMock


async def _execute(draft: str, base_configurable: dict | None = None) -> _Run:
    """Drive execute() with everything outside it stubbed at its seams."""
    build_config = AsyncMock(return_value={"configurable": {"thread_id": "workflow_t1"}})
    stream_turn = AsyncMock(return_value=(draft, False))
    with (
        patch(f"{_MOD}.get_workflow_subagent", new_callable=AsyncMock, return_value=MagicMock()),
        patch(f"{_MOD}.build_agent_config", build_config),
        patch(
            f"{_MOD}.assemble_context",
            new_callable=AsyncMock,
            return_value=AssembledContext(
                stable=SystemMessage(content="ctx", additional_kwargs={"dynamic_context": True}),
                volatile=None,
            ),
        ),
        patch(
            f"{_MOD}.build_connected_integrations_hint",
            new_callable=AsyncMock,
            return_value="connected: none",
        ),
        patch.object(WorkflowSubagentRunner, "_stream_turn", stream_turn),
        patch.object(
            WorkflowSubagentRunner,
            "_draft_correction_needed",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await WorkflowSubagentRunner.execute(
            task="every monday, summarize my inbox",
            user_id="u1",
            thread_id="t1",
            context=SubagentRunContext(
                user_name="Dev", user_timezone="UTC", base_configurable=base_configurable
            ),
        )
    return _Run(result=result, build_config=build_config, stream_turn=stream_turn)


@pytest.mark.unit
class TestTheDraftItHandsBack:
    async def test_a_valid_draft_is_returned_verbatim(self) -> None:
        run = await _execute('{"title": "Inbox digest"}')

        assert run.result == '{"title": "Inbox digest"}'

    async def test_an_empty_answer_becomes_a_terminal_string_not_an_empty_draft(self) -> None:
        """``create_workflow`` reads this as the agent's answer; "" would look like
        a successful run that produced nothing."""
        run = await _execute("")

        assert run.result == "Task completed"


@pytest.mark.unit
class TestTheLaneItInherits:
    async def test_it_runs_on_its_parents_configurable(self) -> None:
        """The executor's bag carries the run's resolved lane, so without this a
        pro user's workflow authoring silently drops to the default model."""
        parent = {"user_id": "u1", "lane": {"provider": "openrouter", "model": "paid/model"}}

        run = await _execute('{"title": "x"}', base_configurable=parent)

        assert run.build_config.call_args.kwargs == {
            "conversation_id": "t1",
            "user": {"user_id": "u1", "email": None, "name": "Dev", "timezone": "UTC"},
            "thread_id": "workflow_t1",
            "agent_name": "workflow_agent",
            "subagent_id": "workflow_agent",
            "base_configurable": parent,
        }

    async def test_authoring_runs_on_a_capped_step_budget(self) -> None:
        """A wandering model must reach the forced-finalize fallback quickly rather
        than burning a full agent's recursion budget first."""
        run = await _execute('{"title": "x"}')

        config = run.stream_turn.call_args.args[2]
        assert config["recursion_limit"] == WORKFLOW_SUBAGENT_RECURSION_LIMIT

    async def test_the_context_stream_writer_reaches_the_streaming_loop(self) -> None:
        """The caller's writer is what forwards tool entries to the chat UI; a
        runner that drops it streams nothing without any error anywhere."""
        writer = MagicMock()
        with (
            patch(
                f"{_MOD}.get_workflow_subagent", new_callable=AsyncMock, return_value=MagicMock()
            ),
            patch(f"{_MOD}.build_agent_config", AsyncMock(return_value={"configurable": {}})),
            patch(
                f"{_MOD}.assemble_context",
                new_callable=AsyncMock,
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                ),
            ),
            patch(
                f"{_MOD}.build_connected_integrations_hint",
                new_callable=AsyncMock,
                return_value="connected: none",
            ),
            patch.object(
                WorkflowSubagentRunner,
                "_stream_turn",
                AsyncMock(return_value=('{"title": "x"}', False)),
            ) as stream_turn,
            patch.object(
                WorkflowSubagentRunner,
                "_draft_correction_needed",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await WorkflowSubagentRunner.execute(
                task="t",
                user_id="u1",
                thread_id="t1",
                context=SubagentRunContext(stream_writer=writer),
            )

        assert stream_turn.call_args.args[3] is writer


@pytest.mark.unit
class TestExecuteLogPins:
    async def test_execution_log_is_exact(self) -> None:
        # Drive through the shared stub helper so every seam execute() awaits is
        # mocked; this test only pins the log line.
        with (
            patch(
                f"{_MOD}.get_workflow_subagent", new_callable=AsyncMock, return_value=MagicMock()
            ),
            patch(f"{_MOD}.build_agent_config", AsyncMock(return_value={"configurable": {}})),
            patch(f"{_MOD}.assemble_context", new_callable=AsyncMock) as assemble,
            patch(
                f"{_MOD}.build_connected_integrations_hint",
                new_callable=AsyncMock,
                return_value="connected: none",
            ),
            patch.object(
                WorkflowSubagentRunner,
                "_stream_turn",
                AsyncMock(return_value=('{"title": "x"}', False)),
            ),
            patch.object(
                WorkflowSubagentRunner,
                "_draft_correction_needed",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.services.workflow.workflow_subagent.log") as log,
        ):
            assemble.return_value = AssembledContext(
                stable=SystemMessage(content="ctx", additional_kwargs={"dynamic_context": True}),
                volatile=None,
            )
            await WorkflowSubagentRunner.execute(task="t", user_id="u1", thread_id="t1")

        exec_logs = [
            c
            for c in log.info.call_args_list
            if "Executing workflow subagent task" in str(c.args[0])
        ]
        assert len(exec_logs) == 1
        assert exec_logs[0].kwargs["task_length"] == len("t")


class _StreamGraph:
    """Minimal astream stand-in yielding pre-built (mode, payload) events."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events

    async def astream(self, state: dict, stream_mode: Any = None, config: Any = None) -> Any:
        for event in self._events:
            yield event


@pytest.mark.unit
class TestConsumeMessageChunk:
    def test_a_silent_chunk_is_ignored(self) -> None:
        chunk = AIMessageChunk(content="hidden")

        result = WorkflowSubagentRunner._consume_message_chunk(
            (chunk, {"silent": True}), MagicMock(), "kept"
        )

        assert result == "kept"

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_an_ai_chunks_text_is_appended(self) -> None:
        result = WorkflowSubagentRunner._consume_message_chunk(
            (AIMessageChunk(content="Hello"), {}), None, ""
        )

        assert result == "Hello"

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_an_empty_ai_chunk_appends_nothing(self) -> None:
        result = WorkflowSubagentRunner._consume_message_chunk(
            (AIMessageChunk(content=""), {}), MagicMock(), "kept"
        )

        assert result == "kept"

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_a_tool_result_is_streamed_as_tool_output(self) -> None:
        writer = MagicMock()

        result = WorkflowSubagentRunner._consume_message_chunk(
            (ToolMessage(content="tool ran", tool_call_id="tc1"), {}), writer, ""
        )

        writer.assert_called_once_with(
            {"tool_output": {"tool_call_id": "tc1", "output": "tool ran"}}
        )
        assert result == ""

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_a_tool_result_without_a_writer_changes_nothing(self) -> None:
        result = WorkflowSubagentRunner._consume_message_chunk(
            (ToolMessage(content="tool ran", tool_call_id="tc1"), {}), None, ""
        )

        assert result == ""

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_a_block_list_content_is_unwrapped_via_text_not_str(self) -> None:
        """``text()`` extracts the blocks' text; ``str(content)`` would ship the
        raw repr of the block list to the user."""
        chunk = AIMessageChunk(content=[{"type": "text", "text": "abc", "index": 0}])

        result = WorkflowSubagentRunner._consume_message_chunk((chunk, {}), None, "")

        assert result == "abc"

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_a_chunk_without_text_falls_back_to_its_content(self) -> None:
        result = WorkflowSubagentRunner._consume_message_chunk(
            (_NoTextChunk(content="plain"), {}), None, ""
        )

        assert result == "plain"

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    def test_a_falsy_tool_message_is_skipped_like_any_falsy_chunk(self) -> None:
        """Only real message chunks reach the writer; a falsey value must not
        slip through the guard as a tool output."""
        writer = MagicMock()
        falsy_tool = _FalsyToolMessage(content="", tool_call_id="tc1")

        result = WorkflowSubagentRunner._consume_message_chunk((falsy_tool, {}), writer, "kept")

        writer.assert_not_called()
        assert result == "kept"


@pytest.mark.unit
class TestEmitUpdateEntries:
    async def test_each_new_tool_entry_is_streamed(self) -> None:
        entries = [
            ("tc1", {"tool_name": "search_triggers"}),
            ("tc2", {"tool_name": "list_workflows"}),
        ]
        writer = MagicMock()
        with patch(
            f"{_MOD}.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=entries,
        ) as extract:
            await WorkflowSubagentRunner._emit_update_entries(
                {"node": {"messages": []}}, writer, emitted_tool_calls={"tc0"}
            )

        extract.assert_awaited_once_with(state_update={"messages": []}, emitted_tool_calls={"tc0"})
        assert [c.args[0] for c in writer.call_args_list] == [
            {"tool_data": {"tool_name": "search_triggers"}},
            {"tool_data": {"tool_name": "list_workflows"}},
        ]

    async def test_no_writer_still_consumes_the_entries(self) -> None:
        with patch(
            f"{_MOD}.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=[("tc1", {"tool_name": "search_triggers"})],
        ):
            await WorkflowSubagentRunner._emit_update_entries(
                {"node": {"messages": []}}, None, set()
            )


@pytest.mark.unit
class TestStreamTurnModes:
    @staticmethod
    async def _run(events: list[Any]) -> tuple[str, bool, MagicMock]:
        writer = MagicMock()
        with patch(
            f"{_MOD}.extract_tool_entries_from_update",
            new_callable=AsyncMock,
            return_value=[("tc1", {"tool_name": "search_triggers"})],
        ):
            message, hit_limit = await WorkflowSubagentRunner._stream_turn(
                _StreamGraph(events), {}, {}, writer, set()
            )
        return message, hit_limit, writer

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    async def test_updates_messages_and_custom_events_are_each_dispatched(self) -> None:
        entry = {"tool_name": "search_triggers"}
        message, hit_limit, writer = await self._run(
            [
                ("updates", {"node": {"messages": []}}),
                ("messages", (AIMessageChunk(content="Hi "), {})),
                ("custom", {"step": 1}),
                ("bogus",),
                ("messages", (AIMessageChunk(content="there"), {})),
            ]
        )

        assert message == "Hi there"
        assert hit_limit is False
        assert [c.args[0] for c in writer.call_args_list] == [
            {"tool_data": entry},
            {"step": 1},
        ]

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    async def test_a_recursion_error_returns_the_partial_text_and_the_hit_flag(self) -> None:
        class _RecursingGraph(_StreamGraph):
            async def astream(
                self, state: dict, stream_mode: Any = None, config: Any = None
            ) -> Any:
                yield ("messages", (AIMessageChunk(content="partial"), {}))
                raise GraphRecursionError

        writer = MagicMock()
        message, hit_limit = await WorkflowSubagentRunner._stream_turn(
            _RecursingGraph([]), {}, {}, writer, set()
        )

        assert message == "partial"
        assert hit_limit is True

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    async def test_the_dedup_set_and_writer_are_forwarded_intact(self) -> None:
        """The caller's emitted-tool-calls set and stream writer must reach the
        per-event handlers — a dropped set would re-stream already-seen tool
        entries, and a dropped writer silently kills all streaming."""
        writer = MagicMock()
        dedup = {"tc0"}
        with (
            patch(
                f"{_MOD}.extract_tool_entries_from_update",
                new_callable=AsyncMock,
                return_value=[],
            ) as extract,
            patch.object(
                WorkflowSubagentRunner,
                "_consume_message_chunk",
                return_value="",
            ) as consume,
        ):
            await WorkflowSubagentRunner._stream_turn(
                _StreamGraph(
                    [
                        ("updates", {"node": {"messages": []}}),
                        ("messages", (AIMessageChunk(content="Hi"), {})),
                    ]
                ),
                {},
                {},
                writer,
                dedup,
            )

        assert extract.await_args.kwargs["emitted_tool_calls"] == dedup
        assert consume.call_args.args[1] is writer

    @pytest.mark.filterwarnings(_TEXT_DEPRECATION)
    async def test_a_custom_event_with_no_writer_is_ignored_not_fatal(self) -> None:
        message, hit_limit = await WorkflowSubagentRunner._stream_turn(
            _StreamGraph([("custom", {"step": 1})]), {}, {}, None, set()
        )

        assert message == ""
        assert hit_limit is False
