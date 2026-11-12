"""Unit tests for turn latency histograms."""

from prometheus_client import REGISTRY

from app.services.latency_metrics import observe_trigger_gate_decision


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

    before = REGISTRY.get_sample_value("transport_redis_publish_seconds_count", {}) or 0.0
    m.observe_transport_redis_publish(0.01)
    assert REGISTRY.get_sample_value("transport_redis_publish_seconds_count", {}) == before + 1


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
