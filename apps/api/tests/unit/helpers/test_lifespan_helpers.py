"""Tests for app/helpers/lifespan_helpers.py"""

import pytest
from pytest_mock import MockerFixture

from app.helpers.lifespan_helpers import (
    StartupService,
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
)
from app.services.reminder_service import reminder_scheduler as real_reminder_scheduler
from app.services.workflow.scheduler import workflow_scheduler as real_workflow_scheduler

# ---------------------------------------------------------------------------
# Init functions
# ---------------------------------------------------------------------------


class TestInitReminderService:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_sched = mocker.patch.object(
            real_reminder_scheduler, "initialize", new=mocker.AsyncMock()
        )
        mocker.patch.object(
            real_reminder_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await init_reminder_service()

        mock_sched.assert_awaited_once()
        mock_log.info.assert_called_once_with(
            "Reminder scheduler initialized and pending reminders scheduled"
        )

    @pytest.mark.asyncio
    async def test_scan_and_schedule_called(self, mocker: MockerFixture) -> None:
        mock_scan = mocker.patch.object(
            real_reminder_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(),
        )
        mocker.patch.object(real_reminder_scheduler, "initialize", new=mocker.AsyncMock())
        mocker.patch("app.helpers.lifespan_helpers.log")

        await init_reminder_service()

        mock_scan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_reraises_and_logs(self, mocker: MockerFixture) -> None:
        mock_sched = mocker.patch.object(
            real_reminder_scheduler,
            "initialize",
            new=mocker.AsyncMock(side_effect=RuntimeError("reminder boom")),
        )
        mock_scan = mocker.patch.object(
            real_reminder_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(RuntimeError, match="reminder boom"):
            await init_reminder_service()

        mock_sched.assert_awaited_once()
        mock_scan.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            "Failed to initialize reminder scheduler",
            error="reminder boom",
            error_type="RuntimeError",
        )

    @pytest.mark.asyncio
    async def test_error_scan_and_schedule_reraises(self, mocker: MockerFixture) -> None:
        mock_scan = mocker.patch.object(
            real_reminder_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(side_effect=ValueError("scan boom")),
        )
        mocker.patch.object(real_reminder_scheduler, "initialize", new=mocker.AsyncMock())
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(ValueError, match="scan boom"):
            await init_reminder_service()

        mock_scan.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Failed to initialize reminder scheduler",
            error="scan boom",
            error_type="ValueError",
        )


class TestInitWorkflowService:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_init = mocker.patch.object(
            real_workflow_scheduler, "initialize", new=mocker.AsyncMock()
        )
        mock_scan = mocker.patch.object(
            real_workflow_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await init_workflow_service()

        mock_init.assert_awaited_once()
        mock_scan.assert_awaited_once()
        mock_log.info.assert_called_once_with("Workflow service initialized")

    @pytest.mark.asyncio
    async def test_error_reraises_and_logs(self, mocker: MockerFixture) -> None:
        mock_init = mocker.patch.object(
            real_workflow_scheduler,
            "initialize",
            new=mocker.AsyncMock(side_effect=RuntimeError("workflow boom")),
        )
        mock_scan = mocker.patch.object(
            real_workflow_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(RuntimeError, match="workflow boom"):
            await init_workflow_service()

        mock_init.assert_awaited_once()
        mock_scan.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            "Failed to initialize workflow service",
            error="workflow boom",
            error_type="RuntimeError",
        )

    @pytest.mark.asyncio
    async def test_error_scan_and_schedule_reraises(self, mocker: MockerFixture) -> None:
        mock_scan = mocker.patch.object(
            real_workflow_scheduler,
            "scan_and_schedule_pending_tasks",
            new=mocker.AsyncMock(side_effect=ValueError("workflow scan boom")),
        )
        mocker.patch.object(real_workflow_scheduler, "initialize", new=mocker.AsyncMock())
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(ValueError, match="workflow scan boom"):
            await init_workflow_service()

        mock_scan.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Failed to initialize workflow service",
            error="workflow scan boom",
            error_type="ValueError",
        )


class TestInitWebsocketConsumer:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_start = mocker.patch(
            "app.helpers.lifespan_helpers.start_websocket_consumer",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await init_websocket_consumer()

        mock_start.assert_awaited_once()
        mock_log.info.assert_called_once_with("WebSocket event consumer started")

    @pytest.mark.asyncio
    async def test_error_reraises_and_logs(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "app.helpers.lifespan_helpers.start_websocket_consumer",
            new=mocker.AsyncMock(side_effect=RuntimeError("ws boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(RuntimeError, match="ws boom"):
            await init_websocket_consumer()

        mock_log.error.assert_called_once_with(
            "Failed to start WebSocket consumer",
            error="ws boom",
            error_type="RuntimeError",
        )


class TestInitMongodbAsync:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_client = mocker.MagicMock()
        mock_client._initialize_indexes = mocker.AsyncMock()
        mock_init = mocker.patch(
            "app.db.mongodb.mongodb.init_mongodb", return_value=mock_client
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await init_mongodb_async()

        mock_init.assert_called_once_with()
        mock_client._initialize_indexes.assert_awaited_once()
        mock_log.info.assert_called_once_with("MongoDB initialized and indexes created")

    @pytest.mark.asyncio
    async def test_error_reraises_and_logs(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "app.db.mongodb.mongodb.init_mongodb",
            side_effect=RuntimeError("mongo boom"),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(RuntimeError, match="mongo boom"):
            await init_mongodb_async()

        mock_log.error.assert_called_once_with(
            "Failed to initialize MongoDB and create indexes",
            error="mongo boom",
            error_type="RuntimeError",
        )

    @pytest.mark.asyncio
    async def test_error_indexes_reraises_and_logs(self, mocker: MockerFixture) -> None:
        mock_client = mocker.MagicMock()
        mock_client._initialize_indexes = mocker.AsyncMock(
            side_effect=ValueError("index boom")
        )
        mocker.patch("app.db.mongodb.mongodb.init_mongodb", return_value=mock_client)
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        with pytest.raises(ValueError, match="index boom"):
            await init_mongodb_async()

        mock_client._initialize_indexes.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Failed to initialize MongoDB and create indexes",
            error="index boom",
            error_type="ValueError",
        )


# ---------------------------------------------------------------------------
# Shutdown functions
# ---------------------------------------------------------------------------


class TestClosePostgresqlAsync:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_close = mocker.patch(
            "app.helpers.lifespan_helpers.close_postgresql_db",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_postgresql_async()

        mock_close.assert_awaited_once()
        mock_log.info.assert_called_once_with("PostgreSQL database closed")

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_close = mocker.patch(
            "app.helpers.lifespan_helpers.close_postgresql_db",
            new=mocker.AsyncMock(side_effect=RuntimeError("pg boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_postgresql_async()

        mock_close.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Error closing PostgreSQL database",
            error="pg boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


class TestCloseReminderScheduler:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(
            real_reminder_scheduler, "close", new=mocker.AsyncMock()
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_reminder_scheduler()

        mock_close.assert_awaited_once()
        mock_log.info.assert_called_once_with("Reminder scheduler closed")

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(
            real_reminder_scheduler,
            "close",
            new=mocker.AsyncMock(side_effect=RuntimeError("reminder close boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_reminder_scheduler()

        mock_close.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Error closing reminder scheduler",
            error="reminder close boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


class TestCloseWorkflowScheduler:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(
            real_workflow_scheduler, "close", new=mocker.AsyncMock()
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_workflow_scheduler()

        mock_close.assert_awaited_once()
        mock_log.info.assert_called_once_with("Workflow scheduler closed")

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(
            real_workflow_scheduler,
            "close",
            new=mocker.AsyncMock(side_effect=RuntimeError("workflow close boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_workflow_scheduler()

        mock_close.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Error closing workflow scheduler",
            error="workflow close boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


class TestCloseWebsocketAsync:
    @pytest.mark.asyncio
    async def test_success(self, mocker: MockerFixture) -> None:
        mock_stop = mocker.patch(
            "app.helpers.lifespan_helpers.stop_websocket_consumer",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_websocket_async()

        mock_stop.assert_awaited_once()
        mock_log.info.assert_called_once_with("WebSocket event consumer stopped")

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_stop = mocker.patch(
            "app.helpers.lifespan_helpers.stop_websocket_consumer",
            new=mocker.AsyncMock(side_effect=RuntimeError("ws stop boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_websocket_async()

        mock_stop.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Error stopping WebSocket consumer",
            error="ws stop boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


class TestClosePublisherAsync:
    @pytest.mark.asyncio
    async def test_not_initialized_skips(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = False
        mock_get = mocker.patch(
            "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
            new=mocker.AsyncMock(),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_publisher_async()

        mock_providers.is_initialized.assert_called_once_with("rabbitmq_publisher")
        mock_get.assert_not_awaited()
        assert mock_log.method_calls == []

    @pytest.mark.asyncio
    async def test_initialized_closes(self, mocker: MockerFixture) -> None:
        mock_publisher = mocker.AsyncMock()
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_get = mocker.patch(
            "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
            new=mocker.AsyncMock(return_value=mock_publisher),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_publisher_async()

        mock_providers.is_initialized.assert_called_once_with("rabbitmq_publisher")
        mock_get.assert_awaited_once()
        mock_publisher.close.assert_awaited_once()
        mock_log.info.assert_called_once_with("Publisher closed")

    @pytest.mark.asyncio
    async def test_publisher_is_none_logs_closed(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mocker.patch(
            "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
            new=mocker.AsyncMock(return_value=None),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_publisher_async()

        mock_log.info.assert_called_once_with("Publisher closed")

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_get = mocker.patch(
            "app.helpers.lifespan_helpers.get_rabbitmq_publisher",
            new=mocker.AsyncMock(side_effect=RuntimeError("rabbitmq boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_publisher_async()

        mock_providers.is_initialized.assert_called_once_with("rabbitmq_publisher")
        mock_get.assert_awaited_once()
        mock_log.error.assert_called_once_with(
            "Error closing publisher",
            error="rabbitmq boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


class TestCloseCheckpointerManager:
    @pytest.mark.asyncio
    async def test_not_initialized_skips(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = False
        mock_aget = mocker.patch.object(mock_providers, "aget", new=mocker.AsyncMock())
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_checkpointer_manager()

        mock_providers.is_initialized.assert_called_once_with("checkpointer_manager")
        mock_aget.assert_not_awaited()
        assert mock_log.method_calls == []

    @pytest.mark.asyncio
    async def test_initialized_closes(self, mocker: MockerFixture) -> None:
        mock_mgr = mocker.AsyncMock()
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_aget = mocker.patch.object(
            mock_providers, "aget", new=mocker.AsyncMock(return_value=mock_mgr)
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_checkpointer_manager()

        mock_providers.is_initialized.assert_called_once_with("checkpointer_manager")
        mock_aget.assert_awaited_once_with("checkpointer_manager")
        mock_mgr.close.assert_awaited_once()
        mock_log.info.assert_called_once_with("Checkpointer manager closed")

    @pytest.mark.asyncio
    async def test_manager_is_none_skips_close(self, mocker: MockerFixture) -> None:
        mock_mgr = mocker.AsyncMock()
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_aget = mocker.patch.object(
            mock_providers, "aget", new=mocker.AsyncMock(return_value=None)
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_checkpointer_manager()

        mock_aget.assert_awaited_once_with("checkpointer_manager")
        mock_mgr.close.assert_not_awaited()
        mock_log.info.assert_not_called()
        mock_log.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_aget = mocker.patch.object(
            mock_providers,
            "aget",
            new=mocker.AsyncMock(side_effect=RuntimeError("ckpt boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_checkpointer_manager()

        mock_providers.is_initialized.assert_called_once_with("checkpointer_manager")
        mock_aget.assert_awaited_once_with("checkpointer_manager")
        mock_log.error.assert_called_once_with(
            "Error closing checkpointer manager",
            error="ckpt boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


class TestCloseMcpClientPool:
    @pytest.mark.asyncio
    async def test_not_initialized_skips(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = False
        mock_aget = mocker.patch.object(mock_providers, "aget", new=mocker.AsyncMock())
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_mcp_client_pool()

        mock_providers.is_initialized.assert_called_once_with("mcp_client_pool")
        mock_aget.assert_not_awaited()
        assert mock_log.method_calls == []

    @pytest.mark.asyncio
    async def test_initialized_shuts_down(self, mocker: MockerFixture) -> None:
        mock_pool = mocker.AsyncMock()
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_aget = mocker.patch.object(
            mock_providers, "aget", new=mocker.AsyncMock(return_value=mock_pool)
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_mcp_client_pool()

        mock_providers.is_initialized.assert_called_once_with("mcp_client_pool")
        mock_aget.assert_awaited_once_with("mcp_client_pool")
        mock_pool.shutdown.assert_awaited_once()
        mock_log.info.assert_called_once_with("MCP client pool closed")

    @pytest.mark.asyncio
    async def test_pool_is_none_skips_shutdown(self, mocker: MockerFixture) -> None:
        mock_pool = mocker.AsyncMock()
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_aget = mocker.patch.object(
            mock_providers, "aget", new=mocker.AsyncMock(return_value=None)
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_mcp_client_pool()

        mock_aget.assert_awaited_once_with("mcp_client_pool")
        mock_pool.shutdown.assert_not_awaited()
        mock_log.info.assert_not_called()
        mock_log.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_swallowed_and_logged(self, mocker: MockerFixture) -> None:
        mock_providers = mocker.patch("app.helpers.lifespan_helpers.providers")
        mock_providers.is_initialized.return_value = True
        mock_aget = mocker.patch.object(
            mock_providers,
            "aget",
            new=mocker.AsyncMock(side_effect=RuntimeError("mcp boom")),
        )
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        await close_mcp_client_pool()

        mock_providers.is_initialized.assert_called_once_with("mcp_client_pool")
        mock_aget.assert_awaited_once_with("mcp_client_pool")
        mock_log.error.assert_called_once_with(
            "Error closing MCP client pool",
            error="mcp boom",
            error_type="RuntimeError",
        )
        mock_log.info.assert_not_called()


# ---------------------------------------------------------------------------
# _process_results
# ---------------------------------------------------------------------------


def _svc(name: str, *, required: bool = True) -> StartupService:
    """Build a minimal StartupService for _process_results tests."""
    return StartupService(func=lambda: None, name=name, required=required)  # type: ignore[arg-type]


class TestProcessResults:
    def test_no_failures_no_logs(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        _process_results(["ok", 42], [_svc("svc_a"), _svc("svc_b")])

        assert mock_log.method_calls == []

    def test_all_success_no_raise(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        _process_results([None, "result"], [_svc("svc_a"), _svc("svc_b")])

        assert mock_log.method_calls == []

    def test_single_required_failure_raises_and_logs(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        exc = RuntimeError("boom")
        results = [exc, "ok"]

        with pytest.raises(RuntimeError) as exc_info:
            _process_results(results, [_svc("svc_a"), _svc("svc_b")])

        assert exc_info.value.args == ("Failed to initialize required services: ['svc_a']",)
        mock_log.error.assert_any_call("Failed to initialize", name="svc_a", result=exc)
        mock_log.error.assert_any_call("Failed to initialize required services: ['svc_a']")
        mock_log.warning.assert_not_called()

    def test_failure_on_first_iteration(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        exc = RuntimeError("first")

        with pytest.raises(RuntimeError) as exc_info:
            _process_results([exc], [_svc("svc_a")])

        assert exc_info.value.args == ("Failed to initialize required services: ['svc_a']",)
        mock_log.error.assert_any_call("Failed to initialize", name="svc_a", result=exc)
        mock_log.error.assert_any_call("Failed to initialize required services: ['svc_a']")

    def test_best_effort_failure_warns_no_raise(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        exc = RuntimeError("optional boom")

        _process_results([exc], [_svc("svc_a", required=False)])

        mock_log.warning.assert_called_once_with(
            "Best-effort startup service failed; continuing degraded",
            name="svc_a",
            result=exc,
        )
        mock_log.error.assert_not_called()

    def test_mixed_failures_raises_required_only(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        optional_exc = RuntimeError("optional boom")
        required_exc = RuntimeError("required boom")
        services = [_svc("opt_a", required=False), _svc("req_a")]

        with pytest.raises(RuntimeError) as exc_info:
            _process_results([optional_exc, required_exc], services)

        assert exc_info.value.args == ("Failed to initialize required services: ['req_a']",)
        mock_log.warning.assert_called_once_with(
            "Best-effort startup service failed; continuing degraded",
            name="opt_a",
            result=optional_exc,
        )
        mock_log.error.assert_any_call("Failed to initialize", name="req_a", result=required_exc)
        mock_log.error.assert_any_call("Failed to initialize required services: ['req_a']")

    def test_multiple_required_failures_preserve_order(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        exc_a = RuntimeError("a boom")
        exc_b = RuntimeError("b boom")

        with pytest.raises(RuntimeError) as exc_info:
            _process_results(
                [exc_a, exc_b],
                [_svc("svc_a"), _svc("svc_b")],
            )

        assert exc_info.value.args == (
            "Failed to initialize required services: ['svc_a', 'svc_b']",
        )
        mock_log.error.assert_any_call("Failed to initialize", name="svc_a", result=exc_a)
        mock_log.error.assert_any_call("Failed to initialize", name="svc_b", result=exc_b)
        mock_log.error.assert_any_call(
            "Failed to initialize required services: ['svc_a', 'svc_b']"
        )

    def test_non_exception_results_are_successes(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")

        _process_results(["not-an-exc", 0], [_svc("svc_a"), _svc("svc_b")])

        assert mock_log.method_calls == []

    def test_failure_after_success_raises(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        exc = RuntimeError("later boom")

        with pytest.raises(RuntimeError) as exc_info:
            _process_results(["ok", exc], [_svc("svc_a"), _svc("svc_b")])

        assert exc_info.value.args == ("Failed to initialize required services: ['svc_b']",)
        mock_log.error.assert_any_call("Failed to initialize", name="svc_b", result=exc)
        mock_log.error.assert_any_call("Failed to initialize required services: ['svc_b']")

    def test_zip_pairs_by_index_and_truncates(self, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("app.helpers.lifespan_helpers.log")
        exc = RuntimeError("first boom")
        tail_exc = RuntimeError("tail boom")

        with pytest.raises(RuntimeError) as exc_info:
            _process_results(
                [exc, "ok", tail_exc],
                [_svc("svc_a"), _svc("svc_b")],
            )

        assert exc_info.value.args == ("Failed to initialize required services: ['svc_a']",)
        mock_log.error.assert_any_call("Failed to initialize", name="svc_a", result=exc)
        mock_log.error.assert_any_call("Failed to initialize required services: ['svc_a']")
