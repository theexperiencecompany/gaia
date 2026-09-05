"""Per-session browser metrics: aggregation, navigation timing, failure isolation."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import psutil
import pytest

from app.browser_host import metrics as metrics_module
from app.browser_host.chromium import ChromiumHost
from app.browser_host.metrics import Aggregate, ProcessSampler, SessionMetrics


class _FakeCDP:
    """Root CDP stand-in: every call returns the ids ``create_context`` needs."""

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        return {
            "browserContextId": "ctx-1",
            "targetId": "tgt-1",
            "cookies": [],
            "targetInfos": [],
        }


def _make_host() -> ChromiumHost:
    host = ChromiumHost()
    host._cdp = _FakeCDP()
    host._proc = MagicMock(returncode=None)
    return host


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
            session_metrics.context_count = 1
            session_metrics.page_count = 3
            session_metrics.add_resource_sample(rss_mb=400.0, cpu_percent=12.0)
            snapshot = session_metrics.snapshot()
        assert snapshot["session_lifetime_seconds"] == pytest.approx(12.5)
        assert snapshot["context_count"] == 1
        assert snapshot["page_count"] == 3
        assert snapshot["navigation_count"] == 0
        assert snapshot["navigation_ms"] is None
        assert snapshot["rss_mb"] == {"count": 1, "min": 400.0, "max": 400.0, "avg": 400.0}
        assert snapshot["cpu_percent"] == {"count": 1, "min": 12.0, "max": 12.0, "avg": 12.0}


@pytest.mark.unit
class TestSamplerFailureIsolation:
    def test_sampler_for_a_dead_process_is_none_not_an_exception(self) -> None:
        with patch.object(metrics_module.psutil, "Process", side_effect=psutil.NoSuchProcess(1234)):
            assert ProcessSampler.for_pid(1234) is None

    def test_sample_returns_none_when_the_process_tree_cannot_be_read(self) -> None:
        sampler = ProcessSampler.for_pid(psutil.Process().pid)
        assert sampler is not None
        sampler._root = MagicMock()
        sampler._root.children.side_effect = psutil.AccessDenied(1234)
        assert sampler.sample() is None

    async def test_a_failing_sampler_does_not_break_create_or_dispose(self) -> None:
        host = _make_host()
        failing = MagicMock()
        failing.sample.return_value = None
        host._sampler = failing

        session = await host.create_context(None)
        state = await host.dispose_context(session.session_id)

        assert state == {"cookies": [], "origins": []}
        assert failing.sample.called
        assert session.metrics.rss_mb.snapshot() is None
        assert session.metrics.context_count == 1


@pytest.mark.unit
class TestHostSessionMetrics:
    async def test_session_info_exposes_a_live_metrics_block(self) -> None:
        host = _make_host()
        host._sampler = MagicMock()
        host._sampler.sample.return_value = (512.0, 25.0)

        session = await host.create_context(None)
        host.note_navigation_started(session.session_id)
        host.note_navigation_finished(session.session_id)
        host.note_page_created(session.session_id)
        info = await host.session_info(session.session_id)

        metrics = info["metrics"]
        assert metrics["navigation_count"] == 1
        assert metrics["context_count"] == 1
        assert metrics["page_count"] == 2
        assert metrics["rss_mb"]["max"] == 512.0
        assert metrics["navigation_ms"]["count"] == 1

    async def test_unknown_session_ids_are_ignored_by_the_metric_hooks(self) -> None:
        host = _make_host()
        host._sampler = MagicMock()
        host.note_navigation_started("gone")
        host.note_navigation_finished("gone")
        host.note_page_created("gone")
        host.sample_resources("gone")
        assert not host._sampler.sample.called
