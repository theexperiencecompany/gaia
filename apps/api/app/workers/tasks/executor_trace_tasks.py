"""ARQ cron task: close the executor runs whose process died before they ended."""

from collections.abc import Mapping

from app.services.executor_trace.recorder import reap_abandoned_runs
from shared.py.wide_events import log


async def reap_abandoned_executor_runs(_ctx: Mapping[str, object]) -> str:
    """Mark every run left running past the timeout, with no live executor behind it, abandoned."""
    reaped = await reap_abandoned_runs()
    log.set(abandoned_runs=reaped)
    return f"abandoned={reaped}"
