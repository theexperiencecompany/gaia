"""Tests for app.core.provider_registration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# setup_warnings
# ---------------------------------------------------------------------------


class TestSetupWarnings:
    def test_setup_warnings_runs_without_error(self) -> None:
        from app.core.provider_registration import setup_warnings

        # Should not raise
        setup_warnings()


# ---------------------------------------------------------------------------
# _spawn_background_task
# ---------------------------------------------------------------------------


class TestSpawnBackgroundTask:
    @pytest.mark.asyncio
    async def test_task_is_created_and_appended(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_task,
        )

        initial_len = len(_background_tasks)
        called = False

        async def factory() -> None:
            nonlocal called
            called = True

        _spawn_background_task("test_task", factory)

        assert len(_background_tasks) > initial_len
        # Let the task run
        task = _background_tasks[-1]
        await task
        assert called is True
        # Cleanup
        _background_tasks.remove(task)

    @pytest.mark.asyncio
    async def test_task_logs_failure_without_crashing(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_task,
        )

        async def failing_factory() -> None:
            raise RuntimeError("boom")

        _spawn_background_task("failing_task", failing_factory)
        task = _background_tasks[-1]
        # Should NOT raise — failure is caught internally
        await task
        _background_tasks.remove(task)


# ---------------------------------------------------------------------------
# _spawn_background_services
# ---------------------------------------------------------------------------


class TestSpawnBackgroundServices:
    @pytest.mark.asyncio
    async def test_runs_multiple_services(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_services,
        )

        results: list[str] = []

        async def svc_a() -> None:
            results.append("a")

        async def svc_b() -> None:
            results.append("b")

        _spawn_background_services([(svc_a, "svc_a"), (svc_b, "svc_b")])
        task = _background_tasks[-1]
        await task
        assert set(results) == {"a", "b"}
        _background_tasks.remove(task)

    @pytest.mark.asyncio
    async def test_runs_after_callback(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_services,
        )

        after_called = False

        async def svc() -> None:
            pass

        async def after() -> None:
            nonlocal after_called
            after_called = True

        _spawn_background_services(
            [(svc, "svc")],
            after=after,
            after_name="followup",
        )
        task = _background_tasks[-1]
        await task
        assert after_called is True
        _background_tasks.remove(task)

    @pytest.mark.asyncio
    async def test_handles_partial_failure(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_services,
        )

        async def good() -> None:
            pass

        async def bad() -> None:
            raise RuntimeError("fail")

        _spawn_background_services([(good, "good"), (bad, "bad")])
        task = _background_tasks[-1]
        await task  # Should not raise
        _background_tasks.remove(task)

    @pytest.mark.asyncio
    async def test_after_failure_does_not_crash(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_services,
        )

        async def svc() -> None:
            pass

        async def bad_after() -> None:
            raise RuntimeError("after fail")

        _spawn_background_services([(svc, "svc")], after=bad_after, after_name="bad")
        task = _background_tasks[-1]
        await task  # Should not raise
        _background_tasks.remove(task)


# ---------------------------------------------------------------------------
# unified_startup
# ---------------------------------------------------------------------------


class TestUnifiedStartup:
    @pytest.mark.asyncio
    @patch("app.core.provider_registration.warmup_tools_cache", new_callable=AsyncMock)
    @patch(
        "app.core.provider_registration.init_websocket_consumer", new_callable=AsyncMock
    )
    @patch("app.core.provider_registration.get_vfs", new_callable=AsyncMock)
    @patch(
        "app.core.provider_registration.init_workflow_service", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.init_reminder_service", new_callable=AsyncMock
    )
    @patch("app.core.provider_registration.init_mongodb_async", new_callable=AsyncMock)
    @patch("app.core.provider_registration.providers")
    @patch("app.core.provider_registration._process_results")
    @patch("app.core.provider_registration.settings")
    async def test_main_app_hot_reload_enabled(
        self,
        mock_settings: MagicMock,
        mock_process: MagicMock,
        mock_providers: MagicMock,
        mock_mongo: AsyncMock,
        mock_reminder: AsyncMock,
        mock_workflow: AsyncMock,
        mock_vfs: AsyncMock,
        mock_ws: AsyncMock,
        mock_warmup: AsyncMock,
    ) -> None:
        from app.core.provider_registration import unified_startup

        mock_settings.ENABLE_LAZY_LOADING = True
        mock_providers.initialize_auto_providers = AsyncMock()

        # Make all registrations no-ops
        with (
            patch("app.core.provider_registration.init_postgresql_engine"),
            patch("app.core.provider_registration.init_rabbitmq_publisher"),
            patch("app.core.provider_registration.register_llm_providers"),
            patch("app.core.provider_registration.build_graphs"),
            patch("app.core.provider_registration.init_chroma"),
            patch("app.core.provider_registration.init_checkpointer_manager"),
            patch("app.core.provider_registration.init_tool_registry"),
            patch("app.core.provider_registration.init_composio_service"),
            patch("app.core.provider_registration.init_mcp_client_pool"),
            patch("app.core.provider_registration.init_embeddings"),
            patch("app.core.provider_registration.initialize_chroma_tools_store"),
            patch("app.core.provider_registration.initialize_chroma_triggers_store"),
            patch("app.core.provider_registration.init_cloudinary"),
            patch("app.core.provider_registration.validate_startup_requirements"),
            patch("app.core.provider_registration.init_vfs"),
            patch("app.core.provider_registration.init_posthog"),
            patch("app.core.provider_registration.init_opik"),
        ):
            await unified_startup("main_app")

        mock_process.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.core.provider_registration.warmup_tools_cache", new_callable=AsyncMock)
    @patch("app.core.provider_registration.get_vfs", new_callable=AsyncMock)
    @patch(
        "app.core.provider_registration.init_workflow_service", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.init_reminder_service", new_callable=AsyncMock
    )
    @patch("app.core.provider_registration.init_mongodb_async", new_callable=AsyncMock)
    @patch("app.core.provider_registration.providers")
    @patch("app.core.provider_registration._process_results")
    @patch("app.core.provider_registration.settings")
    async def test_arq_worker_no_websocket(
        self,
        mock_settings: MagicMock,
        mock_process: MagicMock,
        mock_providers: MagicMock,
        mock_mongo: AsyncMock,
        mock_reminder: AsyncMock,
        mock_workflow: AsyncMock,
        mock_vfs: AsyncMock,
        mock_warmup: AsyncMock,
    ) -> None:
        from app.core.provider_registration import unified_startup

        mock_settings.ENABLE_LAZY_LOADING = True
        mock_providers.initialize_auto_providers = AsyncMock()

        with (
            patch("app.core.provider_registration.init_postgresql_engine"),
            patch("app.core.provider_registration.init_rabbitmq_publisher"),
            patch("app.core.provider_registration.register_llm_providers"),
            patch("app.core.provider_registration.build_graphs"),
            patch("app.core.provider_registration.init_chroma"),
            patch("app.core.provider_registration.init_checkpointer_manager"),
            patch("app.core.provider_registration.init_tool_registry"),
            patch("app.core.provider_registration.init_composio_service"),
            patch("app.core.provider_registration.init_mcp_client_pool"),
            patch("app.core.provider_registration.init_embeddings"),
            patch("app.core.provider_registration.initialize_chroma_tools_store"),
            patch("app.core.provider_registration.initialize_chroma_triggers_store"),
            patch("app.core.provider_registration.init_cloudinary"),
            patch("app.core.provider_registration.validate_startup_requirements"),
            patch("app.core.provider_registration.init_vfs"),
            patch("app.core.provider_registration.init_posthog"),
            patch("app.core.provider_registration.init_opik"),
        ):
            await unified_startup("arq_worker")

        mock_process.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.core.provider_registration._spawn_background_services")
    @patch("app.core.provider_registration.warmup_tools_cache", new_callable=AsyncMock)
    @patch("app.core.provider_registration.get_vfs", new_callable=AsyncMock)
    @patch(
        "app.core.provider_registration.init_workflow_service", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.init_reminder_service", new_callable=AsyncMock
    )
    @patch("app.core.provider_registration.init_mongodb_async", new_callable=AsyncMock)
    @patch(
        "app.core.provider_registration.init_websocket_consumer", new_callable=AsyncMock
    )
    @patch("app.core.provider_registration.providers")
    @patch("app.core.provider_registration.settings")
    async def test_background_warmup_when_lazy_loading_disabled(
        self,
        mock_settings: MagicMock,
        mock_providers: MagicMock,
        mock_ws: AsyncMock,
        mock_mongo: AsyncMock,
        mock_reminder: AsyncMock,
        mock_workflow: AsyncMock,
        mock_vfs: AsyncMock,
        mock_warmup: AsyncMock,
        mock_spawn: MagicMock,
    ) -> None:
        from app.core.provider_registration import unified_startup

        mock_settings.ENABLE_LAZY_LOADING = False
        mock_providers.initialize_auto_providers = AsyncMock()

        with (
            patch("app.core.provider_registration.init_postgresql_engine"),
            patch("app.core.provider_registration.init_rabbitmq_publisher"),
            patch("app.core.provider_registration.register_llm_providers"),
            patch("app.core.provider_registration.build_graphs"),
            patch("app.core.provider_registration.init_chroma"),
            patch("app.core.provider_registration.init_checkpointer_manager"),
            patch("app.core.provider_registration.init_tool_registry"),
            patch("app.core.provider_registration.init_composio_service"),
            patch("app.core.provider_registration.init_mcp_client_pool"),
            patch("app.core.provider_registration.init_embeddings"),
            patch("app.core.provider_registration.initialize_chroma_tools_store"),
            patch("app.core.provider_registration.initialize_chroma_triggers_store"),
            patch("app.core.provider_registration.init_cloudinary"),
            patch("app.core.provider_registration.validate_startup_requirements"),
            patch("app.core.provider_registration.init_vfs"),
            patch("app.core.provider_registration.init_posthog"),
            patch("app.core.provider_registration.init_opik"),
        ):
            await unified_startup("main_app")

        mock_spawn.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.core.provider_registration.warmup_tools_cache", new_callable=AsyncMock)
    @patch("app.core.provider_registration.get_vfs", new_callable=AsyncMock)
    @patch(
        "app.core.provider_registration.init_workflow_service", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.init_reminder_service", new_callable=AsyncMock
    )
    @patch("app.core.provider_registration.init_mongodb_async", new_callable=AsyncMock)
    @patch("app.core.provider_registration.providers")
    @patch(
        "app.core.provider_registration._process_results",
        side_effect=RuntimeError("boom"),
    )
    @patch("app.core.provider_registration.settings")
    async def test_raises_runtime_error_on_failure(
        self,
        mock_settings: MagicMock,
        mock_process: MagicMock,
        mock_providers: MagicMock,
        mock_mongo: AsyncMock,
        mock_reminder: AsyncMock,
        mock_workflow: AsyncMock,
        mock_vfs: AsyncMock,
        mock_warmup: AsyncMock,
    ) -> None:
        from app.core.provider_registration import unified_startup

        mock_settings.ENABLE_LAZY_LOADING = True
        mock_providers.initialize_auto_providers = AsyncMock()

        with (
            patch("app.core.provider_registration.init_postgresql_engine"),
            patch("app.core.provider_registration.init_rabbitmq_publisher"),
            patch("app.core.provider_registration.register_llm_providers"),
            patch("app.core.provider_registration.build_graphs"),
            patch("app.core.provider_registration.init_chroma"),
            patch("app.core.provider_registration.init_checkpointer_manager"),
            patch("app.core.provider_registration.init_tool_registry"),
            patch("app.core.provider_registration.init_composio_service"),
            patch("app.core.provider_registration.init_mcp_client_pool"),
            patch("app.core.provider_registration.init_embeddings"),
            patch("app.core.provider_registration.initialize_chroma_tools_store"),
            patch("app.core.provider_registration.initialize_chroma_triggers_store"),
            patch("app.core.provider_registration.init_cloudinary"),
            patch("app.core.provider_registration.validate_startup_requirements"),
            patch("app.core.provider_registration.init_vfs"),
            patch("app.core.provider_registration.init_posthog"),
            patch("app.core.provider_registration.init_opik"),
        ):
            with pytest.raises(RuntimeError, match="startup failed"):
                await unified_startup("main_app")


# ---------------------------------------------------------------------------
# unified_shutdown
# ---------------------------------------------------------------------------


class TestUnifiedShutdown:
    @pytest.mark.asyncio
    @patch(
        "app.core.provider_registration.close_mcp_client_pool", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.close_checkpointer_manager",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_workflow_scheduler",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_reminder_scheduler",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_postgresql_async", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.close_websocket_async", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.close_publisher_async", new_callable=AsyncMock
    )
    async def test_main_app_shutdown(
        self,
        mock_pub: AsyncMock,
        mock_ws: AsyncMock,
        mock_pg: AsyncMock,
        mock_rem: AsyncMock,
        mock_wf: AsyncMock,
        mock_ckpt: AsyncMock,
        mock_mcp: AsyncMock,
    ) -> None:
        from app.core.provider_registration import unified_shutdown

        await unified_shutdown("main_app")
        mock_pub.assert_called_once()
        mock_ws.assert_called_once()
        mock_pg.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "app.core.provider_registration.close_mcp_client_pool", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.close_checkpointer_manager",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_workflow_scheduler",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_reminder_scheduler",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_postgresql_async", new_callable=AsyncMock
    )
    async def test_arq_worker_shutdown_no_websocket(
        self,
        mock_pg: AsyncMock,
        mock_rem: AsyncMock,
        mock_wf: AsyncMock,
        mock_ckpt: AsyncMock,
        mock_mcp: AsyncMock,
    ) -> None:
        from app.core.provider_registration import unified_shutdown

        await unified_shutdown("arq_worker")
        mock_pg.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "app.core.provider_registration.close_mcp_client_pool", new_callable=AsyncMock
    )
    @patch(
        "app.core.provider_registration.close_checkpointer_manager",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_workflow_scheduler",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_reminder_scheduler",
        new_callable=AsyncMock,
    )
    @patch(
        "app.core.provider_registration.close_postgresql_async",
        new_callable=AsyncMock,
        side_effect=RuntimeError("pg error"),
    )
    async def test_shutdown_logs_error_without_raising(
        self,
        mock_pg: AsyncMock,
        mock_rem: AsyncMock,
        mock_wf: AsyncMock,
        mock_ckpt: AsyncMock,
        mock_mcp: AsyncMock,
    ) -> None:
        from app.core.provider_registration import unified_shutdown

        # Should not raise even though pg fails
        await unified_shutdown("arq_worker")

    @pytest.mark.asyncio
    async def test_shutdown_cancels_background_tasks(self) -> None:
        from app.core.provider_registration import (
            _background_tasks,
            _spawn_background_task,
            unified_shutdown,
        )

        async def long_running() -> None:
            await asyncio.sleep(999)

        _spawn_background_task("long", long_running)

        with (
            patch(
                "app.core.provider_registration.close_mcp_client_pool",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.provider_registration.close_checkpointer_manager",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.provider_registration.close_workflow_scheduler",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.provider_registration.close_reminder_scheduler",
                new_callable=AsyncMock,
            ),
            patch(
                "app.core.provider_registration.close_postgresql_async",
                new_callable=AsyncMock,
            ),
        ):
            await unified_shutdown("arq_worker")

        # _background_tasks should be cleared
        assert len(_background_tasks) == 0
