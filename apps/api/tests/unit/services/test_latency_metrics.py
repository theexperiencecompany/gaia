"""Unit tests for turn latency histograms."""

from prometheus_client import REGISTRY

from app.constants.chat import ConversationSource
from app.services.latency_metrics import (
    observe_context_section_budget_exceeded,
    observe_fast_recall_semantic_missed,
    observe_reaction_ack_decision,
    observe_trigger_gate_decision,
)


def test_histograms_registered_and_observe():
    from app.services import latency_metrics as m

    m.observe_chat_ttft(0.5, source=ConversationSource.WEB, status=m.ChatTurnStatus.OK)
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


def test_a_reaction_ack_decision_is_counted_under_its_labels() -> None:
    labels = {"outcome": "none", "reason": "jev_timeout"}
    before = REGISTRY.get_sample_value("reaction_ack_decision_total", labels) or 0.0

    observe_reaction_ack_decision(outcome="none", reason="jev_timeout")

    assert REGISTRY.get_sample_value("reaction_ack_decision_total", labels) == before + 1


def test_a_section_past_its_budget_is_counted_under_its_section() -> None:
    labels = {"section": "metrics_test_section"}
    before = REGISTRY.get_sample_value("context_section_budget_exceeded_total", labels) or 0.0

    observe_context_section_budget_exceeded(section="metrics_test_section")

    assert REGISTRY.get_sample_value("context_section_budget_exceeded_total", labels) == before + 1


def test_a_late_fast_lane_embedding_is_counted() -> None:
    before = REGISTRY.get_sample_value("memory_fast_recall_semantic_missed_total") or 0.0

    observe_fast_recall_semantic_missed()

    assert REGISTRY.get_sample_value("memory_fast_recall_semantic_missed_total") == before + 1
