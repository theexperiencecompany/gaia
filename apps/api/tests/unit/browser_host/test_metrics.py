"""Per-session browser metrics: aggregation, navigation timing, failure isolation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psutil
import pytest

from app.browser_host import metrics as metrics_module
from app.browser_host.chromium import ChromiumHost
from app.browser_host.metrics import Aggregate, ProcessSampler, SessionMetrics
from app.constants.log_tags import LogTag
from tests.unit.browser_host.conftest import install_mux, make_host

_MB = 1024 * 1024


def _fake_proc(rss_mb: float, cpu: float) -> MagicMock:
    proc = MagicMock()
    proc.memory_info.return_value = MagicMock(rss=int(rss_mb * _MB))
    proc.cpu_percent.return_value = cpu
    return proc


def _sampler_over(root: MagicMock, pid: int = 4321) -> ProcessSampler:
    """Return a real sampler for pid whose process tree resolves to root."""
    with patch.object(metrics_module.psutil, "Process", return_value=root):
        return ProcessSampler(pid)


def _started_host(monkeypatch: pytest.MonkeyPatch) -> ChromiumHost:
    """Build a host whose sessions ride a fake connection, since a session is a connection now."""
    install_mux(monkeypatch)
    return make_host()


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
class TestProcessSamplerReadings:
    def test_sample_sums_the_whole_process_tree_and_reports_rss_in_megabytes(self) -> None:
        root = _fake_proc(rss_mb=100.0, cpu=10.0)
        root.children.return_value = [_fake_proc(50.0, 5.0), _fake_proc(25.0, 2.5)]

        assert _sampler_over(root).sample() == (175.0, 17.5)

    def test_the_tree_walk_is_recursive_so_a_renderers_own_children_are_counted(self) -> None:
        grandchild = _fake_proc(25.0, 2.5)
        child = _fake_proc(50.0, 5.0)
        root = _fake_proc(100.0, 10.0)
        root.children.side_effect = lambda recursive: (
            [child, grandchild] if recursive else [child]
        )

        assert _sampler_over(root).sample() == (175.0, 17.5)

    def test_a_child_that_exits_mid_walk_is_skipped_while_the_rest_still_count(self) -> None:
        gone = _fake_proc(50.0, 5.0)
        gone.memory_info.side_effect = psutil.NoSuchProcess(99)
        root = _fake_proc(100.0, 10.0)
        root.children.return_value = [gone, _fake_proc(25.0, 2.5)]

        assert _sampler_over(root).sample() == (125.0, 12.5)


@pytest.mark.unit
class TestSamplerFailureIsolation:
    def test_sampler_for_a_dead_process_is_none_not_an_exception(self) -> None:
        with patch.object(metrics_module.psutil, "Process", side_effect=psutil.NoSuchProcess(1234)):
            assert ProcessSampler.for_pid(1234) is None

    def test_an_unusable_pid_warns_with_the_pid_and_the_real_failure_type(self) -> None:
        with (
            patch.object(metrics_module.psutil, "Process", side_effect=psutil.NoSuchProcess(1234)),
            patch.object(metrics_module, "log") as mock_log,
        ):
            assert ProcessSampler.for_pid(1234) is None

        mock_log.warning.assert_called_once_with(
            f"{LogTag.BROWSER} browser host resource sampler unavailable",
            error_type="NoSuchProcess",
            browser={"pid": 1234},
        )

    def test_sample_returns_none_when_the_process_tree_cannot_be_read(self) -> None:
        root = MagicMock()
        root.children.side_effect = psutil.AccessDenied(1234)
        assert _sampler_over(root).sample() is None

    def test_a_failed_sample_warns_with_the_sampled_pid_and_the_real_failure_type(self) -> None:
        root = MagicMock()
        root.children.side_effect = psutil.AccessDenied(1234)

        with patch.object(metrics_module, "log") as mock_log:
            assert _sampler_over(root, pid=777).sample() is None

        mock_log.warning.assert_called_once_with(
            f"{LogTag.BROWSER} browser host resource sample failed",
            error_type="AccessDenied",
            browser={"pid": 777},
        )

    def test_for_pid_samples_the_pid_it_was_given_and_names_it_when_that_fails(self) -> None:
        """A sampler aimed at the wrong pid reports another process's numbers as this session's."""
        root = MagicMock()
        root.children.side_effect = psutil.AccessDenied(4321)

        with patch.object(metrics_module.psutil, "Process", return_value=root) as process:
            sampler = ProcessSampler.for_pid(4321)

        assert sampler is not None
        process.assert_called_once_with(4321)

        with patch.object(metrics_module, "log") as mock_log:
            assert sampler.sample() is None

        mock_log.warning.assert_called_once_with(
            f"{LogTag.BROWSER} browser host resource sample failed",
            error_type="AccessDenied",
            browser={"pid": 4321},
        )

    async def test_a_failing_sampler_does_not_break_create_or_dispose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        host = _started_host(monkeypatch)
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
    async def test_session_info_exposes_a_live_metrics_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        host = _started_host(monkeypatch)
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
        host = make_host()
        host._sampler = MagicMock()
        host.note_navigation_started("gone")
        host.note_navigation_finished("gone")
        host.note_page_created("gone")
        host.sample_resources("gone")
        assert not host._sampler.sample.called
