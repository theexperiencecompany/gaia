"""Unit tests for ARQ worker lifecycle (startup, shutdown) and config."""

import asyncio
import importlib.util
from pathlib import Path
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.config.worker_settings import WorkerSettings
from app.workers.lifecycle.shutdown import shutdown

# ---------------------------------------------------------------------------
# startup — imported lazily because the module has side-effects at import time
# (calls configure_file_logging and setup_warnings)
# ---------------------------------------------------------------------------


class TestWorkerStartup:
    """Tests for ARQ worker startup function."""

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


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestWorkerShutdown:
    """Tests for ARQ worker shutdown function."""

    async def test_shutdown_calls_unified_shutdown_with_arq_worker(self):
        """unified_shutdown is called with the 'arq_worker' literal."""
        ctx: dict = {"startup_time": 100.0}
        with patch(
            "app.workers.lifecycle.shutdown.unified_shutdown",
            new_callable=AsyncMock,
        ) as mock_unified:
            await shutdown(ctx)

        mock_unified.assert_awaited_once_with("arq_worker")

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

    The class doubles as the ARQ wiring registry: ``app/worker.py`` assigns
    ``functions`` / ``cron_jobs`` / ``on_startup`` / ``on_shutdown`` at
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
        """functions starts as an empty list (populated by the worker module)."""
        assert isinstance(WorkerSettings.functions, list)

    def test_cron_jobs_default_empty_list(self):
        """cron_jobs starts as an empty list."""
        assert isinstance(WorkerSettings.cron_jobs, list)

    def test_on_startup_default_none(self):
        """on_startup is None by default (set by the worker module)."""
        assert WorkerSettings.on_startup is None

    def test_on_shutdown_default_none(self):
        """on_shutdown is None by default."""
        assert WorkerSettings.on_shutdown is None

    def test_max_jobs_is_positive_integer(self):
        """max_jobs must be a positive integer."""
        assert isinstance(WorkerSettings.max_jobs, int)
        assert WorkerSettings.max_jobs > 0

    def test_job_timeout_is_positive(self):
        """job_timeout must be positive (in seconds)."""
        assert isinstance(WorkerSettings.job_timeout, int)
        assert WorkerSettings.job_timeout > 0

    def test_job_timeout_is_30_minutes(self):
        """Default job timeout should be 30 minutes (1800 seconds)."""
        assert WorkerSettings.job_timeout == 1800

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
        """Each worker must own its liveness key, or the probe stops being liveness.

        ``scripts/arq_healthcheck.py`` runs INSIDE each worker container and is
        just ``EXISTS <key>``. While the key was the global ``arq:health``,
        every worker wrote the same one, so a wedged worker's own probe was
        satisfied by a sibling still refreshing it — measured: worker 1 dead,
        worker 2 alive, worker 1's probe still HEALTHY. The container is never
        restarted, it holds a replica slot doing nothing, and the queue backs up
        with nothing to alert on. Correct at one worker; silently wrong at more.
        """
        assert WorkerSettings.health_check_key != "arq:health", (
            "a fleet-wide health key makes the probe report 'is ANY worker alive'"
        )
        assert socket.gethostname() in WorkerSettings.health_check_key

    def test_healthcheck_probe_reads_the_key_this_worker_writes(self):
        """The probe cannot import ``app``, so the two derivations must be pinned.

        ``arq_healthcheck.py`` deliberately imports nothing from the app (it runs
        outside the entrypoint with no Infisical credentials), so the key format
        is duplicated on purpose. Nothing but this test stops the two sides from
        drifting apart — and a drifted probe reads a key nobody writes, which
        fails every container immediately.
        """
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
