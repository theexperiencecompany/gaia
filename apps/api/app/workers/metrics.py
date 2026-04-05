"""
Prometheus metrics for the ARQ background worker.

Exposes a histogram of task durations and a counter of task outcomes so the
`arq-worker` dashboard can show real latency percentiles instead of scraping logs.

A standalone HTTP server is started in `startup()` on the port configured via
``ARQ_METRICS_PORT`` (default 9100). Prometheus scrapes this endpoint via the
``arq_worker`` job in ``prometheus.yml``.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Coroutine, TypeVar

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server

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
            TASK_DURATION_SECONDS.labels(task_name=task_name, status=status).observe(
                elapsed
            )
            TASK_TOTAL.labels(task_name=task_name, status=status).inc()

    return wrapper


def start_metrics_server(port: int) -> None:
    """Start the Prometheus metrics HTTP server on the given port."""
    start_http_server(port, registry=REGISTRY)
