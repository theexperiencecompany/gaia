"""Turn latency histograms — the benchmark source of truth (p50/p95/p99, alerts).

PostHog carries the same timings as event props for segmentation; wide events
carry per-turn fields for Loki deep-dives.

Label discipline: low-cardinality labels only. Never user/conversation/stream/
task ids on collectors — those go on log.set() + PostHog props. tool_name must
come from a bounded catalog: built-in tool names, Composio action slugs, or
tools collapsed to tool_name="mcp" (any tool exposing a tool_connector, i.e.
the MCP adapter). Same rule for subagent_id: the registry integration id,
never the per-call row uuid.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
import contextlib
from enum import StrEnum
import time
from typing import Final

from prometheus_client import Counter, Histogram

from app.constants.chat import ConversationSource
from app.services.storage.metrics import _register_once
from app.services.turn_timings import StepReport, Store, StoreTally, TurnPhase, TurnStep
from shared.py.wide_events import log

#: Sub-second steps where the overhead work moves things, edges at the 5s and
#: 10s alert thresholds, and a 60s top so the p99 is not clamped at 30s.
_TTFT_BUCKETS: Final[tuple[float, ...]] = (
    0.1,
    0.25,
    0.5,
    0.75,
    1,
    1.5,
    2,
    3,
    4,
    5,
    6,
    8,
    10,
    15,
    20,
    30,
    60,
)

#: Overhead is budgeted at 120ms p50 / 200ms p90, so resolution sits there.
#: Round trips per turn phase: a handful when cached, dozens when a step fans out.
_STORE_CALL_BUCKETS: Final[tuple[float, ...]] = (0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89)

_OVERHEAD_BUCKETS: Final[tuple[float, ...]] = (
    0.01,
    0.02,
    0.04,
    0.06,
    0.08,
    0.1,
    0.12,
    0.15,
    0.2,
    0.3,
    0.5,
    1,
    2,
    5,
)

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
        labelnames=("source", "status"),
        buckets=_TTFT_BUCKETS,
    ),
)

_CHAT_E2E_ACK_SECONDS = _register_once(
    "chat_e2e_ack_seconds",
    lambda: Histogram(
        name="chat_e2e_ack_seconds",
        documentation="User message to its settled reply per chat turn in seconds",
        labelnames=("source", "status"),
        buckets=_TURN_BUCKETS,
    ),
)

_TURN_STEP_SECONDS = _register_once(
    "turn_step_seconds",
    lambda: Histogram(
        name="turn_step_seconds",
        documentation=(
            "Chat turn ingress/prep time by named step; step=other is the phase's "
            "time no named step covers, so a phase's steps sum to it"
        ),
        labelnames=("source", "phase", "step"),
        buckets=_OVERHEAD_BUCKETS,
    ),
)

_TURN_STORE_CALLS = _register_once(
    "turn_store_calls",
    lambda: Histogram(
        name="turn_store_calls",
        documentation="Store round trips one chat turn made in a phase, by store",
        labelnames=("source", "phase", "store"),
        buckets=_STORE_CALL_BUCKETS,
    ),
)

_TURN_STORE_SECONDS = _register_once(
    "turn_store_seconds",
    lambda: Histogram(
        name="turn_store_seconds",
        documentation="Wall time one chat turn spent on store round trips in a phase, by store",
        labelnames=("source", "phase", "store"),
        buckets=_OVERHEAD_BUCKETS,
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
        documentation="Chat turns by the surface that sent them and how they ended",
        labelnames=("source", "status"),
    ),
)

_CONTEXT_SECTION_BUDGET_EXCEEDED = _register_once(
    "context_section_budget_exceeded",
    lambda: Counter(
        name="context_section_budget_exceeded",
        documentation="Context sections that ran past their budget and rendered empty, by section",
        labelnames=("section",),
    ),
)

_MEMORY_FAST_RECALL_SEMANTIC_MISSED = _register_once(
    "memory_fast_recall_semantic_missed",
    lambda: Counter(
        name="memory_fast_recall_semantic_missed",
        documentation="Comms fast-lane turns answered without semantic hits: the embedding was late",
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

_TRIGGER_GATE_DECISION_TOTAL = _register_once(
    "trigger_gate_decision_total",
    lambda: Counter(
        name="trigger_gate_decision_total",
        documentation=(
            "Lifetime trigger gate decisions; jev_error, jev_timeout and jev_malformed over "
            "every reason that asked JEV is the gate's JEV error rate"
        ),
        labelnames=("owner", "outcome", "reason"),
    ),
)

_REACTION_ACK_DECISION_TOTAL = _register_once(
    "reaction_ack_decision_total",
    lambda: Counter(
        name="reaction_ack_decision_total",
        documentation=(
            "Lifetime instant reaction decisions; jev_error, jev_timeout and jev_malformed over every "
            "reason that asked JEV is the instant reaction's JEV error rate"
        ),
        labelnames=("outcome", "reason"),
    ),
)

_HIL_PAUSE_TOTAL = _register_once(
    "hil_pause_total",
    lambda: Counter(
        name="hil_pause_total",
        documentation="Lifetime HIL pause observations",
    ),
)


class ChatTurnStatus(StrEnum):
    """How a chat turn ended."""

    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"


def _bool_label(value: bool | str) -> str:
    return value if isinstance(value, str) else ("true" if value else "false")


# The ARQ worker mirrors these onto its own registry (app/workers/metrics.py) so
# samples from worker-run paths (HIL sweep, re-dispatched and workflow-triggered
# executor runs) are served rather than landing on an unscraped default registry.
ALL_COLLECTORS: Final[tuple[Histogram | Counter, ...]] = (
    _CHAT_TTFT_SECONDS,
    _CHAT_E2E_ACK_SECONDS,
    _LLM_TTFT_SECONDS,
    _COMMS_GRAPH_SECONDS,
    _CONTEXT_ASSEMBLE_SECONDS,
    _CONTEXT_SECTION_BUDGET_EXCEEDED,
    _MEMORY_FAST_RECALL_SEMANTIC_MISSED,
    _EXECUTOR_QUEUE_WAIT_SECONDS,
    _EXECUTOR_TTFT_SECONDS,
    _EXECUTOR_ACTIVE_SECONDS,
    _EXECUTOR_E2E_SECONDS,
    _TOOL_CALL_SECONDS,
    _SUBAGENT_RUN_SECONDS,
    _HIL_USER_WAIT_SECONDS,
    _HIL_DISPATCH_LAG_SECONDS,
    _TRANSPORT_REDIS_PUBLISH_SECONDS,
    _SSE_DELIVERY_SECONDS,
    _LLM_CALL_SECONDS,
    _GRAPH_NODE_SECONDS,
    _CHAT_TURN_TOTAL,
    _EXECUTOR_RUN_TOTAL,
    _TOOL_CALL_TOTAL,
    _TRIGGER_GATE_DECISION_TOTAL,
    _REACTION_ACK_DECISION_TOTAL,
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


def create_chat_turn_series() -> None:
    """Create every chat-turn series at zero, so the first failed turn is an increase."""
    for source in ConversationSource:
        for status in ChatTurnStatus:
            _CHAT_TURN_TOTAL.labels(source.value, status.value)


@contextlib.contextmanager
def span() -> Iterator[Callable[[], float]]:
    """Time one span, yielding an elapsed() reader in seconds."""
    start = time.perf_counter()
    yield lambda: time.perf_counter() - start


def observe_chat_ttft(
    seconds: float, *, source: ConversationSource, status: ChatTurnStatus
) -> None:
    """Record user message to the first text of the reply that settled it."""
    _observe(_CHAT_TTFT_SECONDS, seconds, source=source.value, status=status.value)


def observe_chat_e2e_ack(
    seconds: float, *, source: ConversationSource, status: ChatTurnStatus
) -> None:
    """Record user message to the settle of the reply that answered it."""
    _observe(_CHAT_E2E_ACK_SECONDS, seconds, source=source.value, status=status.value)


def observe_chat_turn_total(*, source: ConversationSource, status: ChatTurnStatus) -> None:
    """Count one chat turn by the surface that sent it and how it ended."""
    _inc(_CHAT_TURN_TOTAL, source=source.value, status=status.value)


def observe_context_section_budget_exceeded(*, section: str) -> None:
    """Count a context section that rendered empty because it ran past its budget."""
    _inc(_CONTEXT_SECTION_BUDGET_EXCEEDED, section=section)


def observe_fast_recall_semantic_missed() -> None:
    """Count a fast-lane turn that answered without semantic hits because the embedding was late."""
    _inc(_MEMORY_FAST_RECALL_SEMANTIC_MISSED)


def observe_turn_steps(
    reports: Mapping[TurnPhase, Mapping[TurnStep, StepReport]], *, source: str
) -> None:
    """Record each phase's step times, and its round trips and time per store (zero included)."""
    for phase, steps in reports.items():
        totals = {store: StoreTally() for store in Store}
        for step, report in steps.items():
            _observe(
                _TURN_STEP_SECONDS,
                report.seconds,
                source=source,
                phase=phase.value,
                step=step.value,
            )
            for store, tally in report.stores.items():
                totals[store].calls += tally.calls
                totals[store].seconds += tally.seconds
        for store, tally in totals.items():
            _observe(
                _TURN_STORE_CALLS, tally.calls, source=source, phase=phase.value, store=store.value
            )
            _observe(
                _TURN_STORE_SECONDS,
                tally.seconds,
                source=source,
                phase=phase.value,
                store=store.value,
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


def observe_trigger_gate_decision(*, owner: str, outcome: str, reason: str) -> None:
    """Count one trigger gate decision."""
    _inc(_TRIGGER_GATE_DECISION_TOTAL, owner=owner, outcome=outcome, reason=reason)


def observe_reaction_ack_decision(*, outcome: str, reason: str) -> None:
    """Count one instant reaction decision."""
    _inc(_REACTION_ACK_DECISION_TOTAL, outcome=outcome, reason=reason)


def observe_hil_pause() -> None:
    """Increment the lifetime HIL-pause counter."""
    _inc(_HIL_PAUSE_TOTAL)


def observe_hil_user_wait(seconds: float) -> None:
    """Record HIL approval decided_at minus created_at."""
    _observe(_HIL_USER_WAIT_SECONDS, seconds)


def observe_hil_dispatch_lag(seconds: float) -> None:
    """Record HIL approval resumed_at minus decided_at."""
    _observe(_HIL_DISPATCH_LAG_SECONDS, seconds)


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
    "ChatTurnStatus",
    "create_chat_turn_series",
    "observe_chat_e2e_ack",
    "observe_chat_ttft",
    "observe_chat_turn_total",
    "observe_comms_graph",
    "observe_context_assemble",
    "observe_context_section_budget_exceeded",
    "observe_fast_recall_semantic_missed",
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
    "observe_reaction_ack_decision",
    "observe_sse_delivery",
    "observe_subagent_run",
    "observe_tool_call",
    "observe_turn_steps",
    "observe_trigger_gate_decision",
    "observe_transport_redis_publish",
    "span",
]
