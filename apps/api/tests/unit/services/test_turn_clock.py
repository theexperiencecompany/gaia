"""TurnClock: the per-turn stage stamps that turn_overhead_seconds is built from."""

from contextvars import copy_context

import pytest
from starlette.requests import Request

from app.services.turn_clock import TurnClock, TurnMark, TurnPath, stamp_received
from app.services.turn_timings import TurnPhase, TurnTimings, current_turn_timings


def _clock_with(**offsets: float) -> TurnClock:
    """Build a clock received at 100.0 whose marks sit at 100.0 + offset seconds."""
    clock = TurnClock(received=100.0)
    for name, offset in offsets.items():
        clock.marks[TurnMark(name)] = 100.0 + offset
    return clock


def test_overhead_splits_stages_and_subtracts_provider_ttft() -> None:
    clock = _clock_with(t0=0.010, llm_request=0.090, llm_first_chunk=1.290, frame_written=1.305)

    overhead = clock.overhead()

    assert overhead is not None
    assert overhead.ingress == pytest.approx(0.010)
    assert overhead.prep == pytest.approx(0.080)
    assert overhead.provider_ttft == pytest.approx(1.200)
    assert overhead.egress == pytest.approx(0.015)
    assert overhead.total == pytest.approx(0.105)


@pytest.mark.parametrize("missing", list(TurnMark))
def test_overhead_is_none_when_any_mark_is_missing(missing: TurnMark) -> None:
    clock = _clock_with(t0=0.01, llm_request=0.09, llm_first_chunk=1.29, frame_written=1.3)
    del clock.marks[missing]

    assert clock.overhead() is None


def test_first_mark_wins() -> None:
    clock = TurnClock(received=0.0)
    clock.mark(TurnMark.LLM_REQUEST)
    first = clock.marks[TurnMark.LLM_REQUEST]

    clock.mark(TurnMark.LLM_REQUEST)

    assert clock.marks[TurnMark.LLM_REQUEST] == first


def test_path_is_direct_when_first_call_produced_the_text() -> None:
    clock = _clock_with(t0=0.01, llm_request=0.09, llm_first_chunk=1.29, frame_written=1.3)
    clock.note_comms_call()

    overhead = clock.overhead()

    assert overhead is not None
    assert overhead.path is TurnPath.DIRECT


def test_path_is_tool_loop_when_text_came_after_a_second_call() -> None:
    clock = _clock_with(t0=0.01, llm_request=0.09, llm_first_chunk=1.29)
    clock.note_comms_call()
    clock.note_comms_call()
    clock.mark(TurnMark.FRAME_WRITTEN)

    overhead = clock.overhead()

    assert overhead is not None
    assert overhead.path is TurnPath.TOOL_LOOP


def test_comms_calls_after_the_first_frame_do_not_change_the_path() -> None:
    clock = _clock_with(t0=0.01, llm_request=0.09, llm_first_chunk=1.29)
    clock.note_comms_call()
    clock.mark(TurnMark.FRAME_WRITTEN)
    clock.note_comms_call()

    overhead = clock.overhead()

    assert overhead is not None
    assert overhead.path is TurnPath.DIRECT


def test_path_is_delegated_when_the_turn_handed_off() -> None:
    clock = _clock_with(t0=0.01, llm_request=0.09, llm_first_chunk=1.29, frame_written=1.3)
    clock.note_comms_call()
    clock.delegated = True

    overhead = clock.overhead()

    assert overhead is not None
    assert overhead.path is TurnPath.DELEGATED


def test_clock_without_a_received_stamp_reports_no_overhead() -> None:
    clock = TurnClock(received=None)
    for mark in TurnMark:
        clock.mark(mark)

    assert clock.overhead() is None


def test_accepted_reads_the_middleware_stamp_and_marks_t0() -> None:
    request = Request({"type": "http", "state": {}})
    stamp_received(request)

    clock = TurnClock.accepted(request)

    assert clock.received is not None
    assert clock.marks[TurnMark.T0] >= clock.received


def test_accepted_without_the_middleware_stamp_has_no_received() -> None:
    clock = TurnClock.accepted(Request({"type": "http", "state": {}}))

    assert clock.received is None
    assert TurnMark.T0 in clock.marks


def test_missing_lists_absent_stamps_in_turn_order() -> None:
    clock = TurnClock(received=None)
    clock.mark(TurnMark.LLM_REQUEST)

    assert clock.missing() == ["received", "t0", "llm_first_chunk", "frame_written"]


def test_arrival_begins_the_turns_timings_in_ingress() -> None:
    def arrive() -> TurnTimings | None:
        stamp_received(Request({"type": "http", "state": {}}))
        return current_turn_timings()

    timings = copy_context().run(arrive)

    assert timings is not None
    assert timings.phase is TurnPhase.INGRESS


def test_acceptance_adopts_the_requests_timings_and_moves_them_to_prep() -> None:
    def accept() -> tuple[TurnClock, TurnTimings | None]:
        request = Request({"type": "http", "state": {}})
        stamp_received(request)
        return TurnClock.accepted(request), current_turn_timings()

    clock, timings = copy_context().run(accept)

    assert clock.timings is timings
    assert timings is not None
    assert timings.phase is TurnPhase.PREP


def test_the_first_model_request_closes_the_timings() -> None:
    timings = TurnTimings()
    clock = TurnClock(received=0.0, timings=timings)
    clock.mark(TurnMark.T0)

    clock.mark(TurnMark.LLM_REQUEST)

    assert timings.phase is TurnPhase.CLOSED


def test_a_clock_without_timings_still_stamps() -> None:
    clock = TurnClock(received=0.0)

    clock.mark(TurnMark.LLM_REQUEST)

    assert TurnMark.LLM_REQUEST in clock.marks
