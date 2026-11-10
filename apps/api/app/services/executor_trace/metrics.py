"""Prometheus counter for run-trace writes that failed, the signal that a trace has a gap.

The trace is best-effort: a failed write never fails the user's tool call, so the
counter and the error log are the only places a missing record shows up.
"""

from __future__ import annotations

from enum import StrEnum

from prometheus_client import Counter

from app.services.storage.metrics import _register_once


class TraceWrite(StrEnum):
    """The trace write that failed; a closed label set."""

    RUN_START = "run_start"
    RUN_END = "run_end"
    CALL = "call"


EXECUTOR_TRACE_WRITE_FAILED_TOTAL = _register_once(
    "gaia_executor_trace_write_failed_total",
    lambda: Counter(
        name="gaia_executor_trace_write_failed_total",
        documentation="Executor run-trace writes that failed, by which write",
        labelnames=("write",),
    ),
)


def count_trace_write_failed(write: TraceWrite) -> None:
    """Count one failed trace write."""
    EXECUTOR_TRACE_WRITE_FAILED_TOTAL.labels(write.value).inc()
