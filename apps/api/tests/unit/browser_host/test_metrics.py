"""Per-session browser metrics: aggregation, navigation timing, failure isolation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.browser_host import metrics as metrics_module
from app.browser_host.metrics import Aggregate, SessionMetrics


@pytest.mark.unit
class TestAggregate:
    def test_tracks_min_max_and_average(self) -> None:
        agg = Aggregate()
        for value in (10.0, 2.0, 6.0):
            agg.add(value)
        assert agg.snapshot() == {"count": 3, "min": 2.0, "max": 10.0, "avg": 6.0}

    def test_single_sample_is_its_own_min_and_max(self) -> None:
        agg = Aggregate()
        agg.add(7.5)
        assert agg.snapshot() == {"count": 1, "min": 7.5, "max": 7.5, "avg": 7.5}

    def test_empty_aggregate_snapshots_as_none_not_zero(self) -> None:
        assert Aggregate().snapshot() is None
        assert Aggregate().average == 0.0


@pytest.mark.unit
class TestNavigationTiming:
    def test_elapsed_ms_is_measured_between_navigate_and_load(self) -> None:
        session_metrics = SessionMetrics()
        with patch.object(metrics_module.time, "monotonic", side_effect=[100.0, 100.25]):
            session_metrics.start_navigation()
            elapsed = session_metrics.finish_navigation()
        assert elapsed == pytest.approx(250.0)
        assert session_metrics.navigation_count == 1
        assert session_metrics.navigation_ms.snapshot() == {
            "count": 1,
            "min": 250.0,
            "max": 250.0,
            "avg": 250.0,
        }

    def test_load_event_without_a_navigate_is_not_counted(self) -> None:
        session_metrics = SessionMetrics()
        assert session_metrics.finish_navigation() is None
        assert session_metrics.navigation_count == 0
        assert session_metrics.navigation_ms.snapshot() is None

    def test_second_navigate_supersedes_an_unfinished_first(self) -> None:
        session_metrics = SessionMetrics()
        with patch.object(metrics_module.time, "monotonic", side_effect=[0.0, 100.0, 100.1]):
            session_metrics.start_navigation()  # abandoned, no load event
            session_metrics.start_navigation()
            elapsed = session_metrics.finish_navigation()
        assert elapsed == pytest.approx(100.0)
        assert session_metrics.navigation_count == 1

    def test_snapshot_carries_counts_and_lifetime(self) -> None:
        session_metrics = SessionMetrics(created_at=50.0)
        with patch.object(metrics_module.time, "monotonic", return_value=62.5):
            session_metrics.page_count = 3
            session_metrics.add_resource_sample(rss_mb=400.0, cpu_percent=12.0)
            snapshot = session_metrics.snapshot()
        assert snapshot["session_lifetime_seconds"] == pytest.approx(12.5)
        assert snapshot["page_count"] == 3
        assert snapshot["navigation_count"] == 0
        assert snapshot["navigation_ms"] is None
        assert snapshot["rss_mb"] == {"count": 1, "min": 400.0, "max": 400.0, "avg": 400.0}
        assert snapshot["cpu_percent"] == {"count": 1, "min": 12.0, "max": 12.0, "avg": 12.0}
