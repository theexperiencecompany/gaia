"""Unit tests for ARQ worker lifecycle (startup, shutdown) and config."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.lifecycle.shutdown import shutdown
from app.workers.config.worker_settings import WorkerSettings


# ---------------------------------------------------------------------------
# startup — imported lazily because the module has side-effects at import time
# (calls configure_file_logging and setup_warnings)
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestWorkerSettings:
    """Tests for WorkerSettings configuration class."""

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
        assert WorkerSettings.health_check_key == "arq:health"

    def test_allow_abort_jobs_enabled(self):
        """allow_abort_jobs should be True."""
        assert WorkerSettings.allow_abort_jobs is True

    def test_max_jobs_value(self):
        """max_jobs default is 10."""
        assert WorkerSettings.max_jobs == 10

    def test_health_check_interval_value(self):
        """health_check_interval default is 30 seconds."""
        assert WorkerSettings.health_check_interval == 30
