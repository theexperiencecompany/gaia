"""The chat turn's overhead clock: stamped by the reply reader, recorded at turn close."""

from collections.abc import Iterator

from prometheus_client import REGISTRY
import pytest

from app.agents.core.background.executor_capture import (
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.background.session import get_session
from app.services.chat import stream as stream_module
from app.services.turn_clock import TurnClock, TurnMark
from app.services.turn_timings import Store, TurnPhase, TurnStep, TurnTimings
from tests.helpers import captured_wide_event

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


async def test_turn_close_records_every_stage_of_a_complete_clock(clock: TurnClock) -> None:
    # Sub-millisecond stamps, so the event's 2-decimal rounding of each stretch is pinned.
    clock.note_comms_call()
    clock.marks[TurnMark.T0] = 100.0101234
    clock.marks[TurnMark.LLM_REQUEST] = 100.0905678
    clock.marks[TurnMark.LLM_FIRST_CHUNK] = 101.2909906
    clock.marks[TurnMark.FRAME_WRITTEN] = 101.3054321
    before = {stage: _overhead_count(stage) for stage in ("ingress", "prep", "egress", "total")}
    state = stream_module._StreamState(turn_id=None)

    async with captured_wide_event() as event:
        stream_module._close_turn_timings(
            _STREAM_ID, state, source="web", voice_mode=False, status="success"
        )

    for stage, count in before.items():
        assert _overhead_count(stage) == count + 1
    assert event["latency"] == {
        "ingress_ms": 10.12,
        "prep_ms": 80.44,
        "egress_ms": 14.44,
        "total_ms": 105.01,
        "provider_ttft_ms": 1200.42,  # 1200.4228 ms, so a third decimal would show
        "path": "direct",
        "comms_calls_before_text": 1,
    }


async def test_a_delegated_turn_is_recorded_on_the_delegated_path(clock: TurnClock) -> None:
    clock.marks[TurnMark.LLM_REQUEST] = 100.090
    clock.marks[TurnMark.LLM_FIRST_CHUNK] = 101.290
    clock.marks[TurnMark.FRAME_WRITTEN] = 101.305
    before = _overhead_count("total", path="delegated")
    session = get_session(_STREAM_ID)
    assert session is not None
    session.executor_spawned = True
    state = stream_module._StreamState(turn_id=None)

    async with captured_wide_event() as event:
        stream_module._close_turn_timings(
            _STREAM_ID, state, source="web", voice_mode=False, status="success"
        )

    assert _overhead_count("total", path="delegated") == before + 1
    assert event["latency"]["path"] == "delegated"


async def test_a_turn_with_no_source_is_counted_under_unknown(clock: TurnClock) -> None:
    clock.marks[TurnMark.LLM_REQUEST] = 100.090
    clock.marks[TurnMark.LLM_FIRST_CHUNK] = 101.290
    clock.marks[TurnMark.FRAME_WRITTEN] = 101.305
    before = _overhead_count("total", source="unknown")

    stream_module._close_turn_timings(
        _STREAM_ID,
        stream_module._StreamState(turn_id=None),
        source=None,
        voice_mode=False,
        status="success",
    )

    assert _overhead_count("total", source="unknown") == before + 1


async def test_an_incomplete_clock_records_no_overhead_and_names_what_is_missing(
    clock: TurnClock,
) -> None:
    clock.marks[TurnMark.LLM_REQUEST] = 100.090
    before = _overhead_count("total")
    state = stream_module._StreamState(turn_id=None)

    async with captured_wide_event() as event:
        stream_module._close_turn_timings(
            _STREAM_ID, state, source="web", voice_mode=False, status="success"
        )

    assert _overhead_count("total") == before
    assert event["latency"] == {"missing_marks": ["llm_first_chunk", "frame_written"]}


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_turn_close_reports_the_steps_and_store_round_trips_of_each_phase(
    clock: TurnClock,
) -> None:
    timings = TurnTimings()
    timings.add_step(TurnPhase.INGRESS, TurnStep.SESSION, 0.004)
    timings.add_store_call(TurnStep.SESSION, Store.MONGO, 0.003)
    timings.enter(TurnPhase.PREP)
    timings.add_step(TurnPhase.PREP, TurnStep.CONTEXT, 0.05)
    clock.timings = timings
    clock.marks[TurnMark.LLM_REQUEST] = 100.110
    clock.marks[TurnMark.LLM_FIRST_CHUNK] = 101.0
    clock.marks[TurnMark.FRAME_WRITTEN] = 101.01
    labels = {"source": "telegram", "phase": "ingress"}
    steps_before = _sample("turn_step_seconds_count", **labels, step="session")
    mongo_before = _sample("turn_store_calls_sum", **labels, store="mongo")
    redis_count_before = _sample("turn_store_calls_count", **labels, store="redis")

    async with captured_wide_event() as event:
        stream_module._close_turn_timings(
            _STREAM_ID,
            stream_module._StreamState(turn_id=None),
            source="telegram",
            voice_mode=False,
            status="success",
        )

    assert event["latency"]["steps"] == {
        "ingress": {
            "session": {"ms": 4.0, "mongo_calls": 1, "mongo_ms": 3.0},
            "other": {"ms": 6.0},
        },
        "prep": {"context": {"ms": 50.0}, "other": {"ms": 50.0}},
    }
    assert _sample("turn_step_seconds_count", **labels, step="session") == steps_before + 1
    assert _sample("turn_store_calls_sum", **labels, store="mongo") == mongo_before + 1
    # A store the phase never touched still counts the turn, as zero round trips.
    assert _sample("turn_store_calls_count", **labels, store="redis") == redis_count_before + 1


async def test_a_turn_with_no_source_reports_its_steps_under_unknown(clock: TurnClock) -> None:
    timings = TurnTimings()
    timings.add_step(TurnPhase.INGRESS, TurnStep.CHARGE, 0.002)
    clock.timings = timings
    clock.marks[TurnMark.LLM_REQUEST] = 100.110
    clock.marks[TurnMark.LLM_FIRST_CHUNK] = 101.0
    clock.marks[TurnMark.FRAME_WRITTEN] = 101.01
    labels = {"source": "unknown", "phase": "ingress", "step": "charge"}
    before = _sample("turn_step_seconds_count", **labels)

    async with captured_wide_event():
        stream_module._close_turn_timings(
            _STREAM_ID,
            stream_module._StreamState(turn_id=None),
            source=None,
            voice_mode=False,
            status="success",
        )

    assert _sample("turn_step_seconds_count", **labels) == before + 1
