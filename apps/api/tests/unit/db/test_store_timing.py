"""Store clients report their round trips to the current chat turn."""

from collections.abc import Iterator
import itertools
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fakeredis
from fakeredis.aioredis import FakeConnection
import pytest
from redis.asyncio import ConnectionPool
from redis.exceptions import ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import store_timing
from app.db.store_timing import MongoTurnListener, TimedRedis, instrument_postgres
from app.services import turn_timings
from app.services.turn_timings import (
    Store,
    StoreTally,
    TurnPhase,
    TurnStep,
    TurnTimings,
    begin_turn_timings,
)


@pytest.fixture(autouse=True)
def _no_current_turn() -> Iterator[None]:
    """Start each test with no current turn, as each request does."""
    token = turn_timings._turn.set(None)
    yield
    turn_timings._turn.reset(token)


#: Each perf_counter read advances the store hooks' clock by this much: a round trip lasts one tick.
_TICK = 0.25


@pytest.fixture(autouse=True)
def _ticking_clock() -> Iterator[None]:
    """Drive the hooks' clock, so a duration is exact rather than bounded by wall time."""
    ticks = itertools.count()
    clock = SimpleNamespace(perf_counter=lambda: next(ticks) * _TICK)
    with patch.object(store_timing, "time", clock):
        yield


def _calls(timings: TurnTimings, store: Store) -> StoreTally:
    return timings.stores[(TurnPhase.INGRESS, TurnStep.OTHER, store)]


def _timed_redis() -> TimedRedis:
    pool = ConnectionPool(
        connection_class=FakeConnection, server=fakeredis.FakeServer(), decode_responses=True
    )
    return TimedRedis(connection_pool=pool)


def test_a_mongo_command_reports_the_drivers_duration_whether_it_succeeds_or_fails() -> None:
    timings = begin_turn_timings()
    listener = MongoTurnListener()

    listener.started(MagicMock())
    listener.succeeded(MagicMock(duration_micros=7_000))
    assert _calls(timings, Store.MONGO) == StoreTally(calls=1, seconds=0.007)
    listener.failed(MagicMock(duration_micros=3_000))
    assert _calls(timings, Store.MONGO) == StoreTally(calls=2, seconds=0.007 + 0.003)


async def test_each_postgres_statement_is_one_round_trip() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    instrument_postgres(engine)
    timings = begin_turn_timings()

    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
        await conn.execute(text("select 2"))
    await engine.dispose()

    tally = _calls(timings, Store.POSTGRES)
    assert tally.calls == 2
    assert tally.seconds == tally.calls * _TICK


async def test_each_redis_command_is_one_round_trip() -> None:
    client = _timed_redis()
    timings = begin_turn_timings()

    await client.set("k", "v")
    assert await client.get("k") == "v"

    tally = _calls(timings, Store.REDIS)
    assert tally.calls == 2
    assert tally.seconds == tally.calls * _TICK


async def test_a_redis_commands_options_reach_the_server() -> None:
    client = _timed_redis()
    await client.zadd("z", {"a": 1.5})

    assert await client.zrange("z", 0, -1, withscores=True) == [("a", 1.5)]


async def test_a_failed_command_in_a_pipeline_raises_by_default() -> None:
    client = _timed_redis()
    await client.set("text", "not a number")
    pipe = client.pipeline()
    pipe.incr("text")

    with pytest.raises(ResponseError):
        await pipe.execute()


def test_a_pipeline_keeps_its_transaction_mode_and_shard_hint() -> None:
    client = _timed_redis()

    assert client.pipeline().is_transaction is True
    assert client.pipeline(transaction=False).is_transaction is False
    assert client.pipeline(shard_hint="s1").shard_hint == "s1"


async def test_a_redis_pipeline_is_one_round_trip_however_many_commands_it_carries() -> None:
    client = _timed_redis()
    timings = begin_turn_timings()

    pipe = client.pipeline()
    pipe.set("a", "1")
    pipe.set("b", "2")
    pipe.get("a")
    assert await pipe.execute() == [True, True, "1"]

    tally = _calls(timings, Store.REDIS)
    assert tally.calls == 1
    assert tally.seconds == tally.calls * _TICK


async def test_store_calls_outside_a_request_are_not_recorded() -> None:
    client = _timed_redis()

    await client.set("k", "v")
    MongoTurnListener().succeeded(MagicMock(duration_micros=1_000))

    assert turn_timings._turn.get() is None


async def test_a_watched_pipelines_immediate_commands_are_round_trips_too() -> None:
    client = _timed_redis()
    await client.zadd("z", {"a": 1.5})
    timings = begin_turn_timings()
    async with client.pipeline() as pipe:
        await pipe.watch("counter")
        assert await pipe.zrange("z", 0, -1, withscores=True) == [("a", 1.5)]
        pipe.multi()
        pipe.incr("counter")
        assert await pipe.execute() == [1]

    # WATCH and ZRANGE run immediately (options intact), then MULTI/EXEC goes as one batch.
    tally = _calls(timings, Store.REDIS)
    assert tally.calls == 3
    assert tally.seconds == tally.calls * _TICK
