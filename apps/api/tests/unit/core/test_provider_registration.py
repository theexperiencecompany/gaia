"""unified_startup wiring: a blocking boot honors each provider's declared strategy.

The lazy-provider auto-initializer runs as a blocking startup service. It must run
strict (so an ERROR-strategy provider that fails to initialize propagates) AND be
marked required (so that failure reaches _process_results instead of being logged
and swallowed). Together that turns a provider declared ERROR to fail loud — e.g.
tool_registry — into a boot abort rather than a server that comes up broken and
500s the first request. These pin that wiring; the strategy semantics themselves
live in test_lazy_loader.py.

The arq_worker context is used because it always takes the blocking path (the
main_app fast-start branch schedules warmup in the background instead).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core import provider_registration
from app.core.provider_registration import unified_startup

_MOD = "app.core.provider_registration"

# Eager services unified_startup runs before the auto-initializer; all stubbed to
# succeed so the only variable under test is the auto-initializer itself.
_EAGER_ENTRYPOINTS = (
    "register_lazy_providers",
    "init_mongodb_async",
    "init_reminder_service",
    "init_workflow_service",
    "init_system_subtree",
    "declare_outbound_topology_on_startup",
    "warmup_tools_cache",
)


@pytest.fixture
def auto_init_spy() -> Iterator[AsyncMock]:
    """Stub every eager startup service to succeed; yield the auto-initializer spy."""
    spy = AsyncMock(return_value=None)
    with ExitStack() as stack:
        stack.enter_context(patch.object(provider_registration, "register_lazy_providers"))
        for name in _EAGER_ENTRYPOINTS:
            if name == "register_lazy_providers":
                continue
            stack.enter_context(patch.object(provider_registration, name, AsyncMock()))
        # redis_cache and providers are objects; patch their methods.
        stack.enter_context(
            patch.object(provider_registration.redis_cache, "verify_connection", AsyncMock())
        )
        stack.enter_context(
            patch.object(provider_registration.providers, "aget", AsyncMock(return_value=None))
        )
        stack.enter_context(
            patch.object(provider_registration.providers, "initialize_auto_providers", spy)
        )
        yield spy


class TestBlockingStartupHonorsStrategy:
    async def test_the_auto_initializer_runs_strict(self, auto_init_spy: AsyncMock) -> None:
        await unified_startup("arq_worker")

        auto_init_spy.assert_awaited_once()
        assert auto_init_spy.await_args.kwargs.get("strict") is True, (
            "blocking startup must run auto-init strict so ERROR providers fail loud"
        )

    async def test_an_error_provider_failure_aborts_the_boot(
        self, auto_init_spy: AsyncMock
    ) -> None:
        # strict auto-init raises RuntimeError when an ERROR-strategy provider fails.
        # The service is marked required, so that must abort startup — not be swallowed.
        auto_init_spy.side_effect = RuntimeError("Auto-initialization failed for: tool_registry")

        with pytest.raises(RuntimeError, match="arq_worker startup failed"):
            await unified_startup("arq_worker")

    async def test_a_best_effort_service_failing_still_boots(
        self, auto_init_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Counterpart: a non-required service failing must NOT abort — proving the
        # abort in the test above comes from required=True, not from any failure.
        boom: Any = AsyncMock(side_effect=RuntimeError("juicefs down"))
        monkeypatch.setattr(provider_registration, "init_system_subtree", boom)

        await unified_startup("arq_worker")  # must not raise

        auto_init_spy.assert_awaited_once()


class TestMainAppRegistersTheBroadcastListener:
    async def test_only_the_web_app_subscribes_to_the_broadcast_fanout(
        self, auto_init_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only the web app holds user WebSockets, so only it registers the Redis
        # broadcast listener — and it must be func + name + required exactly, or a
        # replica silently stops delivering pushes.
        monkeypatch.setattr(provider_registration.settings, "ENABLE_LAZY_LOADING", True)
        monkeypatch.setattr(provider_registration, "init_websocket_broadcast_listener", AsyncMock())
        monkeypatch.setattr(provider_registration, "resync_stale_user_workspaces", AsyncMock())
        monkeypatch.setattr(provider_registration, "spawn_logged_task", lambda *a, **k: None)

        real = provider_registration.StartupService
        seen: list[tuple] = []

        def _spy(func, name, required):
            seen.append((func, name, required))
            return real(func, name, required)

        monkeypatch.setattr(provider_registration, "StartupService", _spy)

        await unified_startup("main_app")

        listener = provider_registration.init_websocket_broadcast_listener
        entries = [(f, n, r) for (f, n, r) in seen if f is listener]
        assert len(entries) == 1
        _func, name, required = entries[0]
        assert name == "websocket_broadcast_listener"
        assert required is True

    async def test_the_worker_does_not_register_the_broadcast_listener(
        self, auto_init_spy: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider_registration, "init_websocket_broadcast_listener", AsyncMock())
        real = provider_registration.StartupService
        seen: list[tuple] = []

        def _spy(func, name, required):
            seen.append((func, name, required))
            return real(func, name, required)

        monkeypatch.setattr(provider_registration, "StartupService", _spy)

        await unified_startup("arq_worker")

        listener = provider_registration.init_websocket_broadcast_listener
        assert [entry for entry in seen if entry[0] is listener] == []
