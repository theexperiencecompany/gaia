"""The repair rewrites polluted comms replies in place and removes the ones with nothing left."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
import pytest
from scripts.repair_comms_message_breaks import repair_thread, repair_writes

from app.constants.general import NEW_MESSAGE_BREAKER
from app.override.langgraph_bigtool.utils import messages_delta_reducer

BR = NEW_MESSAGE_BREAKER
CALL = [{"name": "call_executor", "args": {"task": "x"}, "id": "tc-1"}]


def test_a_tool_call_with_only_breaks_keeps_its_id_and_loses_the_breaks() -> None:
    [write] = repair_writes([AIMessage(id="a1", content=BR * 13, tool_calls=CALL)])
    assert isinstance(write, AIMessage)
    assert (write.id, write.content, write.tool_calls[0]["id"]) == ("a1", "", "tc-1")


def test_a_reply_with_only_breaks_is_removed() -> None:
    assert repair_writes([AIMessage(id="a2", content=BR * 3998 + "<NEW_MESSAGE_BREAK")]) == [
        RemoveMessage(id="a2")
    ]


def test_text_and_clean_messages_are_left_alone_or_trimmed() -> None:
    writes = repair_writes(
        [
            HumanMessage(id="h1", content=f"{BR}{BR}"),
            AIMessage(id="a3", content="already clean"),
            AIMessage(id="a4", content=f"on it{BR * 14}"),
        ]
    )
    assert [(w.id, w.content) for w in writes] == [("a4", "on it")]


def test_the_writes_replace_and_remove_through_the_real_reducer() -> None:
    history = [
        HumanMessage(id="h1", content="go"),
        AIMessage(id="a1", content=BR * 13, tool_calls=CALL),
        AIMessage(id="a2", content=BR * 3998),
    ]
    repaired = messages_delta_reducer(history, [repair_writes(history)])
    assert [(m.id, m.content) for m in repaired] == [("h1", "go"), ("a1", "")]


THREAD = "018ac94b-e526-427e-8bee-04d5de0d5274"
LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)
NOW = LONG_AGO + timedelta(days=1)


def _graph(*, parent_checkpoint: str, created_at: datetime = LONG_AGO) -> MagicMock:
    """Build a graph holding one polluted reply whose repair write lands on the given parent checkpoint."""
    polluted = AIMessage(id="a1", content=BR * 13, tool_calls=CALL)
    read = SimpleNamespace(
        values={"messages": [polluted]},
        created_at=created_at.isoformat(),
        config={"configurable": {"checkpoint_id": "cp-read"}},
    )
    after = SimpleNamespace(parent_config={"configurable": {"checkpoint_id": parent_checkpoint}})
    graph = MagicMock()
    graph.aget_state = AsyncMock(side_effect=[read, after])
    graph.aupdate_state = AsyncMock(return_value={"configurable": {"checkpoint_id": "cp-new"}})
    return graph


async def test_an_idle_thread_is_repaired_on_the_checkpoint_it_read() -> None:
    graph = _graph(parent_checkpoint="cp-read")

    report = await repair_thread(graph, THREAD, apply=True, now=NOW, live=frozenset())

    graph.aupdate_state.assert_awaited_once()
    assert (report.rewritten, report.removed, report.skipped_busy) == (1, 0, False)


async def test_a_thread_with_a_turn_in_flight_is_not_written() -> None:
    graph = _graph(parent_checkpoint="cp-read")

    report = await repair_thread(graph, THREAD, apply=True, now=NOW, live=frozenset({THREAD}))

    graph.aupdate_state.assert_not_awaited()
    assert report.skipped_busy


async def test_a_recently_written_thread_is_not_written() -> None:
    graph = _graph(parent_checkpoint="cp-read", created_at=NOW - timedelta(minutes=1))

    report = await repair_thread(graph, THREAD, apply=True, now=NOW, live=frozenset())

    graph.aupdate_state.assert_not_awaited()
    assert report.skipped_busy


async def test_a_write_that_landed_on_a_newer_checkpoint_fails_loudly() -> None:
    graph = _graph(parent_checkpoint="cp-someone-else")

    with pytest.raises(RuntimeError, match="changed during the repair"):
        await repair_thread(graph, THREAD, apply=True, now=NOW, live=frozenset())


async def test_a_dry_run_never_writes() -> None:
    graph = _graph(parent_checkpoint="cp-read")

    await repair_thread(graph, THREAD, apply=False, now=NOW, live=frozenset())

    graph.aupdate_state.assert_not_awaited()
