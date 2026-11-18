"""Every latency collector is mirrored onto the ARQ worker's own registry.

The worker serves its own Prometheus registry on ARQ_METRICS_PORT, so a collector
registered only on the default one is invisible for everything the worker runs:
the HIL sweep's timeout path, sweep re-dispatched executor runs, and
reminder/workflow-triggered runs.
"""

from app.services import latency_metrics
from app.services.briefing.metrics import create_brief_run_series
from app.services.links.metrics import LinkMintOutcome, create_link_mint_series
from app.workers.metrics import REGISTRY as WORKER_REGISTRY


def test_every_latency_collector_is_served_by_the_worker_registry() -> None:
    names = set(WORKER_REGISTRY._names_to_collectors)
    missing = [
        collector._name
        for collector in latency_metrics.ALL_COLLECTORS
        if collector._name not in names
    ]
    assert missing == []
    assert "hil_user_wait_seconds" in names
    assert "executor_e2e_seconds" in names


def test_every_briefing_run_series_is_served_by_the_worker_before_its_first_run() -> None:
    create_brief_run_series()

    for kind in ("daily", "weekly"):
        labels = {"kind": kind, "outcome": "failed"}
        assert WORKER_REGISTRY.get_sample_value("gaia_brief_run_total", labels) is not None


def test_the_link_mint_failure_series_is_served_by_the_worker_before_its_first_mint() -> None:
    """Briefs and workflow results mint their links on the worker; the alert reads the failed series."""
    create_link_mint_series()

    outcomes = {
        sample.labels["outcome"]
        for family in WORKER_REGISTRY.collect()
        if family.name == "gaia_link_mint"
        for sample in family.samples
        if sample.name == "gaia_link_mint_total"
    }
    assert outcomes == {outcome.value for outcome in LinkMintOutcome}
