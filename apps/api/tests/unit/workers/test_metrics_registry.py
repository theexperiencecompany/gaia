"""Every latency collector is mirrored onto the ARQ worker's own registry.

The worker serves its own Prometheus registry on ARQ_METRICS_PORT, so a collector
registered only on the default one is invisible for everything the worker runs:
the HIL sweep's timeout path, sweep re-dispatched executor runs, and
reminder/workflow-triggered runs.
"""

from app.agents.llm.metrics import (
    LLM_CALL_TOTAL,
    LLM_FALLBACK_TOTAL,
    UNKNOWN_PROVIDER,
    create_llm_series,
)
from app.constants.briefing import BriefingKind, BriefingRunOutcome
from app.constants.llm import LLMProviderName
from app.services import latency_metrics
from app.services.briefing.metrics import FAILED, create_brief_run_series
from app.services.latency_metrics import create_chat_turn_series
from app.services.links.metrics import LinkMintOutcome, create_link_mint_series
from app.services.scheduler_metrics import (
    SCHEDULED_TASK_LATENESS_SECONDS,
    SCHEDULED_TASK_TOTAL,
    create_scheduled_task_series,
)
from app.workers.metrics import REGISTRY as WORKER_REGISTRY
from tests.helpers import series_labels


def test_every_latency_collector_is_served_by_the_worker_registry() -> None:
    names = set(WORKER_REGISTRY._names_to_collectors)
    missing = [
        collector._name
        for collector in latency_metrics.ALL_COLLECTORS
        if collector._name not in names
    ]
    assert missing == []
    assert "tool_call_seconds" in names
    assert "executor_e2e_seconds" in names


def test_every_briefing_run_series_is_served_by_the_worker_before_its_first_run() -> None:
    create_brief_run_series()

    outcomes = [*(o.value for o in BriefingRunOutcome), FAILED]
    assert series_labels("gaia_brief_run_total", WORKER_REGISTRY) == {
        (kind.value, outcome) for kind in BriefingKind for outcome in outcomes
    }


def test_the_link_mint_failure_series_is_served_by_the_worker_before_its_first_mint() -> None:
    """Briefs and workflow results mint their links on the worker; the alert reads the failed series."""
    create_link_mint_series()

    assert series_labels("gaia_link_mint_total", WORKER_REGISTRY) == {
        (outcome.value,) for outcome in LinkMintOutcome
    }


def test_every_llm_series_is_served_by_the_worker_before_its_first_call() -> None:
    """The worker runs model calls; the alerts read each provider's failures and the exhausted fallbacks."""
    LLM_CALL_TOTAL.clear()
    LLM_FALLBACK_TOTAL.clear()

    create_llm_series()

    providers = [*(provider.value for provider in LLMProviderName), UNKNOWN_PROVIDER]
    assert series_labels("gaia_llm_call_total", WORKER_REGISTRY) == {
        (provider, outcome)
        for provider in providers
        for outcome in ("ok", "rate_limited", "failed")
    }
    assert series_labels("gaia_llm_fallback_total", WORKER_REGISTRY) == {
        ("recovered",),
        ("exhausted",),
    }


def test_every_scheduler_series_is_served_by_the_worker_before_its_first_task() -> None:
    """The worker claims and reaps scheduled tasks; the alerts read each kind's failures and lateness."""
    SCHEDULED_TASK_TOTAL.clear()
    SCHEDULED_TASK_LATENESS_SECONDS.clear()

    create_scheduled_task_series()

    kinds = ("reminder", "workflow")
    assert series_labels("gaia_scheduled_task_total", WORKER_REGISTRY) == {
        (kind, outcome) for kind in kinds for outcome in ("ok", "failed", "reaped")
    }
    assert series_labels("gaia_scheduled_task_lateness_seconds_count", WORKER_REGISTRY) == {
        (kind,) for kind in kinds
    }


def test_the_chat_turn_series_is_served_by_the_worker() -> None:
    """The worker settles chat turns; the alert reads their failures."""
    create_chat_turn_series()

    assert series_labels("chat_turn_total", WORKER_REGISTRY)
