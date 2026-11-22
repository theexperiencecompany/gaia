"""A running run's stop mark, keyed by its stream id.

Written by work_cancel when a logged CancelWork (or the cancel_executor tool) names
the run, and by RunningSubagents when the run that dispatched a subagent stops. The
run reads it before each step and stops itself, in whichever process it runs.
"""

from app.constants.cache import RUN_STOP_PREFIX, RUN_STOP_TTL
from app.db.redis import redis_cache

_STOPPED = "1"


async def request_stop(stream_id: str) -> None:
    """Mark the run on this stream stopped."""
    await redis_cache.client.set(f"{RUN_STOP_PREFIX}{stream_id}", _STOPPED, ex=RUN_STOP_TTL)


async def stop_requested(stream_id: str) -> bool:
    """Whether the run on this stream has been told to stop."""
    return bool(await redis_cache.client.exists(f"{RUN_STOP_PREFIX}{stream_id}"))
