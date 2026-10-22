"""Unit tests: an interruption leaves one real error answer per dangling tool call.

The record exists so the next model turn sees what actually happened instead of
an unanswered tool call the pruning hook then erases. Every field of the
synthetic answer is therefore load-bearing: the id ties it to its call, the
name lets the provider match it, and the error status tells the model the call
did not succeed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.core.interruption import (
    INTERRUPTED_TOOL_RESULT,
    INTERRUPTION_MARKER,
    INTERRUPTION_SOURCE,
    _interrupted_tool_messages,
    build_interruption_messages,
    record_interruption,
)
from app.constants.log_tags import LogTag


def _call(call_id: str, name: str = "web_search") -> dict[str, Any]:
    return {"id": call_id, "name": name, "args": {"query": "kyoto"}}


class TestInterruptedToolMessages:
    def test_every_unanswered_call_gets_an_answer_with_the_exact_fields(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[_call("c1", "web_search"), _call("c2", "send_email")],
            )
        ]

        backfill = _interrupted_tool_messages(messages, set())

        assert [(m.content, m.tool_call_id, m.name, m.status) for m in backfill] == [
            (INTERRUPTED_TOOL_RESULT, "c1", "web_search", "error"),
            (INTERRUPTED_TOOL_RESULT, "c2", "send_email", "error"),
        ]

    def test_an_answered_call_is_not_answered_again(self) -> None:
        messages = [
            AIMessage(content="", tool_calls=[_call("c1"), _call("c2")]),
            ToolMessage(content="ok", tool_call_id="c1"),
        ]

        backfill = _interrupted_tool_messages(messages, {"c1"})

        assert [m.tool_call_id for m in backfill] == ["c2"]

    def test_a_call_with_an_empty_id_is_left_alone(self) -> None:
        # An id-less call cannot be matched to an answer; inventing one would
        # put an unrelated tool message into the transcript.
        messages = [AIMessage(content="", tool_calls=[_call("")])]

        assert _interrupted_tool_messages(messages, set()) == []

    def test_a_non_ai_message_does_not_end_the_scan(self) -> None:
        messages = [
            ToolMessage(content="ok", tool_call_id="c0"),
            AIMessage(content="", tool_calls=[_call("c1")]),
        ]

        backfill = _interrupted_tool_messages(messages, set())

        assert [m.tool_call_id for m in backfill] == ["c1"]

    def test_calls_from_every_ai_message_are_backfilled_in_order(self) -> None:
        messages = [
            AIMessage(content="", tool_calls=[_call("c1")]),
            ToolMessage(content="ok", tool_call_id="c1"),
            AIMessage(content="", tool_calls=[_call("c2")]),
        ]

        backfill = _interrupted_tool_messages(messages, {"c1"})

        assert [m.tool_call_id for m in backfill] == ["c2"]


class TestBuildInterruptionMessages:
    def test_empty_history_is_a_no_op(self) -> None:
        assert build_interruption_messages([]) == []

    def test_a_dangling_call_gets_an_answer_and_the_marker(self) -> None:
        messages = [
            HumanMessage(content="do a thing"),
            AIMessage(content="", tool_calls=[_call("c1")]),
        ]

        updates = build_interruption_messages(messages)

        assert len(updates) == 2
        answer, marker = updates
        assert isinstance(answer, ToolMessage)
        assert answer.tool_call_id == "c1"
        assert marker.content == INTERRUPTION_MARKER
        assert marker.additional_kwargs == {"lc_source": INTERRUPTION_SOURCE}

    def test_a_completed_reply_with_nothing_dangling_needs_no_record(self) -> None:
        messages = [HumanMessage(content="do a thing"), AIMessage(content="Done.")]

        assert build_interruption_messages(messages) == []

    def test_a_completed_reply_with_a_still_dangling_call_is_still_recorded(self) -> None:
        messages = [AIMessage(content="Done.", tool_calls=[_call("c1")])]

        updates = build_interruption_messages(messages)

        assert [type(m) for m in updates] == [ToolMessage, HumanMessage]
        assert updates[0].tool_call_id == "c1"

    def test_a_trailing_human_message_gets_the_marker(self) -> None:
        messages = [
            HumanMessage(content="do a thing"),
            AIMessage(content="Done."),
            HumanMessage("next?"),
        ]

        updates = build_interruption_messages(messages)

        assert len(updates) == 1
        assert updates[0].content == INTERRUPTION_MARKER


def _snapshot(messages: list[Any] | None) -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = {} if messages is None else {"messages": messages}
    return snapshot


class TestRecordInterruption:
    async def test_the_record_is_written_to_the_tool_node_with_ids(self) -> None:
        graph = MagicMock()
        graph.aget_state = AsyncMock(
            return_value=_snapshot([AIMessage(content="", tool_calls=[_call("c1")])])
        )
        graph.aupdate_state = AsyncMock()
        config = {"configurable": {"thread_id": "thread-1"}}

        with patch("app.agents.core.interruption.log") as mock_log:
            await record_interruption(graph, config)

        written = graph.aupdate_state.await_args.args[1]["messages"]
        assert [type(m) for m in written] == [ToolMessage, HumanMessage]
        assert all(m.id for m in written)
        graph.aupdate_state.assert_awaited_once()
        assert graph.aupdate_state.await_args.args[0] == config
        assert graph.aupdate_state.await_args.kwargs == {"as_node": "tools"}
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Recorded user interruption in checkpoint",
            thread_id="thread-1",
            backfilled_tool_calls=1,
        )

    async def test_an_empty_checkpoint_writes_nothing(self) -> None:
        graph = MagicMock()
        graph.aget_state = AsyncMock(return_value=_snapshot(None))
        graph.aupdate_state = AsyncMock()

        with (
            patch(
                "app.agents.core.interruption.build_interruption_messages",
                wraps=build_interruption_messages,
            ) as build,
            patch("app.agents.core.interruption.log"),
        ):
            await record_interruption(graph, {"configurable": {"thread_id": "thread-1"}})

        # A missing messages channel is an empty list, never None: the builder
        # walks it and the downstream write expects a list.
        build.assert_called_once_with([])
        graph.aupdate_state.assert_not_awaited()
