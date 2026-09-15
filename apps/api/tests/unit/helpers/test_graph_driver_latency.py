"""Unit tests for graph-driver latency spans (execute_graph_streaming)."""

from collections.abc import AsyncGenerator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
from prometheus_client import REGISTRY
import pytest

from app.helpers.agent_helpers import execute_graph_streaming

HELPERS = "app.helpers.agent_helpers"


class _ScriptedGraph:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def astream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[tuple[Any, ...], None]:
        events = self._events

        async def stream() -> AsyncGenerator[tuple[Any, ...], None]:
            for event in events:
                yield event

        return stream()


def _graph_count(status: str) -> float:
    return REGISTRY.get_sample_value("comms_graph_seconds_count", {"status": status}) or 0.0


def _config() -> Any:
    return {"agent_name": "comms_agent", "configurable": {"user_id": "u1"}}


async def test_streaming_run_observes_graph_span() -> None:
    graph = _ScriptedGraph(
        [
            ((), "messages", (AIMessageChunk(id="m1", content="hi"), {})),
            ((), "updates", {"agent": {"messages": [AIMessage(id="m1", content="hi")]}}),
        ]
    )
    before = _graph_count("success")
    frames = [frame async for frame in execute_graph_streaming(graph, {}, _config())]
    assert any(f.startswith("data: ") and "hi" in f for f in frames)
    assert _graph_count("success") == before + 1


async def test_first_text_yield_stamps_pipeline_ttft() -> None:
    graph = _ScriptedGraph(
        [
            ((), "messages", (AIMessageChunk(id="m1", content="hi"), {})),
            ((), "updates", {"agent": {"messages": [AIMessage(id="m1", content="hi")]}}),
        ]
    )
    with patch(f"{HELPERS}.log") as mock_log:
        [frame async for frame in execute_graph_streaming(graph, {}, _config())]
    ttft_sets = [
        call.kwargs["comms_pipeline_ttft_ms"]
        for call in mock_log.set.call_args_list
        if "comms_pipeline_ttft_ms" in call.kwargs
    ]
    assert len(ttft_sets) == 1
    assert ttft_sets[0] >= 0.0


async def test_run_without_text_stamps_no_pipeline_ttft() -> None:
    graph = _ScriptedGraph([])
    with patch(f"{HELPERS}.log") as mock_log:
        frames = [frame async for frame in execute_graph_streaming(graph, {}, _config())]
    assert frames[-2].startswith("nostream: ")
    assert not [
        call for call in mock_log.set.call_args_list if "comms_pipeline_ttft_ms" in call.kwargs
    ]


async def test_first_text_yield_stamps_the_exact_rounded_milliseconds() -> None:
    """The stamp is first text minus run start, in ms to two places, with only agent_helpers' clock frozen."""
    graph = _ScriptedGraph(
        [
            ((), "messages", (AIMessageChunk(id="m1", content="hi"), {})),
            ((), "updates", {"agent": {"messages": [AIMessage(id="m1", content="hi")]}}),
        ]
    )
    # run_start, then the first-text stamp.
    ticks = iter([10.0, 11.234567])

    with (
        patch(f"{HELPERS}.time") as mock_time,
        patch(f"{HELPERS}.log") as mock_log,
    ):
        mock_time.perf_counter.side_effect = lambda: next(ticks)
        [frame async for frame in execute_graph_streaming(graph, {}, _config())]

    stamps = [
        call.kwargs["comms_pipeline_ttft_ms"]
        for call in mock_log.set.call_args_list
        if "comms_pipeline_ttft_ms" in call.kwargs
    ]
    assert stamps == [1234.57]


async def test_the_cancel_check_names_the_runs_own_stream() -> None:
    """The cancel flag is keyed by this run's own stream id, not another or none."""
    graph = _ScriptedGraph([((), "custom", {"progress": "working"})])
    config = {"agent_name": "comms_agent", "configurable": {"stream_id": "stream-42"}}

    with patch(f"{HELPERS}.stream_manager.is_cancelled", AsyncMock(return_value=False)) as check:
        [frame async for frame in execute_graph_streaming(graph, {}, config)]

    check.assert_awaited_with("stream-42")


async def test_a_cancelled_run_observes_the_cancelled_status() -> None:
    graph = _ScriptedGraph([((), "custom", {"progress": "working"})])
    config = {"agent_name": "comms_agent", "configurable": {"stream_id": "stream-1"}}
    before = _graph_count("cancelled")

    with (
        patch(f"{HELPERS}.stream_manager.is_cancelled", AsyncMock(return_value=True)),
        patch(f"{HELPERS}.record_interruption", AsyncMock()),
    ):
        [frame async for frame in execute_graph_streaming(graph, {}, config)]

    assert _graph_count("cancelled") == before + 1


async def test_a_graph_error_observes_the_error_status_and_reraises() -> None:
    class _ExplodingGraph:
        def astream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[tuple[Any, ...], None]:
            async def stream() -> AsyncGenerator[tuple[Any, ...], None]:
                yield ((), "custom", {"progress": "working"})
                raise RuntimeError("graph blew up")

            return stream()

    before = _graph_count("error")

    with pytest.raises(RuntimeError, match="graph blew up"):
        [frame async for frame in execute_graph_streaming(_ExplodingGraph(), {}, _config())]

    assert _graph_count("error") == before + 1


async def test_aclose_mid_stream_observes_the_abandoned_status() -> None:
    """A close without cancellation or exception, the shutdown path, is neither success nor cancelled."""
    graph = _ScriptedGraph(
        [
            ((), "custom", {"progress": "working"}),
            ((), "custom", {"progress": "never reached"}),
        ]
    )
    before = _graph_count("abandoned")

    generator = execute_graph_streaming(graph, {}, _config())
    first = await generator.__anext__()
    assert first == f"data: {json.dumps({'progress': 'working'})}\n\n"
    await generator.aclose()

    assert _graph_count("abandoned") == before + 1
