"""Every latency collector is mirrored onto the ARQ worker's own registry.

The worker serves its own Prometheus registry on ARQ_METRICS_PORT, so a collector
registered only on the default one is invisible for everything the worker runs:
the HIL sweep's timeout path, sweep re-dispatched executor runs, and
reminder/workflow-triggered runs.
"""

from app.services import latency_metrics
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
