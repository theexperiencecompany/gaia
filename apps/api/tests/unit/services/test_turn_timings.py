"""Turn timings: steps and store round trips attributed to the phase they ran in."""

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import turn_timings
from app.services.turn_timings import (
    Store,
    StoreTally,
    TurnPhase,
    TurnStep,
    TurnTimings,
    begin_turn_timings,
    close_ingress,
    record_store_call,
    render_reports,
    turn_step,
)


@pytest.fixture
def clock() -> Iterator[list[float]]:
    """Feed perf_counter from a list, so a step's length is exactly what the test says."""
    ticks: list[float] = []
    with patch.object(turn_timings, "time", SimpleNamespace(perf_counter=lambda: ticks.pop(0))):
        yield ticks


@pytest.fixture(autouse=True)
def _isolated() -> Iterator[None]:
    """Start each test with no current turn or step, as each request does."""
    token_turn = turn_timings._turn.set(None)
    token_scope = turn_timings._scope.set(None)
    yield
    turn_timings._scope.reset(token_scope)
    turn_timings._turn.reset(token_turn)


def test_a_step_records_its_time_and_the_store_calls_made_inside_it(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([10.0, 10.25])

    with turn_step(TurnStep.SESSION):
        record_store_call(Store.MONGO, 0.007)
    record_store_call(Store.REDIS, 0.001)

    assert timings.steps == {(TurnPhase.INGRESS, TurnStep.SESSION): 0.25}
    assert timings.stores == {
        (TurnPhase.INGRESS, TurnStep.SESSION, Store.MONGO): StoreTally(calls=1, seconds=0.007),
        (TurnPhase.INGRESS, TurnStep.OTHER, Store.REDIS): StoreTally(calls=1, seconds=0.001),
    }


def test_a_step_run_twice_adds_up(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.1, 1.0, 1.3])

    with turn_step(TurnStep.RATE_LIMIT):
        pass
    with turn_step(TurnStep.RATE_LIMIT):
        pass

    assert timings.steps[(TurnPhase.INGRESS, TurnStep.RATE_LIMIT)] == pytest.approx(0.4)


def test_a_nested_step_leaves_its_time_and_calls_to_the_outer_one(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.5])

    with turn_step(TurnStep.CHARGE), turn_step(TurnStep.SESSION):
        record_store_call(Store.POSTGRES, 0.002)

    assert timings.steps == {(TurnPhase.INGRESS, TurnStep.CHARGE): 0.5}
    assert list(timings.stores) == [(TurnPhase.INGRESS, TurnStep.CHARGE, Store.POSTGRES)]


def test_a_closed_turn_attributes_nothing_more(clock: list[float]) -> None:
    timings = begin_turn_timings()
    timings.enter(TurnPhase.CLOSED)
    clock.extend([0.0, 1.0])

    with turn_step(TurnStep.ACCEPT):
        record_store_call(Store.MONGO, 0.01)

    assert (timings.steps, timings.stores) == ({}, {})


def test_phases_only_advance() -> None:
    timings = begin_turn_timings()
    timings.enter(TurnPhase.CLOSED)
    timings.enter(TurnPhase.INGRESS)

    assert timings.phase is TurnPhase.CLOSED


def test_the_report_fills_other_with_the_phase_time_no_step_covers(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.03])
    with turn_step(TurnStep.SESSION):
        record_store_call(Store.MONGO, 0.007)
    record_store_call(Store.REDIS, 0.001)

    report = timings.report(TurnPhase.INGRESS, phase_seconds=0.1)

    assert list(report) == [TurnStep.SESSION, TurnStep.OTHER]
    assert report[TurnStep.SESSION].seconds == pytest.approx(0.03)
    assert report[TurnStep.SESSION].stores == {Store.MONGO: StoreTally(calls=1, seconds=0.007)}
    assert report[TurnStep.OTHER].seconds == pytest.approx(0.07)
    assert report[TurnStep.OTHER].stores == {Store.REDIS: StoreTally(calls=1, seconds=0.001)}


def test_other_is_never_negative(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.2])
    with turn_step(TurnStep.SESSION):
        pass

    report = timings.report(TurnPhase.INGRESS, phase_seconds=0.1)

    assert report[TurnStep.OTHER].seconds == 0.0


async def test_a_task_spawned_by_the_request_records_into_the_same_turn() -> None:
    timings = begin_turn_timings()

    async def background() -> None:
        record_store_call(Store.POSTGRES, 0.004)

    await asyncio.create_task(background())

    assert timings.stores[(TurnPhase.INGRESS, TurnStep.OTHER, Store.POSTGRES)].calls == 1


def test_outside_a_request_nothing_is_recorded() -> None:
    with turn_step(TurnStep.ACCEPT):
        record_store_call(Store.MONGO, 0.01)

    assert turn_timings._turn.get() is None


def test_the_accept_closes_ingress_and_renders_it_for_the_wide_event(
    clock: list[float],
) -> None:
    timings = begin_turn_timings(started=0.01)
    clock.extend([0.01, 0.03, 0.03, 0.05, 0.08])
    with turn_step(TurnStep.SESSION):
        record_store_call(Store.MONGO, 0.007)
    with turn_step(TurnStep.ACCEPT):
        record_store_call(Store.MONGO, 0.004)
        record_store_call(Store.MONGO, 0.006)

    report = close_ingress()

    assert report is not None
    assert render_reports({TurnPhase.INGRESS: report}) == {
        "ingress": {
            "session": {"ms": 20.0, "mongo_calls": 1, "mongo_ms": 7.0},
            "accept": {"ms": 20.0, "mongo_calls": 2, "mongo_ms": 10.0},
            "other": {"ms": 30.0},
        },
    }
    assert timings.phase is TurnPhase.CLOSED


def test_ingress_closes_once(clock: list[float]) -> None:
    begin_turn_timings(started=0.0)
    clock.extend([0.05])

    assert close_ingress() is not None
    assert close_ingress() is None


def test_no_ingress_report_without_an_arrival_stamp() -> None:
    begin_turn_timings()

    assert close_ingress() is None


def test_no_ingress_report_outside_a_request() -> None:
    assert close_ingress() is None


async def test_work_a_step_spawned_that_outlives_it_counts_as_background(
    clock: list[float],
) -> None:
    timings = begin_turn_timings()
    release = asyncio.Event()

    async def spawned() -> None:
        record_store_call(Store.REDIS, 0.001)
        await release.wait()
        record_store_call(Store.REDIS, 0.002)

    clock.extend([0.0, 0.01])
    with turn_step(TurnStep.RATE_LIMIT):
        task = asyncio.create_task(spawned())
        await asyncio.sleep(0)
    release.set()
    await task

    assert timings.stores == {
        (TurnPhase.INGRESS, TurnStep.RATE_LIMIT, Store.REDIS): StoreTally(calls=1, seconds=0.001),
        (TurnPhase.INGRESS, TurnStep.BACKGROUND, Store.REDIS): StoreTally(calls=1, seconds=0.002),
    }


def test_rendered_times_are_milliseconds_to_two_decimals() -> None:
    timings = TurnTimings()
    timings.add_step(TurnPhase.INGRESS, TurnStep.SESSION, 0.0012345)

    rendered = render_reports(
        {TurnPhase.INGRESS: timings.report(TurnPhase.INGRESS, phase_seconds=0.0012345)}
    )

    assert rendered["ingress"]["session"]["ms"] == 1.23
