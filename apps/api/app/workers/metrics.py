"""
Prometheus metrics for the ARQ background worker.

Exposes a histogram of task durations and a counter of task outcomes so the
`arq-worker` dashboard can show real latency percentiles instead of scraping logs.

A standalone HTTP server is started in `startup()` on the port configured via
``ARQ_METRICS_PORT`` (default 9100). Prometheus scrapes this endpoint via the
``arq_worker`` job in ``prometheus.yml``.

This module also re-registers the FsOps Prometheus collectors (declared on
the default registry in ``app/services/storage/metrics.py``) onto the worker's
custom ``REGISTRY`` so the same ``fs_op_*`` metric families show up at
``/metrics`` for the worker process too.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
import functools
import time
from typing import Any, TypeVar

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server

from app.services.storage.metrics import (
    _FS_OP_BYTES_TOTAL,
    _FS_OP_DURATION_SECONDS,
    _FS_OP_IN_FLIGHT,
    _FS_OP_LAST_SEEN,
    _FS_OP_TOTAL,
    _SANDBOX_POOL_SIZE,
)

T = TypeVar("T")

REGISTRY = CollectorRegistry()

TASK_DURATION_SECONDS = Histogram(
    "arq_task_duration_seconds",
    "ARQ background task duration in seconds",
    labelnames=("task_name", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
    registry=REGISTRY,
)

TASK_TOTAL = Counter(
    "arq_task_total",
    "Total number of ARQ tasks executed",
    labelnames=("task_name", "status"),
    registry=REGISTRY,
)

# Cross-register the FsOps collectors onto this worker registry so the worker
# process's /metrics surface mirrors the API's. The same collector instances
# are registered on both registries — observations from `record_fs_op` flow
# into one underlying state and surface on both /metrics endpoints.
#
# The `tool_bash_exit_code_total` counter is NOT mirrored here — bash_tool is
# only reachable from API request paths, not ARQ tasks, so it would always be
# zero on the worker side.
for _collector in (
    _FS_OP_DURATION_SECONDS,
    _FS_OP_BYTES_TOTAL,
    _FS_OP_TOTAL,
    _FS_OP_LAST_SEEN,
    _FS_OP_IN_FLIGHT,
    _SANDBOX_POOL_SIZE,
):
    try:
        REGISTRY.register(_collector)
    except ValueError:
        # Already registered on this registry (re-import under reload).
        pass


def instrument_task(
    func: Callable[..., Coroutine[Any, Any, T]],
) -> Callable[..., Coroutine[Any, Any, T]]:
    """Wrap an ARQ task coroutine to record duration and outcome metrics."""

    task_name = func.__name__

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        start = time.perf_counter()
        status = "success"
        try:
            return await func(*args, **kwargs)
        except Exception:
            status = "error"
            raise
        finally:
            elapsed = time.perf_counter() - start
            TASK_DURATION_SECONDS.labels(task_name=task_name, status=status).observe(elapsed)
            TASK_TOTAL.labels(task_name=task_name, status=status).inc()

    return wrapper


def start_metrics_server(port: int) -> None:
    """Start the Prometheus metrics HTTP server on the given port."""
    start_http_server(port, registry=REGISTRY)
