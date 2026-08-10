"""The observability envelope every ARQ task runs behind.

``arq_task`` is applied once per task in ``app.worker`` at registration time, so
a task cannot reach ``WorkerSettings`` without it. It owns the two things every
task needs and no task body should have to remember:

* the ``worker_task`` wide-event boundary, carrying the trace id propagated by
  ``app.workers.queue.enqueue_worker_job`` plus ARQ's ``job_id`` / ``job_try`` — the
  latter two are what make a retry chain queryable.
* the Prometheus duration/outcome metrics behind the ``arq-worker`` dashboard.

Task bodies therefore call ``log.set(...)`` directly: the boundary is already
open by the time they run.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
import functools
import time
from typing import ParamSpec, TypeVar

from app.workers.metrics import TASK_DURATION_SECONDS, TASK_TOTAL
from app.workers.queue import TRACE_ID_KWARG
from shared.py.wide_events import wide_task

T = TypeVar("T")
P = ParamSpec("P")


def arq_task(
    func: Callable[P, Coroutine[None, None, T]],
) -> Callable[P, Coroutine[None, None, T]]:
    """Wrap an ARQ task coroutine in the wide-event + metrics envelope."""

    task_name = func.__name__

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # ARQ invokes tasks as ``task(ctx, *args, **kwargs)``, so the context is
        # the first positional argument; it is always a dict at runtime.
        ctx = args[0]
        if not isinstance(ctx, dict):
            raise TypeError(f"ARQ task '{task_name}' context must be a dict")
        # Absent only when a caller (a test) invokes the task with a bare ctx;
        # omitting the keys beats emitting nulls the dashboards would have to skip.
        job_context = {key: ctx[key] for key in ("job_id", "job_try") if key in ctx}
        trace_id_value = kwargs.pop(TRACE_ID_KWARG, None)
        trace_id = trace_id_value if isinstance(trace_id_value, str) else None
        start = time.perf_counter()
        status = "success"
        try:
            async with wide_task(
                task_name,
                trace_id=trace_id,
                **job_context,
            ):
                return await func(*args, **kwargs)
        except Exception:
            status = "error"
            raise
        finally:
            elapsed = time.perf_counter() - start
            TASK_DURATION_SECONDS.labels(task_name=task_name, status=status).observe(elapsed)
            TASK_TOTAL.labels(task_name=task_name, status=status).inc()

    return wrapper
