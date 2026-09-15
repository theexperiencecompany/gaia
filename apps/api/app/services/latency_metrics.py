"""Turn latency histograms — the benchmark source of truth (p50/p95/p99, alerts).

PostHog carries the same timings as event props for segmentation; wide events
carry per-turn fields for Loki deep-dives.

Label discipline: low-cardinality labels only. Never user/conversation/stream/
task ids on collectors — those go on ``log.set()`` + PostHog props.
``tool_name`` must come from a bounded catalog: built-in tool names, Composio
action slugs, or tools collapsed to ``tool_name="mcp"`` (any tool exposing a
``tool_connector``, i.e. the MCP adapter). Same rule for ``subagent_id``: the
registry integration id, never the per-call row uuid.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import contextlib
import time
from typing import Final

from prometheus_client import Counter, Histogram

from app.services.storage.metrics import _register_once
from shared.py.wide_events import log

_TTFT_BUCKETS: Final[tuple[float, ...]] = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

_TURN_BUCKETS: Final[tuple[float, ...]] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
    120,
    300,
    600,
)

_CHAT_TTFT_SECONDS = _register_once(
    "chat_ttft_seconds",
    lambda: Histogram(
        name="chat_ttft_seconds",
        documentation="Time to first comms response text per chat turn in seconds",
        labelnames=("source", "voice_mode", "status"),
        buckets=_TTFT_BUCKETS,
    ),
)

_CHAT_E2E_ACK_SECONDS = _register_once(
    "chat_e2e_ack_seconds",
    lambda: Histogram(
        name="chat_e2e_ack_seconds",
        documentation="Request accepted to comms ack complete per chat turn in seconds",
        labelnames=("source", "voice_mode", "delegated", "status"),
        buckets=_TURN_BUCKETS,
    ),
)

_CHAT_E2E_FULL_SECONDS = _register_once(
    "chat_e2e_full_seconds",
    lambda: Histogram(
        name="chat_e2e_full_seconds",
        documentation="Request accepted to stream DONE per chat turn in seconds",
        labelnames=("source", "voice_mode", "delegated", "status"),
        buckets=_TURN_BUCKETS,
    ),
)

_LLM_TTFT_SECONDS = _register_once(
    "llm_ttft_seconds",
    lambda: Histogram(
        name="llm_ttft_seconds",
        documentation="True provider time to first token per streaming LLM call in seconds",
        labelnames=("model", "lane", "agent"),
        buckets=_TTFT_BUCKETS,
    ),
)

_COMMS_GRAPH_SECONDS = _register_once(
    "comms_graph_seconds",
    lambda: Histogram(
        name="comms_graph_seconds",
        documentation="Comms graph streaming run duration in seconds",
        labelnames=("status",),
        buckets=_TURN_BUCKETS,
    ),
)

_CONTEXT_ASSEMBLE_SECONDS = _register_once(
    "context_assemble_seconds",
    lambda: Histogram(
        name="context_assemble_seconds",
        documentation="Context assembly duration by stage in seconds",
        labelnames=("stage",),
        buckets=_TTFT_BUCKETS,
    ),
)

_EXECUTOR_QUEUE_WAIT_SECONDS = _register_once(
    "executor_queue_wait_seconds",
    lambda: Histogram(
        name="executor_queue_wait_seconds",
        documentation="Executor dispatch to run start wait in seconds",
        labelnames=("source", "queued"),
        buckets=_TURN_BUCKETS,
    ),
)

_EXECUTOR_TTFT_SECONDS = _register_once(
    "executor_ttft_seconds",
    lambda: Histogram(
        name="executor_ttft_seconds",
        documentation="Executor dispatch to first tool-data frame in seconds",
        labelnames=("queued",),
        buckets=_TURN_BUCKETS,
    ),
)

_EXECUTOR_ACTIVE_SECONDS = _register_once(
    "executor_active_seconds",
    lambda: Histogram(
        name="executor_active_seconds",
        documentation="Executor active run time excluding HIL pause in seconds",
        labelnames=("status",),
        buckets=_TURN_BUCKETS,
    ),
)

_EXECUTOR_E2E_SECONDS = _register_once(
    "executor_e2e_seconds",
    lambda: Histogram(
        name="executor_e2e_seconds",
        documentation="Executor dispatch to finalize in seconds",
        labelnames=("status", "queued"),
        buckets=_TURN_BUCKETS,
    ),
)

_TOOL_CALL_SECONDS = _register_once(
    "tool_call_seconds",
    lambda: Histogram(
        name="tool_call_seconds",
        documentation="Per tool call duration in seconds",
        labelnames=("tool_name", "status"),
        buckets=_TURN_BUCKETS,
    ),
)

_SUBAGENT_RUN_SECONDS = _register_once(
    "subagent_run_seconds",
    lambda: Histogram(
        name="subagent_run_seconds",
        documentation="Subagent active run time excluding pause in seconds",
        labelnames=("subagent_id", "status"),
        buckets=_TURN_BUCKETS,
    ),
)

_HIL_USER_WAIT_SECONDS = _register_once(
    "hil_user_wait_seconds",
    lambda: Histogram(
        name="hil_user_wait_seconds",
        documentation="HIL approval decided_at minus created_at in seconds",
        labelnames=(),
        buckets=_TURN_BUCKETS,
    ),
)

_HIL_DISPATCH_LAG_SECONDS = _register_once(
    "hil_dispatch_lag_seconds",
    lambda: Histogram(
        name="hil_dispatch_lag_seconds",
        documentation="HIL approval resumed_at minus decided_at in seconds",
        labelnames=(),
        buckets=_TTFT_BUCKETS,
    ),
)

_DELIVERY_NARRATION_SECONDS = _register_once(
    "delivery_narration_seconds",
    lambda: Histogram(
        name="delivery_narration_seconds",
        documentation="Executor result narration duration in seconds",
        labelnames=("status",),
        buckets=_TURN_BUCKETS,
    ),
)

_DELIVERY_PERSIST_SECONDS = _register_once(
    "delivery_persist_seconds",
    lambda: Histogram(
        name="delivery_persist_seconds",
        documentation="Result persistence write duration in seconds",
        labelnames=("op",),
        buckets=_TTFT_BUCKETS,
    ),
)

_TRANSPORT_REDIS_PUBLISH_SECONDS = _register_once(
    "transport_redis_publish_seconds",
    lambda: Histogram(
        name="transport_redis_publish_seconds",
        documentation="Redis stream publish duration in seconds",
        labelnames=(),
        buckets=_TTFT_BUCKETS,
    ),
)

_SSE_DELIVERY_SECONDS = _register_once(
    "sse_delivery_seconds",
    lambda: Histogram(
        name="sse_delivery_seconds",
        documentation="SSE subscribe to close delivery duration in seconds",
        labelnames=("status",),
        buckets=_TURN_BUCKETS,
    ),
)

_LLM_CALL_SECONDS = _register_once(
    "llm_call_seconds",
    lambda: Histogram(
        name="llm_call_seconds",
        documentation="Provider LLM call duration in seconds by model and agent",
        labelnames=("model", "agent"),
        buckets=_TURN_BUCKETS,
    ),
)

_GRAPH_NODE_SECONDS = _register_once(
    "graph_node_seconds",
    lambda: Histogram(
        name="graph_node_seconds",
        documentation="Graph node duration in seconds by node and agent",
        labelnames=("node", "agent"),
        buckets=_TTFT_BUCKETS,
    ),
)

_CHAT_TURN_TOTAL = _register_once(
    "chat_turn_total",
    lambda: Counter(
        name="chat_turn_total",
        documentation="Lifetime chat turn observations",
        labelnames=("source", "delegated", "status"),
    ),
)

_EXECUTOR_RUN_TOTAL = _register_once(
    "executor_run_total",
    lambda: Counter(
        name="executor_run_total",
        documentation="Lifetime executor run observations",
        labelnames=("status", "queued"),
    ),
)

_TOOL_CALL_TOTAL = _register_once(
    "tool_call_total",
    lambda: Counter(
        name="tool_call_total",
        documentation="Lifetime tool call observations",
        labelnames=("tool_name", "status"),
    ),
)

_HIL_PAUSE_TOTAL = _register_once(
    "hil_pause_total",
    lambda: Counter(
        name="hil_pause_total",
        documentation="Lifetime HIL pause observations",
    ),
)


def _bool_label(value: bool | str) -> str:
    return value if isinstance(value, str) else ("true" if value else "false")


# Every collector this module owns. The ARQ worker mirrors these onto its own
# registry (app/workers/metrics.py) so samples emitted inside worker-run paths —
# the HIL sweep, re-dispatched and workflow-triggered executor runs — are served
# rather than landing on a default registry nothing scrapes.
ALL_COLLECTORS: Final[tuple[Histogram | Counter, ...]] = (
    _CHAT_TTFT_SECONDS,
    _CHAT_E2E_ACK_SECONDS,
    _CHAT_E2E_FULL_SECONDS,
    _LLM_TTFT_SECONDS,
    _COMMS_GRAPH_SECONDS,
    _CONTEXT_ASSEMBLE_SECONDS,
    _EXECUTOR_QUEUE_WAIT_SECONDS,
    _EXECUTOR_TTFT_SECONDS,
    _EXECUTOR_ACTIVE_SECONDS,
    _EXECUTOR_E2E_SECONDS,
    _TOOL_CALL_SECONDS,
    _SUBAGENT_RUN_SECONDS,
    _HIL_USER_WAIT_SECONDS,
    _HIL_DISPATCH_LAG_SECONDS,
    _DELIVERY_NARRATION_SECONDS,
    _DELIVERY_PERSIST_SECONDS,
    _TRANSPORT_REDIS_PUBLISH_SECONDS,
    _SSE_DELIVERY_SECONDS,
    _LLM_CALL_SECONDS,
    _GRAPH_NODE_SECONDS,
    _CHAT_TURN_TOTAL,
    _EXECUTOR_RUN_TOTAL,
    _TOOL_CALL_TOTAL,
    _HIL_PAUSE_TOTAL,
)


def _observe(histogram: Histogram, amount: float, **labels: str) -> None:
    try:
        if labels:
            histogram.labels(**labels).observe(amount)
        else:
            histogram.observe(amount)  # .labels() raises on a labelless collector
    except Exception as e:  # metrics must never break the turn they measure
        log.warning(
            "[metrics] latency observe failed",
            error=str(e),
            error_type=type(e).__name__,
            labels=labels,
        )


def _inc(counter: Counter, **labels: str) -> None:
    try:
        if labels:
            counter.labels(**labels).inc()
        else:
            counter.inc()
    except Exception as e:  # metrics must never break the turn they measure
        log.warning(
            "[metrics] latency counter inc failed",
            error=str(e),
            error_type=type(e).__name__,
            labels=labels,
        )


@contextlib.contextmanager
def span() -> Iterator[Callable[[], float]]:
    """Time one span, yielding an ``elapsed()`` reader in seconds."""
    start = time.perf_counter()
    yield lambda: time.perf_counter() - start


def observe_chat_ttft(seconds: float, *, source: str, voice_mode: bool, status: str) -> None:
    """Record time to first comms response text for a chat turn."""
    _observe(
        _CHAT_TTFT_SECONDS,
        seconds,
        source=source,
        voice_mode=_bool_label(voice_mode),
        status=status,
    )


def observe_chat_e2e_ack(
    seconds: float, *, source: str, voice_mode: bool, delegated: bool, status: str
) -> None:
    """Record request-accepted to comms-ack-complete for a chat turn."""
    _observe(
        _CHAT_E2E_ACK_SECONDS,
        seconds,
        source=source,
        voice_mode=_bool_label(voice_mode),
        delegated=_bool_label(delegated),
        status=status,
    )


def observe_chat_e2e_full(
    seconds: float, *, source: str, voice_mode: bool, delegated: bool, status: str
) -> None:
    """Record request-accepted to stream-DONE for a chat turn."""
    _observe(
        _CHAT_E2E_FULL_SECONDS,
        seconds,
        source=source,
        voice_mode=_bool_label(voice_mode),
        delegated=_bool_label(delegated),
        status=status,
    )


def observe_chat_turn_total(*, source: str, delegated: bool, status: str) -> None:
    """Increment the lifetime chat-turn counter."""
    _inc(
        _CHAT_TURN_TOTAL,
        source=source,
        delegated=_bool_label(delegated),
        status=status,
    )


def observe_llm_ttft(seconds: float, *, model: str, lane: str, agent: str) -> None:
    """Record true provider time to first token for a streaming LLM call."""
    _observe(_LLM_TTFT_SECONDS, seconds, model=model, lane=lane, agent=agent)


def observe_comms_graph(seconds: float, *, status: str) -> None:
    """Record the comms graph streaming run duration."""
    _observe(_COMMS_GRAPH_SECONDS, seconds, status=status)


def observe_context_assemble(seconds: float, *, stage: str) -> None:
    """Record context assembly duration for one stage."""
    _observe(_CONTEXT_ASSEMBLE_SECONDS, seconds, stage=stage)


def observe_executor_queue_wait(seconds: float, *, source: str, queued: bool) -> None:
    """Record executor dispatch-to-run-start wait."""
    _observe(_EXECUTOR_QUEUE_WAIT_SECONDS, seconds, source=source, queued=_bool_label(queued))


def observe_executor_ttft(seconds: float, *, queued: bool) -> None:
    """Record executor dispatch to first tool-data frame."""
    _observe(_EXECUTOR_TTFT_SECONDS, seconds, queued=_bool_label(queued))


def observe_executor_active(seconds: float, *, status: str) -> None:
    """Record executor active run time, excluding HIL pause."""
    _observe(_EXECUTOR_ACTIVE_SECONDS, seconds, status=status)


def observe_executor_e2e(seconds: float, *, status: str, queued: bool) -> None:
    """Record executor dispatch to finalize."""
    _observe(
        _EXECUTOR_E2E_SECONDS,
        seconds,
        status=status,
        queued=_bool_label(queued),
    )


def observe_executor_run_total(*, status: str, queued: bool) -> None:
    """Increment the lifetime executor-run counter."""
    _inc(_EXECUTOR_RUN_TOTAL, status=status, queued=_bool_label(queued))


def observe_tool_call(seconds: float, *, tool_name: str, status: str) -> None:
    """Record one tool call's duration and count it."""
    _observe(_TOOL_CALL_SECONDS, seconds, tool_name=tool_name, status=status)
    _inc(_TOOL_CALL_TOTAL, tool_name=tool_name, status=status)


def observe_subagent_run(seconds: float, *, subagent_id: str, status: str) -> None:
    """Record subagent active run time, excluding pause."""
    _observe(_SUBAGENT_RUN_SECONDS, seconds, subagent_id=subagent_id, status=status)


def observe_hil_pause() -> None:
    """Increment the lifetime HIL-pause counter."""
    _inc(_HIL_PAUSE_TOTAL)


def observe_hil_user_wait(seconds: float) -> None:
    """Record HIL approval decided_at minus created_at."""
    _observe(_HIL_USER_WAIT_SECONDS, seconds)


def observe_hil_dispatch_lag(seconds: float) -> None:
    """Record HIL approval resumed_at minus decided_at."""
    _observe(_HIL_DISPATCH_LAG_SECONDS, seconds)


def observe_delivery_narration(seconds: float, *, status: str) -> None:
    """Record executor result narration duration."""
    _observe(_DELIVERY_NARRATION_SECONDS, seconds, status=status)


def observe_delivery_persist(seconds: float, *, op: str) -> None:
    """Record result persistence write duration for one op."""
    _observe(_DELIVERY_PERSIST_SECONDS, seconds, op=op)


def observe_transport_redis_publish(seconds: float) -> None:
    """Record Redis stream publish duration."""
    _observe(_TRANSPORT_REDIS_PUBLISH_SECONDS, seconds)


def observe_sse_delivery(seconds: float, *, status: str) -> None:
    """Record SSE subscribe-to-close delivery duration."""
    _observe(_SSE_DELIVERY_SECONDS, seconds, status=status)


def observe_llm_call(seconds: float, *, model: str, agent: str) -> None:
    """Record total provider LLM call duration."""
    _observe(_LLM_CALL_SECONDS, seconds, model=model, agent=agent)


def observe_graph_node(seconds: float, *, node: str, agent: str) -> None:
    """Record one graph node's duration."""
    _observe(_GRAPH_NODE_SECONDS, seconds, node=node, agent=agent)


__all__ = [
    "ALL_COLLECTORS",
    "observe_chat_e2e_ack",
    "observe_chat_e2e_full",
    "observe_chat_ttft",
    "observe_chat_turn_total",
    "observe_comms_graph",
    "observe_context_assemble",
    "observe_delivery_narration",
    "observe_delivery_persist",
    "observe_executor_active",
    "observe_executor_e2e",
    "observe_executor_queue_wait",
    "observe_executor_run_total",
    "observe_executor_ttft",
    "observe_graph_node",
    "observe_hil_dispatch_lag",
    "observe_hil_pause",
    "observe_hil_user_wait",
    "observe_llm_call",
    "observe_llm_ttft",
    "observe_sse_delivery",
    "observe_subagent_run",
    "observe_tool_call",
    "observe_transport_redis_publish",
    "span",
]
