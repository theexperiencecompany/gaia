"""Each store client reports its round trips to the current chat turn's timings.

One hook per client, attached where the client is built: a Mongo command
listener, SQLAlchemy cursor events on the Postgres engine, and a Redis client
whose commands and pipelines time themselves. Outside a request they record
nothing (record_store_call finds no current turn).

LangGraph's checkpointer runs on its own psycopg pool, outside SQLAlchemy, so
its queries are not counted here; the agent_state step times them instead.
"""

import time

from pymongo import monitoring
from redis.asyncio.client import Pipeline, Redis
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.turn_timings import Store, record_store_call

#: Connection.info key holding the start times of the statements in flight on it.
_PG_STARTED = "turn_store_started"


class MongoTurnListener(monitoring.CommandListener):
    """Report every Mongo command, failed or not, with the driver's own duration."""

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        """Nothing to record until the command ends."""

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        record_store_call(Store.MONGO, event.duration_micros / 1_000_000)

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        record_store_call(Store.MONGO, event.duration_micros / 1_000_000)


def _statement_started(conn: Connection, *_: object) -> None:
    conn.info.setdefault(_PG_STARTED, []).append(time.perf_counter())


def _statement_finished(conn: Connection, *_: object) -> None:
    record_store_call(Store.POSTGRES, time.perf_counter() - conn.info[_PG_STARTED].pop())


def instrument_postgres(engine: AsyncEngine) -> None:
    """Report every statement the engine executes."""
    event.listen(engine.sync_engine, "before_cursor_execute", _statement_started)
    event.listen(engine.sync_engine, "after_cursor_execute", _statement_finished)


class _TimedPipeline(Pipeline):
    """Report a pipeline batch as one round trip, and each immediate command as one too.

    A watched pipeline runs WATCH and its reads before MULTI immediately.
    """

    async def immediate_execute_command(self, *args: object, **options: object) -> object:
        started = time.perf_counter()
        try:
            return await super().immediate_execute_command(*args, **options)
        finally:
            record_store_call(Store.REDIS, time.perf_counter() - started)

    async def execute(self, raise_on_error: bool = True) -> list[object]:
        started = time.perf_counter()
        try:
            results: list[object] = await super().execute(raise_on_error)
            return results
        finally:
            record_store_call(Store.REDIS, time.perf_counter() - started)


class TimedRedis(Redis):
    """Redis client that reports each command and each pipeline as one round trip."""

    async def execute_command(self, *args: object, **options: object) -> object:
        started = time.perf_counter()
        try:
            return await super().execute_command(*args, **options)
        finally:
            record_store_call(Store.REDIS, time.perf_counter() - started)

    def pipeline(self, transaction: bool = True, shard_hint: str | None = None) -> Pipeline:
        return _TimedPipeline(
            self.connection_pool, self.response_callbacks, transaction, shard_hint
        )
