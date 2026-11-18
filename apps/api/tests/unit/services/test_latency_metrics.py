"""Unit tests for turn latency histograms."""

from prometheus_client import REGISTRY
import pytest

from app.services.latency_metrics import (
    observe_context_section_budget_exceeded,
    observe_fast_recall_semantic_missed,
    observe_trigger_gate_decision,
    observe_turn_overhead,
)
from app.services.turn_clock import TurnOverhead, TurnPath


def test_histograms_registered_and_observe():
    from app.services import latency_metrics as m

    m.observe_chat_ttft(0.5, source="web", voice_mode=False, status="success")
    assert "chat_ttft_seconds" in REGISTRY._names_to_collectors


def test_span_yields_elapsed_seconds():
    from app.services import latency_metrics as m

    with m.span() as elapsed:
        pass
    assert elapsed() >= 0.0


def test_llm_call_and_graph_node_observe():
    from prometheus_client import REGISTRY

    from app.services import latency_metrics as m

    m.observe_llm_call(1.5, model="test-model", agent="test-agent")
    assert (
        REGISTRY.get_sample_value(
            "llm_call_seconds_count", {"model": "test-model", "agent": "test-agent"}
        )
        == 1.0
    )
    m.observe_graph_node(0.05, node="test-node", agent="test-agent")
    assert (
        REGISTRY.get_sample_value(
            "graph_node_seconds_count", {"node": "test-node", "agent": "test-agent"}
        )
        == 1.0
    )


def test_labelless_histograms_observe_directly():
    """Collectors with no label names take observations without .labels()."""
    from prometheus_client import REGISTRY

    from app.services import latency_metrics as m

    before = REGISTRY.get_sample_value("hil_user_wait_seconds_count", {}) or 0.0
    m.observe_hil_user_wait(1.0)
    m.observe_hil_dispatch_lag(0.5)
    m.observe_transport_redis_publish(0.01)
    assert REGISTRY.get_sample_value("hil_user_wait_seconds_count", {}) == before + 1


def test_hil_pause_total_counts_pauses_not_decisions():
    """hil_pause_total fires when a pause is created, never on a decision; observe_hil_user_wait leaves it untouched."""
    from prometheus_client import REGISTRY

    from app.services import latency_metrics as m

    before = REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0
    m.observe_hil_pause()
    assert REGISTRY.get_sample_value("hil_pause_total", {}) == before + 1
    # A decision must NOT bump the pause counter.
    m.observe_hil_user_wait(1.0)
    assert REGISTRY.get_sample_value("hil_pause_total", {}) == before + 1


def test_tool_call_histogram_resolves_a_call_that_ran_to_the_timeout():
    """The generic guard is 120s and handoff/subagent/executor calls are exempt, so buckets must reach it."""
    from prometheus_client import REGISTRY

    from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS
    from app.services import latency_metrics as m

    labels = {"tool_name": "bucket-probe", "status": "success"}
    inf_before = (
        REGISTRY.get_sample_value("tool_call_seconds_bucket", {**labels, "le": "+Inf"}) or 0.0
    )
    resolved_before = (
        REGISTRY.get_sample_value("tool_call_seconds_bucket", {**labels, "le": "300.0"}) or 0.0
    )
    m.observe_tool_call(TOOL_EXECUTION_TIMEOUT_SECONDS, tool_name="bucket-probe", status="success")
    assert (
        REGISTRY.get_sample_value("tool_call_seconds_bucket", {**labels, "le": "+Inf"})
        == inf_before + 1
    )
    assert (
        REGISTRY.get_sample_value("tool_call_seconds_bucket", {**labels, "le": "300.0"})
        == resolved_before + 1
    )


def test_a_trigger_gate_decision_is_counted_under_its_labels() -> None:
    labels = {"owner": "workflow", "outcome": "run", "reason": "jev_timeout"}
    before = REGISTRY.get_sample_value("trigger_gate_decision_total", labels) or 0.0

    observe_trigger_gate_decision(owner="workflow", outcome="run", reason="jev_timeout")

    assert REGISTRY.get_sample_value("trigger_gate_decision_total", labels) == before + 1


def test_a_turns_overhead_is_observed_per_stage_with_total_the_sum_of_ours() -> None:
    overhead = TurnOverhead(
        ingress=0.01, prep=0.03, provider_ttft=1.5, egress=0.02, path=TurnPath.TOOL_LOOP
    )

    def sample(stage: str, suffix: str) -> float:
        labels = {"source": "metrics-test", "stage": stage, "path": "tool_loop"}
        return REGISTRY.get_sample_value(f"turn_overhead_seconds_{suffix}", labels) or 0.0

    stages = ("ingress", "prep", "egress", "total")
    before = {stage: (sample(stage, "count"), sample(stage, "sum")) for stage in stages}

    observe_turn_overhead(overhead, source="metrics-test")

    expected = {"ingress": 0.01, "prep": 0.03, "egress": 0.02, "total": 0.06}
    for stage in stages:
        count, total = before[stage]
        assert sample(stage, "count") == count + 1
        assert sample(stage, "sum") == pytest.approx(total + expected[stage])


def test_a_section_past_its_budget_is_counted_under_its_section() -> None:
    labels = {"section": "metrics_test_section"}
    before = REGISTRY.get_sample_value("context_section_budget_exceeded_total", labels) or 0.0

    observe_context_section_budget_exceeded(section="metrics_test_section")

    assert REGISTRY.get_sample_value("context_section_budget_exceeded_total", labels) == before + 1


def test_a_late_fast_lane_embedding_is_counted() -> None:
    before = REGISTRY.get_sample_value("memory_fast_recall_semantic_missed_total") or 0.0

    observe_fast_recall_semantic_missed()

    assert REGISTRY.get_sample_value("memory_fast_recall_semantic_missed_total") == before + 1
