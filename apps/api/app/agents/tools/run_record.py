"""The run record: every tool call one run made, in order, keyed by its stream id.

Written by ``app.agents.tools.invocation``, so a call is in the record because it
ran, whatever path ran it: a graph tool node, the execute proxy, a sandbox script
calling back, an approved action run later. The one other writer is a workflow
fire whose replay stopped: it opens the heal run's record with the replay's
calls, which ran in that same fire. Redis, not process memory, because those
paths run in different processes (the workflow worker, the API serving a sandbox
callback).
"""

from collections.abc import Sequence
from functools import cache

import redis as redislib

from app.config.settings import settings
from app.constants.cache import RUN_RECORD_PREFIX, RUN_RECORD_TTL
from app.db.redis import redis_cache
from app.models.workflow_execution_models import RecordedCall


def _key(stream_id: str) -> str:
    return f"{RUN_RECORD_PREFIX}{stream_id}"


async def append_call(stream_id: str, call: RecordedCall) -> None:
    """Add one finished call to the end of a run's record."""
    key = _key(stream_id)
    await redis_cache.client.rpush(key, call.model_dump_json())
    await redis_cache.client.expire(key, RUN_RECORD_TTL)


async def seed_run_record(stream_id: str, calls: Sequence[RecordedCall]) -> None:
    """Open a run's record with calls made before it started, in their order."""
    if not calls:
        return
    key = _key(stream_id)
    await redis_cache.client.rpush(key, *(call.model_dump_json() for call in calls))
    await redis_cache.client.expire(key, RUN_RECORD_TTL)


@cache
def _sync_client() -> redislib.Redis:
    return redislib.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def append_call_sync(stream_id: str, call: RecordedCall) -> None:
    """Add one finished call from a sync tool path (LangGraph's sync node twins)."""
    key = _key(stream_id)
    client = _sync_client()
    client.rpush(key, call.model_dump_json())
    client.expire(key, RUN_RECORD_TTL)


async def read_run_record(stream_id: str) -> list[RecordedCall]:
    """Every call the run made so far, in the order each finished."""
    raw = await redis_cache.client.lrange(_key(stream_id), 0, -1)
    return [RecordedCall.model_validate_json(entry) for entry in raw]
