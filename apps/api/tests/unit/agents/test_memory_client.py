"""Behaviour spec for app.agents.memory.client — MemoryClientManager.

UNIT: app/agents/memory/client.py :: MemoryClientManager.get_client / reset / __init__
EXPECTED:
  A lazily-initialised, cached holder for the mem0 AsyncMemoryClient that
  enables graph memory exactly once per successful client build.

MECHANISM (get_client):
  if self._client is None:
      client = AsyncMemoryClient(api_key=..., org_id=..., project_id=...)   # from settings
      if not self._graph_enabled:
          try:
              await client.project.update(enable_graph=True)
              self._graph_enabled = True
          except Exception as e:
              print(f"Warning: Could not enable graph memory: {e}")
      self._client = client
  return self._client

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - __init__ starts with _client=None and _graph_enabled=False (no premature client). [init contract]
  - AsyncMemoryClient is constructed with the THREE settings values as
    api_key / org_id / project_id — not constants, not the wrong field.   [config contract]
  - on the first call the returned object IS the constructed client.        [return shape]
  - the same client instance is cached: a second call returns the identical
    object and does NOT construct a second client (`if self._client is None`). [caching branch]
  - graph memory is enabled via project.update(enable_graph=True) exactly
    once on success, and _graph_enabled flips to True.                      [graph-enable success path]
  - once _graph_enabled is True, rebuilding the client (cache cleared) does
    NOT call project.update again (`if not self._graph_enabled` guard).     [guard branch]
  - if project.update raises, get_client still returns the client, swallows
    the error, prints the warning carrying the exception text, and leaves
    _graph_enabled False so it retries on the next build.                   [error path + retry]
  - reset() clears _client to None but preserves _graph_enabled.            [reset contract]
  - the module-level singleton is a MemoryClientManager.                    [export contract]

EQUIVALENT MUTANTS (allowed survivors, justified):
  - L9  const_str "Manages memory client..." -> ""  : class docstring, no runtime effect.
  - L16 const_str "Get the properly..."      -> ""  : method docstring, no runtime effect.
  - L38 const_str "Reset the client..."      -> ""  : method docstring, no runtime effect.
  (Docstrings are never read at runtime; nothing observable changes. The
  print-warning f-string on L31 is NOT equivalent and is killed by
  test_graph_enable_failure_prints_warning_and_retries.)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.memory.client import MemoryClientManager, memory_client_manager


def _wire_instance(mock_client_cls: MagicMock) -> MagicMock:
    """Wire the patched AsyncMemoryClient class to return a stub with an async project.update."""
    instance = MagicMock(name="AsyncMemoryClientInstance")
    instance.project = MagicMock()
    instance.project.update = AsyncMock()
    mock_client_cls.return_value = instance
    return instance


class TestInitialState:
    def test_starts_empty_with_graph_disabled(self) -> None:
        mgr = MemoryClientManager()
        assert mgr._client is None
        assert mgr._graph_enabled is False


class TestGetClient:
    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_constructs_client_with_settings_credentials(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """The client is built from the three settings values, mapped to the right kwargs."""
        mock_settings.MEM0_API_KEY = "api-key-123"  # pragma: allowlist secret
        mock_settings.MEM0_ORG_ID = "org-456"
        mock_settings.MEM0_PROJECT_ID = "proj-789"
        instance = MagicMock()
        instance.project.update = AsyncMock()
        mock_client_cls.return_value = instance

        mgr = MemoryClientManager()
        returned = await mgr.get_client()

        mock_client_cls.assert_called_once_with(
            api_key="api-key-123",  # pragma: allowlist secret
            org_id="org-456",
            project_id="proj-789",
        )
        assert returned is instance
        assert mgr._client is instance

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_enables_graph_memory_once_on_success(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """Graph memory is turned on via project.update(enable_graph=True); flag flips True."""
        mock_settings.MEM0_API_KEY = "k"  # pragma: allowlist secret
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"
        instance = _wire_instance(mock_client_cls)

        mgr = MemoryClientManager()
        await mgr.get_client()

        instance.project.update.assert_awaited_once_with(enable_graph=True)
        assert mgr._graph_enabled is True

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_caches_instance_across_calls(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """Second call returns the same object and does not build a second client."""
        mock_settings.MEM0_API_KEY = "k"  # pragma: allowlist secret
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"
        instance = MagicMock()
        instance.project.update = AsyncMock()
        mock_client_cls.return_value = instance

        mgr = MemoryClientManager()
        first = await mgr.get_client()
        second = await mgr.get_client()

        assert first is second is instance
        mock_client_cls.assert_called_once()
        # Cached path must NOT re-run graph enabling.
        instance.project.update.assert_awaited_once()

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_graph_enable_skipped_when_already_enabled(
        self, mock_settings: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        """When _graph_enabled is already True, rebuilding the client skips project.update."""
        mock_settings.MEM0_API_KEY = "k"  # pragma: allowlist secret
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"
        instance = MagicMock()
        instance.project.update = AsyncMock()
        mock_client_cls.return_value = instance

        mgr = MemoryClientManager()
        await mgr.get_client()
        # Drop the cached client but keep the enabled flag, forcing a rebuild.
        mgr._client = None
        returned = await mgr.get_client()

        assert returned is instance
        # A second AsyncMemoryClient was built, but graph enabling ran only the first time.
        assert mock_client_cls.call_count == 2
        instance.project.update.assert_awaited_once()

    @patch("app.agents.memory.client.AsyncMemoryClient")
    @patch("app.agents.memory.client.settings")
    async def test_graph_enable_failure_prints_warning_and_retries(
        self,
        mock_settings: MagicMock,
        mock_client_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A failed enable_graph is swallowed (client still returned), warned about, and retried."""
        mock_settings.MEM0_API_KEY = "k"  # pragma: allowlist secret
        mock_settings.MEM0_ORG_ID = "o"
        mock_settings.MEM0_PROJECT_ID = "p"
        instance = MagicMock()
        instance.project.update = AsyncMock(side_effect=RuntimeError("graph boom"))
        mock_client_cls.return_value = instance

        mgr = MemoryClientManager()
        returned = await mgr.get_client()

        # Error swallowed: client returned, flag stays False so the next build retries.
        assert returned is instance
        assert mgr._graph_enabled is False
        warning = capsys.readouterr().out
        assert "Warning: Could not enable graph memory:" in warning
        assert "graph boom" in warning

        # Retry on the next build now that update succeeds.
        mgr._client = None
        instance.project.update = AsyncMock()
        await mgr.get_client()

        instance.project.update.assert_awaited_once_with(enable_graph=True)
        assert mgr._graph_enabled is True


class TestReset:
    def test_clears_client_but_keeps_graph_flag(self) -> None:
        """reset() drops the cached client yet preserves the graph-enabled flag."""
        mgr = MemoryClientManager()
        mgr._client = MagicMock()
        mgr._graph_enabled = True

        mgr.reset()

        assert mgr._client is None
        assert mgr._graph_enabled is True


class TestModuleSingleton:
    def test_global_instance_is_manager(self) -> None:
        assert isinstance(memory_client_manager, MemoryClientManager)
