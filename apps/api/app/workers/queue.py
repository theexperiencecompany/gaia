"""The one path app code uses to put work on the ARQ queue.

Every enqueue goes through :func:enqueue_worker_job so a job always carries the
trace id and the analytics context (attribution plus PostHog session) of
whatever caused it. ARQ's ctx is built by the worker and has no
channel for producer-supplied metadata, so both travel as reserved kwargs in
the job payload; app.workers.task_envelope.arq_task pops them back off before
the task function runs and binds them around it. No task
signature knows about it, and no call site can forget it.

Deploy note: because the id rides in the job payload, a worker running code
older than this module would reject the kwarg. API and worker ship from the same
image, so they only skew during a restart.
"""

from datetime import datetime, timedelta

from arq.connections import ArqRedis
from arq.jobs import Job

from shared.py.analytics.context import bound_analytics_context
from shared.py.wide_events import get_trace_id

TRACE_ID_KWARG = "_gaia_trace_id"
ANALYTICS_CONTEXT_KWARG = "_gaia_analytics_context"


async def enqueue_worker_job(
    pool: ArqRedis,
    function: str,
    *args: object,
    _job_id: str | None = None,
    _queue_name: str | None = None,
    _defer_until: datetime | None = None,
    _defer_by: float | timedelta | None = None,
    _expires: float | timedelta | None = None,
    _job_try: int | None = None,
    **kwargs: object,
) -> Job | None:
    """Enqueue an ARQ job stamped with the caller's trace id and analytics context.

    Returns None when ARQ deduped the job against an existing _job_id,
    exactly like pool.enqueue_job. Outside a wide-event boundary there is no
    trace to propagate and the worker mints a fresh id; outside every analytics
    entry point the job runs as the worker's own system work.
    """
    trace_id = get_trace_id()
    if trace_id:
        kwargs[TRACE_ID_KWARG] = trace_id
    analytics = bound_analytics_context()
    if analytics is not None:
        kwargs[ANALYTICS_CONTEXT_KWARG] = analytics.model_dump(mode="json")
    return await pool.enqueue_job(
        function,
        *args,
        _job_id=_job_id,
        _queue_name=_queue_name,
        _defer_until=_defer_until,
        _defer_by=_defer_by,
        _expires=_expires,
        _job_try=_job_try,
        **kwargs,
    )
