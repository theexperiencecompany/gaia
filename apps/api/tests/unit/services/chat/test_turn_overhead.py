"""The chat turn's overhead clock: stamped by the reply reader, recorded at turn close."""

from collections.abc import Iterator
from unittest.mock import patch

from prometheus_client import REGISTRY
import pytest

from app.agents.core.background.executor_capture import (
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.background.session import get_session
from app.services.chat import stream as stream_module
from app.services.turn_clock import TurnClock, TurnMark

_STREAM_ID = "turn-overhead-test-stream"
# The wire format subscribe_stream really yields: an SSE id line, then the data line.
# A bare "data:" fixture let a reader that never recognised a real frame pass.
_REPLY_CHUNK = 'id: 1700000000000-0\ndata: {"response": "Hi there"}\n\n'
_INIT_CHUNK = 'id: 1700000000000-1\ndata: {"conversation_id": "c1"}\n\n'


@pytest.fixture
def clock() -> Iterator[TurnClock]:
    turn_clock = TurnClock(received=100.0)
    turn_clock.marks[TurnMark.T0] = 100.010
    register_executor_capture(_STREAM_ID, clock=turn_clock)
    yield turn_clock
    teardown_executor_capture(_STREAM_ID)


def _overhead_count(stage: str, path: str = "direct", source: str = "web") -> float:
    return (
        REGISTRY.get_sample_value(
            "turn_overhead_seconds_count", {"source": source, "stage": stage, "path": path}
        )
        or 0.0
    )


def test_reply_reader_stamps_only_the_first_reply_frame(clock: TurnClock) -> None:
    stream_module.note_reply_delivered(_STREAM_ID, _INIT_CHUNK)
    assert TurnMark.FRAME_WRITTEN not in clock.marks

    stream_module.note_reply_delivered(_STREAM_ID, _REPLY_CHUNK)
    first = clock.marks[TurnMark.FRAME_WRITTEN]
    stream_module.note_reply_delivered(_STREAM_ID, _REPLY_CHUNK)

    assert clock.marks[TurnMark.FRAME_WRITTEN] == first


def test_reply_reader_without_a_session_is_a_no_op() -> None:
    stream_module.note_reply_delivered("no-such-stream", _REPLY_CHUNK)

    assert get_session("no-such-stream") is None


def test_turn_close_records_every_stage_of_a_complete_clock(clock: TurnClock) -> None:
    clock.note_comms_call()
    clock.marks[TurnMark.LLM_REQUEST] = 100.090
    clock.marks[TurnMark.LLM_FIRST_CHUNK] = 101.290
    clock.marks[TurnMark.FRAME_WRITTEN] = 101.305
    before = {stage: _overhead_count(stage) for stage in ("ingress", "prep", "egress", "total")}
    state = stream_module._StreamState(turn_id=None)

    with patch.object(stream_module.log, "set") as log_set:
        stream_module._close_turn_timings(
            _STREAM_ID, state, source="web", voice_mode=False, status="success"
        )

    for stage, count in before.items():
        assert _overhead_count(stage) == count + 1
    latency = next(c.kwargs["latency"] for c in log_set.call_args_list if "latency" in c.kwargs)
    assert latency["total_ms"] == pytest.approx(105.0)
    assert latency["provider_ttft_ms"] == pytest.approx(1200.0)
    assert latency["path"] == "direct"


def test_an_incomplete_clock_records_no_overhead_and_names_what_is_missing(
    clock: TurnClock,
) -> None:
    clock.marks[TurnMark.LLM_REQUEST] = 100.090
    before = _overhead_count("total")
    state = stream_module._StreamState(turn_id=None)

    with patch.object(stream_module.log, "set") as log_set:
        stream_module._close_turn_timings(
            _STREAM_ID, state, source="web", voice_mode=False, status="success"
        )

    assert _overhead_count("total") == before
    latency = next(c.kwargs["latency"] for c in log_set.call_args_list if "latency" in c.kwargs)
    assert latency == {"missing_marks": ["llm_first_chunk", "frame_written"]}
