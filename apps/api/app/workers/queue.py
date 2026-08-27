"""The one path app code uses to put work on the ARQ queue.

Every enqueue goes through :func:`enqueue_worker_job` so a job always carries the
trace id of whatever caused it. ARQ's ``ctx`` is built by the worker and has no
channel for producer-supplied metadata, so the id travels as a reserved kwarg in
the job payload; ``app.workers.task_envelope.arq_task`` pops it back off before
the task function runs and hands it to the task's wide-event boundary. No task
signature knows about it, and no call site can forget it.

Deploy note: because the id rides in the job payload, a worker running code
older than this module would reject the kwarg. API and worker ship from the same
image, so they only skew during a restart.
"""

from typing import Any

from arq.connections import ArqRedis
from arq.jobs import Job

from shared.py.wide_events import get_trace_id

TRACE_ID_KWARG = "_gaia_trace_id"


async def enqueue_worker_job(
    pool: ArqRedis,
    function: str,
    *args: Any,  # noqa: ANN401 -- ARQ's enqueue_job takes an arbitrary arg bag upstream
    **kwargs: Any,  # noqa: ANN401 -- ARQ's enqueue_job takes an arbitrary arg bag upstream
) -> Job | None:
    """Enqueue an ARQ job stamped with the caller's trace id.

    Returns ``None`` when ARQ deduped the job against an existing ``_job_id``,
    exactly like ``pool.enqueue_job``. Outside a wide-event boundary (a cron
    fire, a process with no inbound trace) there is nothing to propagate, so the
    kwarg is omitted and the worker mints a fresh id for the job.
    """
    trace_id = get_trace_id()
    if trace_id:
        kwargs[TRACE_ID_KWARG] = trace_id
    return await pool.enqueue_job(function, *args, **kwargs)
