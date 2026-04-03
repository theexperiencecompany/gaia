"""Unit tests for app.agents.memory.client — MemoryClientManager."""

from unittest.mock import AsyncMock, MagicMock, patch


from app.agents.memory.client import MemoryClientManager, memory_client_manager


class TestMemoryClientManager:
    """Tests for MemoryClientManager lifecycle and configuration."""

    def test_initial_state(self) -> None:
        """Manager starts with no client and graph disabled."""
        mgr = MemoryClientManager()
        assert mgr._client is None
        assert mgr._graph_enabled is False

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_get_client_creates_client_on_first_call(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """First call to get_client should instantiate AsyncMemoryClient."""
        mock_settings.MEM0_API_KEY = "test-key"
        mock_settings.MEM0_ORG_ID = "test-org"
        mock_settings.MEM0_PROJECT_ID = "test-project"

        mock_instance = MagicMock()
        mock_instance.project = MagicMock()
        mock_instance.project.update = AsyncMock()
        mock_client_cls.return_value = mock_instance

        mgr = MemoryClientManager()
        client = await mgr.get_client()

        mock_client_cls.assert_called_once_with(
            api_key="test-key",
            org_id="test-org",
            project_id="test-project",
        )
        assert client is mock_instance

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_get_client_enables_graph_memory(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """get_client should call project.update(enable_graph=True)."""
        mock_settings.MEM0_API_KEY = "k"
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"

        mock_instance = MagicMock()
        mock_instance.project = MagicMock()
        mock_instance.project.update = AsyncMock()
        mock_client_cls.return_value = mock_instance

        mgr = MemoryClientManager()
        await mgr.get_client()

        mock_instance.project.update.assert_awaited_once_with(enable_graph=True)
        assert mgr._graph_enabled is True

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_get_client_caches_instance(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """Subsequent calls to get_client should return the same instance."""
        mock_settings.MEM0_API_KEY = "k"
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"

        mock_instance = MagicMock()
        mock_instance.project = MagicMock()
        mock_instance.project.update = AsyncMock()
        mock_client_cls.return_value = mock_instance

        mgr = MemoryClientManager()
        first = await mgr.get_client()
        second = await mgr.get_client()

        assert first is second
        # Only created once
        mock_client_cls.assert_called_once()

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_get_client_graph_enable_failure_does_not_crash(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """If enable_graph fails, get_client should still return the client."""
        mock_settings.MEM0_API_KEY = "k"
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"

        mock_instance = MagicMock()
        mock_instance.project = MagicMock()
        mock_instance.project.update = AsyncMock(
            side_effect=RuntimeError("network error")
        )
        mock_client_cls.return_value = mock_instance

        mgr = MemoryClientManager()
        client = await mgr.get_client()

        assert client is mock_instance
        # graph_enabled stays False because of the exception
        assert mgr._graph_enabled is False

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_get_client_does_not_retry_graph_enable_after_success(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """Once graph is enabled, subsequent get_client calls skip project.update."""
        mock_settings.MEM0_API_KEY = "k"
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"

        mock_instance = MagicMock()
        mock_instance.project = MagicMock()
        mock_instance.project.update = AsyncMock()
        mock_client_cls.return_value = mock_instance

        mgr = MemoryClientManager()
        await mgr.get_client()
        # Reset client to force re-creation, but graph_enabled is True
        mgr._client = None
        await mgr.get_client()

        # project.update should only have been called once (first time)
        mock_instance.project.update.assert_awaited_once()

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_get_client_retries_graph_enable_after_failure(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """If graph enable failed previously, next get_client should try again."""
        mock_settings.MEM0_API_KEY = "k"
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"

        mock_instance = MagicMock()
        mock_instance.project = MagicMock()
        mock_instance.project.update = AsyncMock(side_effect=RuntimeError("fail"))
        mock_client_cls.return_value = mock_instance

        mgr = MemoryClientManager()
        await mgr.get_client()
        assert mgr._graph_enabled is False

        # Now reset and fix the update
        mgr._client = None
        mock_instance.project.update = AsyncMock()  # no longer fails
        await mgr.get_client()

        assert mgr._graph_enabled is True

    def test_reset_clears_client(self) -> None:
        """reset() should set _client to None."""
        mgr = MemoryClientManager()
        mgr._client = MagicMock()
        mgr.reset()
        assert mgr._client is None

    def test_reset_does_not_clear_graph_enabled(self) -> None:
        """reset() only clears _client, not _graph_enabled."""
        mgr = MemoryClientManager()
        mgr._graph_enabled = True
        mgr.reset()
        # graph_enabled persists across resets
        assert mgr._graph_enabled is True

    def test_global_instance_exists(self) -> None:
        """Module-level memory_client_manager should be a MemoryClientManager."""
        assert isinstance(memory_client_manager, MemoryClientManager)
