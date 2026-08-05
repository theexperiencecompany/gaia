"""The contract every Composio custom tool has to satisfy to work at all.

75 custom tools across 23 toolkits are registered by decorator, and the SDK
validates almost nothing about them at registration time. Each invariant below
fails the same way in production — the tool registers, appears in the model's
tool list, gets called, and returns something useless — so none of them
announces itself as a bug. They are cheap to check once, over every tool, here.

Registration needs no credentials and no network: the client is constructed with
a throwaway key and the decorator only records the function.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect

from composio import Composio
import pytest

from app.services.composio.custom_tools.registry import CustomToolsRegistry

# Imported for its side effect: app.patches installs the custom-tool schema
# patches at import time, and the contracts asserted below depend on them.
importlib.import_module("app.patches")

pytestmark = pytest.mark.unit

#: The signature the SDK calls a toolkit-bound custom tool with
#: (``CustomTool.invoke_trusted``). A tool declaring anything else raises a
#: TypeError at call time, long after registration reported success.
REQUIRED_PARAMS = ["request", "execute_request", "auth_credentials"]


@pytest.fixture(scope="module")
def registered() -> tuple[dict, CustomToolsRegistry]:
    """Every custom tool the app registers, and the registry that did it."""
    client = Composio(api_key="test-key-not-real")  # pragma: allowlist secret
    registry = CustomToolsRegistry()
    registry.initialize(client)
    return client.tools._custom_tools.custom_tools_registry, registry


class TestNoToolIsAsync:
    def test_every_custom_tool_is_a_sync_function(self, registered):
        """The one that silently corrupts results.

        ``CustomTool.invoke_trusted`` calls ``self.f(...)`` and returns without
        awaiting. An ``async def`` tool therefore registers fine, "executes"
        with no error, and hands back an un-awaited coroutine wrapped as
        ``successful: True`` — the model reads a coroutine repr as its result
        and the real API call never happens. The only runtime signal is a
        RuntimeWarning nobody is watching.

        The SDK does reject async tools, but on the ``experimental.tool`` /
        tool-router class — a different path. ``composio.tools.custom_tool``,
        which is what this app uses, has no such guard. Anyone grepping for
        ``iscoroutinefunction`` finds those hits and concludes it is handled.
        """
        tools, _ = registered

        offenders = [slug for slug, tool in tools.items() if asyncio.iscoroutinefunction(tool.f)]

        assert offenders == [], (
            "these custom tools are async; they will return an un-awaited "
            f"coroutine as a successful result: {offenders}"
        )

    def test_no_tool_returns_an_awaitable_by_being_a_partial_of_one(self, registered):
        """Same corruption, one indirection further out."""
        tools, _ = registered

        offenders = [
            slug
            for slug, tool in tools.items()
            if inspect.isawaitable(getattr(tool.f, "func", None))
            or asyncio.iscoroutinefunction(getattr(tool.f, "func", None))
        ]

        assert offenders == []


class TestSignatures:
    def test_every_toolkit_tool_takes_the_parameters_the_sdk_passes(self, registered):
        """``invoke_trusted`` calls toolkit-bound tools with exactly
        ``request``, ``execute_request`` and ``auth_credentials`` as keywords.
        A tool that renames or omits one raises TypeError the first time a user
        triggers it — never at registration, never in CI."""
        tools, _ = registered
        wrong = {}

        for slug, tool in tools.items():
            if tool.toolkit is None:
                continue
            params = list(inspect.signature(tool.f).parameters)
            if params != REQUIRED_PARAMS:
                wrong[slug] = params

        assert wrong == {}, f"custom tools with a signature the SDK cannot call: {wrong}"

    def test_every_tool_declares_a_request_model(self, registered):
        """``invoke_trusted`` validates the LLM's arguments through it. Without
        one there is nothing between model-authored JSON and the provider."""
        tools, _ = registered

        assert [slug for slug, tool in tools.items() if tool.request_model is None] == []


class TestRegistryAgreesWithReality:
    def test_every_declared_tool_name_actually_registered(self, registered):
        """Each register function returns a hardcoded list of slugs, and that
        list is what ``get_tools`` asks Composio for. A name that drifts from
        its decorated function — a rename, a typo — is requested forever and
        never found, so the integration loses that action with no error."""
        tools, registry = registered
        declared = {
            name
            for toolkit, _ in registry._toolkit_registrations()
            for name in registry.get_tool_names(toolkit)
        }

        assert declared - set(tools) == set(), (
            f"declared but never registered: {sorted(declared - set(tools))}"
        )

    def test_every_registered_tool_is_declared(self, registered):
        """The reverse drift: a tool that exists but is not in its toolkit's
        list is dead weight — never offered to any model."""
        tools, registry = registered
        declared = {
            name
            for toolkit, _ in registry._toolkit_registrations()
            for name in registry.get_tool_names(toolkit)
        }

        assert set(tools) - declared == set(), (
            f"registered but never offered: {sorted(set(tools) - declared)}"
        )

    def test_no_slug_is_claimed_by_two_toolkits(self, registered):
        """Registration is a dict keyed by slug, so a duplicate silently
        replaces the earlier tool — the losing toolkit's action just stops
        working, and which one loses depends on registration order."""
        _, registry = registered
        seen: dict[str, str] = {}
        clashes: dict[str, tuple[str, str]] = {}

        for toolkit, _ in registry._toolkit_registrations():
            for name in registry.get_tool_names(toolkit):
                if name in seen:
                    clashes[name] = (seen[name], toolkit)
                seen[name] = toolkit

        assert clashes == {}, f"slug claimed by two toolkits: {clashes}"

    def test_every_configured_toolkit_registered_something(self, registered):
        """A toolkit whose register function returns nothing is a silent
        regression: the integration still connects, and has no custom tools."""
        _, registry = registered

        empty = [
            toolkit
            for toolkit, _ in registry._toolkit_registrations()
            if not registry.get_tool_names(toolkit)
        ]

        assert empty == [], f"toolkits that registered no custom tools: {empty}"

    def test_initialization_is_idempotent(self, registered):
        """``initialize`` runs on every ComposioService construction. If it
        re-registered, slugs would collide with themselves and the count would
        drift upward across the process lifetime."""
        tools, registry = registered
        before = len(tools)

        registry.initialize(registry._composio)

        assert len(tools) == before
