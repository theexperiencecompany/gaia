"""Readiness: whether every backing service answers a real request.

Liveness (/health) says the API process is up; this says it can do work. Each
check is a genuine round-trip through the client the app itself uses, bounded
by a timeout so one hung dependency cannot stall the probe.
"""

import asyncio
from collections.abc import Awaitable, Callable
import time

from sqlalchemy import text

from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.health import ping_mongodb
from app.db.postgresql import get_postgresql_engine
from app.db.rabbitmq import get_rabbitmq_publisher
from app.db.redis import redis_cache
from app.models.health_models import DependencyStatus, ReadinessResponse
from shared.py.wide_events import log

READINESS_CHECK_TIMEOUT_SECONDS = 2.0


class DependencyNotConnectedError(ConnectionError):
    """A client reported itself disconnected without raising."""


async def _ping_postgres() -> None:
    engine = await get_postgresql_engine()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _ping_redis() -> None:
    await redis_cache.client.ping()


async def _ping_rabbitmq() -> None:
    publisher = await get_rabbitmq_publisher()
    if not await publisher.is_connected():
        raise DependencyNotConnectedError("RabbitMQ connection is closed")


async def _ping_chroma() -> None:
    client = await ChromaClient.get_client()
    await client.heartbeat()


DEPENDENCY_CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "mongodb": ping_mongodb,
    "postgres": _ping_postgres,
    "redis": _ping_redis,
    "rabbitmq": _ping_rabbitmq,
    "chromadb": _ping_chroma,
}


async def _check(name: str, ping: Callable[[], Awaitable[None]]) -> DependencyStatus:
    started = time.monotonic()
    try:
        await asyncio.wait_for(ping(), timeout=READINESS_CHECK_TIMEOUT_SECONDS)
    except Exception as e:  # each failure is reported for its dependency, never swallowed
        log.warning(
            f"{LogTag.STARTUP} Readiness check failed",
            dependency=name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return DependencyStatus(
            name=name,
            ok=False,
            latency_ms=round((time.monotonic() - started) * 1000, 2),
            error_type=type(e).__name__,
        )
    return DependencyStatus(
        name=name, ok=True, latency_ms=round((time.monotonic() - started) * 1000, 2)
    )


async def check_readiness() -> ReadinessResponse:
    """Run every dependency check concurrently and report each outcome."""
    results = await asyncio.gather(
        *(_check(name, ping) for name, ping in DEPENDENCY_CHECKS.items())
    )
    ready = all(result.ok for result in results)
    return ReadinessResponse(status="ready" if ready else "not_ready", dependencies=list(results))
