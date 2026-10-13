"""Unit tests for turn latency histograms."""

from prometheus_client import REGISTRY


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
