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
    current_turn_timings,
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

    with turn_step(TurnStep.CONTEXT), turn_step(TurnStep.SESSION):
        record_store_call(Store.POSTGRES, 0.002)

    assert timings.steps == {(TurnPhase.INGRESS, TurnStep.CONTEXT): 0.5}
    assert list(timings.stores) == [(TurnPhase.INGRESS, TurnStep.CONTEXT, Store.POSTGRES)]


def test_steps_and_calls_land_in_the_phase_they_ran_in(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.1, 1.0, 1.2])

    with turn_step(TurnStep.SESSION):
        pass
    timings.enter(TurnPhase.PREP)
    with turn_step(TurnStep.CONTEXT):
        record_store_call(Store.POSTGRES, 0.003)

    assert timings.steps == {
        (TurnPhase.INGRESS, TurnStep.SESSION): pytest.approx(0.1),
        (TurnPhase.PREP, TurnStep.CONTEXT): pytest.approx(0.2),
    }
    assert list(timings.stores) == [(TurnPhase.PREP, TurnStep.CONTEXT, Store.POSTGRES)]


def test_a_closed_turn_attributes_nothing_more(clock: list[float]) -> None:
    timings = begin_turn_timings()
    timings.enter(TurnPhase.CLOSED)
    clock.extend([0.0, 1.0])

    with turn_step(TurnStep.CONTEXT):
        record_store_call(Store.MONGO, 0.01)

    assert (timings.steps, timings.stores) == ({}, {})


def test_phases_only_advance() -> None:
    timings = begin_turn_timings()
    timings.enter(TurnPhase.PREP)
    timings.enter(TurnPhase.INGRESS)

    assert timings.phase is TurnPhase.PREP


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


def test_the_report_keeps_only_the_asked_phase(clock: list[float]) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.1])
    with turn_step(TurnStep.SESSION):
        pass
    timings.enter(TurnPhase.PREP)

    report = timings.report(TurnPhase.PREP, phase_seconds=0.5)

    assert list(report) == [TurnStep.OTHER]


async def test_a_task_spawned_by_the_request_records_into_the_same_turn() -> None:
    timings = begin_turn_timings()

    async def background() -> None:
        record_store_call(Store.POSTGRES, 0.004)

    await asyncio.create_task(background())

    assert timings.stores[(TurnPhase.INGRESS, TurnStep.OTHER, Store.POSTGRES)].calls == 1


def test_outside_a_request_nothing_is_recorded() -> None:
    with turn_step(TurnStep.CONTEXT):
        record_store_call(Store.MONGO, 0.01)

    assert current_turn_timings() is None


def test_the_turn_reports_both_phases_and_renders_them_for_the_wide_event(
    clock: list[float],
) -> None:
    timings = begin_turn_timings()
    clock.extend([0.0, 0.02, 1.0, 1.1])
    with turn_step(TurnStep.SESSION):
        record_store_call(Store.MONGO, 0.007)
    timings.enter(TurnPhase.PREP)
    with turn_step(TurnStep.CONTEXT):
        record_store_call(Store.POSTGRES, 0.003)
        record_store_call(Store.POSTGRES, 0.002)

    reports = timings.reports(ingress=0.05, prep=0.3)

    assert render_reports(reports) == {
        "ingress": {
            "session": {"ms": 20.0, "mongo_calls": 1, "mongo_ms": 7.0},
            "other": {"ms": 30.0},
        },
        "prep": {
            "context": {"ms": 100.0, "postgres_calls": 2, "postgres_ms": 5.0},
            "other": {"ms": 200.0},
        },
    }


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

    rendered = render_reports(timings.reports(ingress=0.0012345, prep=0.0))

    assert rendered["ingress"]["session"]["ms"] == 1.23
