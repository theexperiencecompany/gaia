"""Composio webhook routing as the platform experiences it: every event finds its handler.

The HTTP pipeline (signature, dedupe, HTTP-level fan-out) is proven in
tests/integration/api/test_webhook_composio_pipeline.py. What nothing proved
is the registry wiring underneath it: a handler whose SUPPORTED event types
were never registered resolves to None, the route acks the delivery, and the
event is silently dropped — a green 200 with no workflow ever queued. That
failure is invisible unless something asserts the registry covers every
handler the codebase ships.

Real: the trigger registry + every shipped handler's declared event types and
trigger names, _process_webhook_event, _expire_connection. Doubled: only the
downstream queues and stores the fanned-out work lands in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import importlib
import inspect
import pkgutil
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints import webhook_composio
from app.api.v1.endpoints.webhook_composio import (
    _expire_connection,
    _process_webhook_event,
)
from app.models.integration_models import IntegrationAccount
from app.models.webhook_models import ComposioWebhookEvent
from app.services.integrations.integration_expiry import AccountExpired
from app.services.triggers import (
    get_handler_by_event,
    get_handler_by_name,
    trigger_registry,
)
from app.services.triggers.base import TriggerHandler

pytestmark = pytest.mark.e2e

MODULE = "app.api.v1.endpoints.webhook_composio"
USER_ID = "user-1"


def _event(**overrides: Any) -> ComposioWebhookEvent:
    data = {
        "type": "GMAIL_NEW_GMAIL_MESSAGE",
        "timestamp": "2026-08-10T05:44:33Z",
        "data": {"payload": {"message_id": "msg-1"}},
        "connection_id": "conn-1",
        "connection_nano_id": "nano-1",
        "trigger_nano_id": "ti_nano",
        "trigger_id": "uuid-1",
        "user_id": USER_ID,
    }
    data.update(overrides)
    return ComposioWebhookEvent(**data)


class TestEveryShippedHandlerIsReachable:
    def test_each_declared_event_type_resolves_to_its_handler(self) -> None:
        handlers = list({id(h): h for h in trigger_registry._event_handlers.values()}.values())
        assert handlers, "registry is empty — handlers never registered"
        for handler in handlers:
            assert handler.event_types, type(handler).__name__
            for event_type in handler.event_types:
                assert get_handler_by_event(event_type) is handler, event_type

    def test_no_shipped_handler_is_missing_from_the_registry(self) -> None:
        """A handler file that is never registered is acked into the void, so enumerate classes independently of the registry."""
        handlers_pkg = importlib.import_module("app.services.triggers.handlers")

        shipped: list[type] = []
        for module_info in pkgutil.iter_modules(handlers_pkg.__path__):
            module = __import__(f"{handlers_pkg.__name__}.{module_info.name}", fromlist=["*"])
            for obj in vars(module).values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, TriggerHandler)
                    and obj is not TriggerHandler
                    and not inspect.isabstract(obj)
                ):
                    shipped.append(obj)

        assert shipped, "no handler classes found under handlers/"
        for cls in shipped:
            # Names are mandatory; events are optional (the poll strategy
            # matches by trigger id and declares none).
            names = getattr(cls, "SUPPORTED_TRIGGERS", [])
            assert names, f"{cls.__name__} declares no trigger names"
            for name in names:
                assert get_handler_by_name(name) is not None, name
            for event_type in getattr(cls, "SUPPORTED_EVENTS", set()):
                assert get_handler_by_event(event_type) is not None, event_type

    def test_each_declared_trigger_name_resolves_to_its_handler(self) -> None:
        handlers = list({id(h): h for h in trigger_registry._name_handlers.values()}.values())
        assert handlers, "registry is empty — handlers never registered"
        for handler in handlers:
            for name in handler.trigger_names:
                assert get_handler_by_name(name) is handler, name

    def test_unknown_event_resolves_to_none_and_is_dropped_by_design(self) -> None:
        assert get_handler_by_event("SOME_EVENT_NOBODY_SHIPS") is None


class TestProcessWebhookEvent:
    @pytest.fixture(autouse=True)
    def _single_account(self) -> Iterator[None]:
        with patch(f"{MODULE}.event_account_name", AsyncMock(return_value=None)):
            yield

    async def test_nano_id_is_preferred_over_internal_id(self) -> None:
        handler = AsyncMock()
        await _process_webhook_event(handler, _event())

        handler.process_event.assert_awaited_once()
        kwargs = handler.process_event.await_args.kwargs
        assert kwargs["trigger_id"] == "ti_nano"
        assert kwargs["user_id"] == USER_ID
        assert kwargs["event_type"] == "GMAIL_NEW_GMAIL_MESSAGE"
        assert kwargs["data"]["payload"]["message_id"] == "msg-1"

    async def test_internal_id_is_used_when_no_nano_id(self) -> None:
        handler = AsyncMock()
        await _process_webhook_event(handler, _event(trigger_nano_id=""))

        assert handler.process_event.await_args.kwargs["trigger_id"] == "uuid-1"

    async def test_handler_timeout_is_swallowed_not_raised(self) -> None:
        """The route already acked Composio; a slow handler must not 500 the ack."""
        handler = AsyncMock()
        handler.process_event = AsyncMock(side_effect=TimeoutError())
        await _process_webhook_event(handler, _event())  # must not raise

    async def test_handler_crash_is_swallowed_not_raised(self) -> None:
        handler = AsyncMock()
        handler.process_event = AsyncMock(side_effect=RuntimeError("queue down"))
        await _process_webhook_event(handler, _event())  # must not raise


class TestExpireConnection:
    async def test_the_expiry_runs_first_and_decides_whether_to_pause(self) -> None:
        order: list[str] = []
        expired = AccountExpired(
            account=IntegrationAccount(connected_account_id="ca-1", label="me", status="expired"),
            account_count=1,
            was_primary=True,
            integration_expired=True,
        )
        expire = AsyncMock(side_effect=lambda *a, **k: (order.append("expire"), expired)[1])
        pause = AsyncMock(side_effect=lambda *a: (order.append("pause"), ["Standup"])[1])
        with (
            patch(f"{MODULE}.expire_account", expire),
            patch(f"{MODULE}.pause_workflows_for_expired_integration", pause),
            patch(f"{MODULE}.announce_account_expiry", AsyncMock()) as announce,
        ):
            await _expire_connection(USER_ID, "googlecalendar", "revoked", "ca-1")

        assert order == ["expire", "pause"]
        announce.assert_awaited_once_with(
            USER_ID, "googlecalendar", expired, ["Standup"], "revoked"
        )

    async def test_expiry_timeout_is_swallowed_not_raised(self) -> None:
        with (
            patch(f"{MODULE}.expire_account", AsyncMock(side_effect=TimeoutError())),
        ):
            await _expire_connection(USER_ID, "googlecalendar", None, "ca-1")  # no raise

    async def test_real_sleeping_handler_hits_the_real_timeout(self) -> None:
        """Without the timeout a hung queue blocks the expiry task forever."""

        async def _hang(*args: Any, **kwargs: Any) -> None:
            await asyncio.sleep(3600)

        with (
            patch(f"{MODULE}.WEBHOOK_TASK_TIMEOUT", 0.01),
            patch(f"{MODULE}.expire_account", AsyncMock(side_effect=_hang)),
        ):
            await _expire_connection(USER_ID, "googlecalendar", None, "ca-1")  # no raise

    def test_module_exports_reference_real_functions(self) -> None:
        assert webhook_composio._process_webhook_event is _process_webhook_event
        assert webhook_composio._expire_connection is _expire_connection
