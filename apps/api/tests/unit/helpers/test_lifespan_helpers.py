"""Tests for app/helpers/lifespan_helpers.py"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.helpers.lifespan_helpers import (
    _process_results,
    close_checkpointer_manager,
    close_mcp_client_pool,
    close_postgresql_async,
    close_publisher_async,
    close_reminder_scheduler,
    close_websocket_async,
    close_workflow_scheduler,
    init_mongodb_async,
    init_reminder_service,
    init_websocket_consumer,
    init_workflow_service,
    setup_event_loop_policy,
)


# ---------------------------------------------------------------------------
# setup_event_loop_policy
# ---------------------------------------------------------------------------


class TestSetupEventLoopPolicy:
    def test_unix_with_uvloop(self) -> None:
        mock_uvloop = MagicMock()
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict("sys.modules", {"uvloop": mock_uvloop}),
            patch("asyncio.set_event_loop_policy") as mock_set,
        ):
            setup_event_loop_policy()
            mock_set.assert_called_once()

    def test_unix_without_uvloop(self) -> None:
        with (
            patch.object(sys, "platform", "linux"),
            patch("builtins.__import__", side_effect=ImportError("no uvloop")),
        ):
            # Should not raise
            setup_event_loop_policy()

    def test_windows(self) -> None:
        with patch.object(sys, "platform", "win32"):
            # Should not raise, just logs
            setup_event_loop_policy()


# ---------------------------------------------------------------------------
# Init functions
# ---------------------------------------------------------------------------


class TestInitReminderService:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch("app.helpers.lifespan_helpers.reminder_scheduler") as mock_sched:
            mock_sched.initialize = AsyncMock()
            mock_sched.scan_and_schedule_pending_tasks = AsyncMock()
            await init_reminder_service()
            mock_sched.initialize.assert_awaited_once()
            mock_sched.scan_and_schedule_pending_tasks.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_reraises(self) -> None:
        with patch("app.helpers.lifespan_helpers.reminder_scheduler") as mock_sched:
            mock_sched.initialize = AsyncMock(side_effect=RuntimeError("fail"))
            with pytest.raises(RuntimeError, match="fail"):
                await init_reminder_service()


class TestInitWorkflowService:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch("app.helpers.lifespan_helpers.workflow_scheduler") as mock_sched:
            mock_sched.initialize = AsyncMock()
            mock_sched.scan_and_schedule_pending_tasks = AsyncMock()
            await init_workflow_service()
            mock_sched.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_reraises(self) -> None:
        with patch("app.helpers.lifespan_helpers.workflow_scheduler") as mock_sched:
            mock_sched.initialize = AsyncMock(side_effect=RuntimeError("workflow fail"))
            with pytest.raises(RuntimeError):
                await init_workflow_service()


class TestInitWebsocketConsumer:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "app.helpers.lifespan_helpers.start_websocket_consumer",
            new_callable=AsyncMock,
        ):
            await init_websocket_consumer()

    @pytest.mark.asyncio
    async def test_error_reraises(self) -> None:
        with patch(
            "app.helpers.lifespan_helpers.start_websocket_consumer",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ws fail"),
        ):
            with pytest.raises(RuntimeError):
                await init_websocket_consumer()


class TestInitMongodbAsync:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        mock_client = MagicMock()
        mock_client._initialize_indexes = AsyncMock()

        # The function does `from app.db.mongodb.mongodb import init_mongodb` locally
        with patch(
            "app.db.mongodb.mongodb.init_mongodb",
            return_value=mock_client,
        ):
            await init_mongodb_async()
            mock_client._initialize_indexes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_reraises(self) -> None:
        with patch(
            "app.db.mongodb.mongodb.init_mongodb",
            side_effect=RuntimeError("mongo fail"),
        ):
            with pytest.raises(RuntimeError):
                await init_mongodb_async()


# ---------------------------------------------------------------------------
# Shutdown functions
# ---------------------------------------------------------------------------


class TestClosePostgresqlAsync:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "app.helpers.lifespan_helpers.close_postgresql_db",
            new_callable=AsyncMock,
        ):
            await close_postgresql_async()

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with patch(
            "app.helpers.lifespan_helpers.close_postgresql_db",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pg fail"),
        ):
            # Should not raise
            await close_postgresql_async()


class TestCloseReminderScheduler:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch("app.services.reminder_service.reminder_scheduler") as mock_sched:
            mock_sched.close = AsyncMock()
            await close_reminder_scheduler()

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with patch("app.services.reminder_service.reminder_scheduler") as mock_sched:
            mock_sched.close = AsyncMock(side_effect=RuntimeError("fail"))
            await close_reminder_scheduler()


class TestCloseWorkflowScheduler:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch("app.helpers.lifespan_helpers.workflow_scheduler") as mock_sched:
            mock_sched.close = AsyncMock()
            await close_workflow_scheduler()

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with patch("app.helpers.lifespan_helpers.workflow_scheduler") as mock_sched:
            mock_sched.close = AsyncMock(side_effect=RuntimeError("fail"))
            await close_workflow_scheduler()


class TestCloseWebsocketAsync:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "app.helpers.lifespan_helpers.stop_websocket_consumer",
            new_callable=AsyncMock,
        ):
            await close_websocket_async()

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with patch(
            "app.helpers.lifespan_helpers.stop_websocket_consumer",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ws stop fail"),
        ):
            await close_websocket_async()


class TestClosePublisherAsync:
    @pytest.mark.asyncio
    async def test_not_initialized_skips(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = False
            await close_publisher_async()
            # get_rabbitmq_publisher should not be called
            mock_providers.is_initialized.assert_called_once_with("rabbitmq_publisher")

    @pytest.mark.asyncio
    async def test_initialized_closes(self) -> None:
        mock_publisher = AsyncMock()

        with (
            patch("app.helpers.lifespan_helpers.providers") as mock_providers,
            patch(
                "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
                new_callable=AsyncMock,
                return_value=mock_publisher,
            ),
        ):
            mock_providers.is_initialized.return_value = True
            await close_publisher_async()
            mock_publisher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publisher_is_none(self) -> None:
        with (
            patch("app.helpers.lifespan_helpers.providers") as mock_providers,
            patch(
                "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_providers.is_initialized.return_value = True
            await close_publisher_async()  # Should not raise

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with (
            patch("app.helpers.lifespan_helpers.providers") as mock_providers,
            patch(
                "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
                new_callable=AsyncMock,
                side_effect=RuntimeError("rabbitmq fail"),
            ),
        ):
            mock_providers.is_initialized.return_value = True
            await close_publisher_async()


class TestCloseCheckpointerManager:
    @pytest.mark.asyncio
    async def test_not_initialized_skips(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = False
            await close_checkpointer_manager()

    @pytest.mark.asyncio
    async def test_initialized_closes(self) -> None:
        mock_mgr = AsyncMock()

        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = True
            mock_providers.aget = AsyncMock(return_value=mock_mgr)
            await close_checkpointer_manager()
            mock_mgr.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manager_is_none(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = True
            mock_providers.aget = AsyncMock(return_value=None)
            await close_checkpointer_manager()

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = True
            mock_providers.aget = AsyncMock(side_effect=RuntimeError("ckpt fail"))
            await close_checkpointer_manager()


class TestCloseMcpClientPool:
    @pytest.mark.asyncio
    async def test_not_initialized_skips(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = False
            await close_mcp_client_pool()

    @pytest.mark.asyncio
    async def test_initialized_shuts_down(self) -> None:
        mock_pool = AsyncMock()

        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = True
            mock_providers.aget = AsyncMock(return_value=mock_pool)
            await close_mcp_client_pool()
            mock_pool.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_is_none(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = True
            mock_providers.aget = AsyncMock(return_value=None)
            await close_mcp_client_pool()

    @pytest.mark.asyncio
    async def test_error_swallowed(self) -> None:
        with patch("app.helpers.lifespan_helpers.providers") as mock_providers:
            mock_providers.is_initialized.return_value = True
            mock_providers.aget = AsyncMock(side_effect=RuntimeError("mcp fail"))
            await close_mcp_client_pool()


# ---------------------------------------------------------------------------
# _process_results
# ---------------------------------------------------------------------------


class TestProcessResults:
    def test_no_failures(self) -> None:
        # No exceptions means no raise
        _process_results(["ok", 42], ["svc_a", "svc_b"])

    def test_single_failure_raises(self) -> None:
        results = [RuntimeError("boom"), "ok"]
        with pytest.raises(RuntimeError, match="Failed to initialize services"):
            _process_results(results, ["svc_a", "svc_b"])

    def test_failure_on_first_iteration(self) -> None:
        """Bug in code: the `if failed_services` check is inside the loop,
        so it raises on the very first failure."""
        results = [RuntimeError("first")]
        with pytest.raises(RuntimeError):
            _process_results(results, ["svc_a"])

    def test_all_success(self) -> None:
        _process_results([None, "result"], ["svc_a", "svc_b"])
