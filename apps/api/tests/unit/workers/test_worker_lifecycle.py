"""Unit tests for ARQ worker lifecycle (startup, shutdown) and config."""

import asyncio
from collections.abc import Iterator
import importlib.util
from pathlib import Path
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.config.worker_settings import (
    ARQ_BACKSTOP_GRACE_SECONDS,
    WORKER_JOB_TIMEOUT_SECONDS,
    WorkerSettings,
)
from app.workers.lifecycle.shutdown import shutdown

# startup is imported lazily: the module has side effects at import time
# (configure_file_logging, setup_warnings).


@pytest.fixture(autouse=True)
def browser_worker_calls() -> Iterator[list[str]]:
    """Record the browser worker's start/stop; a real one would consume the live Redis queue."""
    calls: list[str] = []

    def _start(ctx: dict) -> None:
        calls.append("start")

    async def _stop(ctx: dict) -> None:
        calls.append("stop")

    with (
        patch("app.workers.lifecycle.startup.start_browser_worker", _start),
        patch("app.workers.lifecycle.shutdown.stop_browser_worker", _stop),
    ):
        yield calls


class TestWorkerStartup:
    """Tests for ARQ worker startup function."""

    async def test_startup_starts_the_browser_worker_once_the_process_is_ready(
        self, ctx: dict, browser_worker_calls: list[str]
    ) -> None:
        async def _ready(context: str) -> None:
            assert browser_worker_calls == []

        with patch("app.workers.lifecycle.startup.unified_startup", _ready):
            from app.workers.lifecycle.startup import startup

            await startup(ctx)

        assert browser_worker_calls == ["start"]

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_startup_stores_startup_time_in_ctx(self, ctx):
        """startup() must record the event-loop clock in ctx['startup_time']."""
        with patch(
            "app.workers.lifecycle.startup.unified_startup",
            new_callable=AsyncMock,
        ) as mock_unified:
            from app.workers.lifecycle.startup import startup

            await startup(ctx)

        assert "startup_time" in ctx
        assert isinstance(ctx["startup_time"], float)
        mock_unified.assert_awaited_once_with("arq_worker")

    async def test_startup_calls_unified_startup_with_arq_worker_context(self, ctx):
        """unified_startup is called with the 'arq_worker' context literal."""
        with patch(
            "app.workers.lifecycle.startup.unified_startup",
            new_callable=AsyncMock,
        ) as mock_unified:
            from app.workers.lifecycle.startup import startup

            await startup(ctx)

        mock_unified.assert_awaited_once_with("arq_worker")

    async def test_startup_propagates_unified_startup_error(self, ctx):
        """If unified_startup raises, the error propagates to the caller."""
        with patch(
            "app.workers.lifecycle.startup.unified_startup",
            new_callable=AsyncMock,
            side_effect=RuntimeError("arq_worker startup failed"),
        ):
            from app.workers.lifecycle.startup import startup

            with pytest.raises(RuntimeError, match="arq_worker startup failed"):
                await startup(ctx)

    async def test_startup_time_is_from_event_loop(self, ctx):
        """The stored startup_time should be close to the current loop time."""
        loop = asyncio.get_event_loop()
        before = loop.time()

        with patch(
            "app.workers.lifecycle.startup.unified_startup",
            new_callable=AsyncMock,
        ):
            from app.workers.lifecycle.startup import startup

            await startup(ctx)

        after = loop.time()
        assert before <= ctx["startup_time"] <= after

    async def test_startup_starts_the_device_up_listener(self, ctx):
        """Without this listener, every device warm-connect times out waiting for mcp.opened."""
        with (
            patch(
                "app.workers.lifecycle.startup.unified_startup",
                new_callable=AsyncMock,
            ),
            patch("app.workers.lifecycle.startup.start_up_listener") as mock_start,
        ):
            from app.workers.lifecycle.startup import startup

            await startup(ctx)

        mock_start.assert_called_once_with()


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestWorkerShutdown:
    """Tests for ARQ worker shutdown function."""

    async def test_shutdown_stops_the_browser_worker_before_tearing_services_down(
        self, browser_worker_calls: list[str]
    ) -> None:
        async def _teardown(context: str) -> None:
            assert browser_worker_calls == ["stop"]

        with patch("app.workers.lifecycle.shutdown.unified_shutdown", _teardown):
            await shutdown({})

        assert browser_worker_calls == ["stop"]

    async def test_shutdown_stops_the_browser_worker_this_process_started(self) -> None:
        """The running worker lives in ARQ's ctx; stopping any other leaves its jobs running."""
        stopped: list[dict] = []

        async def _stop(ctx: dict) -> None:
            stopped.append(ctx)

        ctx = {"startup_time": 0}
        with (
            patch("app.workers.lifecycle.shutdown.stop_browser_worker", _stop),
            patch("app.workers.lifecycle.shutdown.unified_shutdown", AsyncMock()),
        ):
            await shutdown(ctx)

        assert stopped == [ctx]
        assert stopped[0] is ctx

    async def test_shutdown_calls_unified_shutdown_with_arq_worker(self):
        """unified_shutdown is called with the 'arq_worker' literal."""
        ctx: dict = {"startup_time": 100.0}
        with patch(
            "app.workers.lifecycle.shutdown.unified_shutdown",
            new_callable=AsyncMock,
        ) as mock_unified:
            await shutdown(ctx)

        mock_unified.assert_awaited_once_with("arq_worker")

    async def test_shutdown_stops_the_device_up_listener(self):
        """Symmetric with startup: the up-listener must be stopped on shutdown."""
        ctx: dict = {"startup_time": 100.0}
        with (
            patch(
                "app.workers.lifecycle.shutdown.unified_shutdown",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.lifecycle.shutdown.stop_up_listener",
                new_callable=AsyncMock,
            ) as mock_stop,
        ):
            await shutdown(ctx)

        mock_stop.assert_awaited_once_with()

    async def test_shutdown_logs_runtime_when_startup_time_present(self):
        """When ctx has startup_time, shutdown computes and logs the runtime."""
        loop = asyncio.get_event_loop()
        ctx: dict = {"startup_time": loop.time() - 5.0}

        with patch(
            "app.workers.lifecycle.shutdown.unified_shutdown",
            new_callable=AsyncMock,
        ):
            # Should not raise — runtime logging is best-effort
            await shutdown(ctx)

    async def test_shutdown_handles_missing_startup_time(self):
        """When startup_time is not in ctx, shutdown skips runtime logging."""
        ctx: dict = {}
        with patch(
            "app.workers.lifecycle.shutdown.unified_shutdown",
            new_callable=AsyncMock,
        ):
            # Should not raise
            await shutdown(ctx)

    async def test_shutdown_handles_zero_startup_time(self):
        """startup_time=0 is falsy — runtime logging is skipped."""
        ctx: dict = {"startup_time": 0}
        with patch(
            "app.workers.lifecycle.shutdown.unified_shutdown",
            new_callable=AsyncMock,
        ):
            await shutdown(ctx)

    async def test_shutdown_propagates_unified_shutdown_error(self):
        """If unified_shutdown raises, the error propagates."""
        ctx: dict = {"startup_time": 100.0}
        with patch(
            "app.workers.lifecycle.shutdown.unified_shutdown",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cleanup explosion"),
        ):
            with pytest.raises(RuntimeError, match="cleanup explosion"):
                await shutdown(ctx)

    async def test_shutdown_with_various_ctx_values(self):
        """Different ctx payloads must not crash shutdown."""
        ctx_variants: list[dict] = [
            {},
            {"startup_time": 50.0},
            {"startup_time": 0},
            {"redis": MagicMock(), "startup_time": 10.0},
        ]
        for ctx in ctx_variants:
            with patch(
                "app.workers.lifecycle.shutdown.unified_shutdown",
                new_callable=AsyncMock,
            ):
                await shutdown(ctx)


# ---------------------------------------------------------------------------
# WorkerSettings
# ---------------------------------------------------------------------------


class TestWorkerSettings:
    """Tests for WorkerSettings configuration class.

    The class doubles as the ARQ wiring registry: app/worker.py assigns
    functions / cron_jobs / on_startup / on_shutdown at
    import, and any test file importing it pollutes the class for the whole
    xdist worker. These tests pin the DECLARED defaults, so reset them in
    setup instead of depending on import order (pytest-randomly).
    """

    def setup_method(self) -> None:
        WorkerSettings.functions = []
        WorkerSettings.cron_jobs = []
        WorkerSettings.on_startup = None
        WorkerSettings.on_shutdown = None

    def test_redis_settings_from_dsn(self):
        """redis_settings is populated from the REDIS_URL setting."""
        assert WorkerSettings.redis_settings is not None

    def test_functions_default_empty_list(self):
        """Functions starts as an empty list (populated by the worker module)."""
        assert isinstance(WorkerSettings.functions, list)

    def test_cron_jobs_default_empty_list(self):
        """cron_jobs starts as an empty list."""
        assert isinstance(WorkerSettings.cron_jobs, list)

    def test_on_startup_default_none(self):
        """on_startup is None by default (set by the worker module)."""
        assert WorkerSettings.on_startup is None

    def test_on_shutdown_default_none(self):
        assert WorkerSettings.on_shutdown is None

    def test_max_jobs_is_positive_integer(self):
        """max_jobs must be a positive integer."""
        assert isinstance(WorkerSettings.max_jobs, int)
        assert WorkerSettings.max_jobs > 0

    def test_job_timeout_is_positive(self):
        """job_timeout must be positive (in seconds)."""
        assert isinstance(WorkerSettings.job_timeout, int)
        assert WorkerSettings.job_timeout > 0

    def test_job_timeout_is_a_backstop_past_the_30_minute_envelope_cap(self):
        """The envelope cuts a job off at 30 minutes; ARQ's timeout only backs it up."""
        assert WORKER_JOB_TIMEOUT_SECONDS == 1800
        assert WorkerSettings.job_timeout == WORKER_JOB_TIMEOUT_SECONDS + ARQ_BACKSTOP_GRACE_SECONDS

    def test_keep_result_zero(self):
        """keep_result=0 means results are not stored in Redis."""
        assert WorkerSettings.keep_result == 0

    def test_log_results_enabled(self):
        """log_results should be True by default."""
        assert WorkerSettings.log_results is True

    def test_health_check_interval_positive(self):
        """health_check_interval must be positive."""
        assert isinstance(WorkerSettings.health_check_interval, int)
        assert WorkerSettings.health_check_interval > 0

    def test_health_check_key_set(self):
        """health_check_key must be a non-empty string."""
        assert isinstance(WorkerSettings.health_check_key, str)
        assert len(WorkerSettings.health_check_key) > 0

    def test_health_check_key_is_per_worker(self):
        """A shared health key lets one worker's dead probe read HEALTHY via a sibling still refreshing it."""
        assert WorkerSettings.health_check_key != "arq:health", (
            "a fleet-wide health key makes the probe report 'is ANY worker alive'"
        )
        assert socket.gethostname() in WorkerSettings.health_check_key

    def test_healthcheck_probe_reads_the_key_this_worker_writes(self):
        """arq_healthcheck.py can't import app, so the key format is duplicated; drift fails every worker."""
        spec = importlib.util.spec_from_file_location(
            "arq_healthcheck", Path(__file__).resolve().parents[3] / "scripts/arq_healthcheck.py"
        )
        assert spec and spec.loader
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)

        assert WorkerSettings.health_check_key == probe.ARQ_HEALTH_KEY

    def test_allow_abort_jobs_enabled(self):
        """allow_abort_jobs should be True."""
        assert WorkerSettings.allow_abort_jobs is True

    def test_max_jobs_value(self):
        """max_jobs default is 10."""
        assert WorkerSettings.max_jobs == 10

    def test_health_check_interval_value(self):
        """health_check_interval default is 30 seconds."""
        assert WorkerSettings.health_check_interval == 30
