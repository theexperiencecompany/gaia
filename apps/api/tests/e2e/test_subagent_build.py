"""What a specialized subagent is actually built with.

A provider subagent declares the tools it always needs bound up front —
`auto_bind_tools` and `extra_initial_tools` in `oauth_config.py`. Gmail, for
instance, declares six Composio tools plus `query_json`/`grep`, and those
declarations are the whole reason a handoff to Gmail can read an inbox without
first paying for a retrieval round-trip.

The build filters those declarations against the tools it actually resolved.
The filter is correct — you cannot bind a tool that does not exist — but a
declaration that resolves to nothing is a configuration or registration fault,
not a normal outcome, and it must not pass in silence. A Gmail subagent that
builds with none of its Gmail tools looks healthy and can do nothing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.core.subagents import base_subagent
from app.agents.core.subagents.base_subagent import (
    build_scoped_tool_dict,
    resolve_declared_tools,
)

pytestmark = pytest.mark.e2e

#: Gmail's declared auto-bind set (see oauth_config.py). Their Composio category
#: is only registered once the integration is provisioned, so in a bare process
#: none of them resolve — which is exactly the silent-degradation case.
GMAIL_AUTO_BIND = [
    "GMAIL_CUSTOM_GATHER_CONTEXT",
    "GMAIL_FETCH_MESSAGES",
    "GMAIL_FETCH_THREAD",
]


@pytest.fixture
async def registry(real_tool_registry):
    from app.core.lazy_loader import providers

    return await providers.aget("tool_registry")


class TestScopedToolDict:
    async def test_a_provider_space_with_no_registered_category_resolves_none_of_its_tools(
        self, registry
    ):
        """The precondition for everything below: until Composio registration
        runs, a provider's own tools simply are not there."""
        scoped, _ = build_scoped_tool_dict(registry, "gmail", None, True)

        assert [name for name in GMAIL_AUTO_BIND if name in scoped] == []

    async def test_the_always_available_tools_are_still_present(self, registry):
        """A subagent always gets memory, file and shell access regardless of its
        provider, so an empty provider category is not an empty toolset — which
        is why the degradation is invisible."""
        scoped, _ = build_scoped_tool_dict(registry, "gmail", None, True)

        assert {"search_memory", "read", "bash"} <= set(scoped)

    async def test_finish_task_is_included_when_asked_for(self, registry):
        scoped, initial = build_scoped_tool_dict(registry, "gmail", None, True)

        assert "finish_task" in scoped
        assert "finish_task" in initial

    async def test_finish_task_is_absent_when_not_asked_for(self, registry):
        """Subagents that terminate on a plain reply must not be handed a tool
        that ends the run."""
        scoped, initial = build_scoped_tool_dict(registry, "gmail", None, False)

        assert "finish_task" not in scoped
        assert "finish_task" not in initial


class TestDeclaredToolResolution:
    """``resolve_declared_tools`` is the one place a declaration meets reality."""

    def test_declared_tools_that_exist_are_kept_in_order(self):
        scoped = {"a": object(), "b": object(), "c": object()}

        assert resolve_declared_tools(["c", "a"], scoped, provider="gmail", kind="auto_bind") == [
            "c",
            "a",
        ]

    def test_a_missing_declaration_is_reported_not_swallowed(self):
        """The failure this exists to prevent: every declared tool dropped, the
        subagent built anyway, and nothing said so. The message must name the
        provider and the missing tools, because the cause is always upstream —
        a category that never registered, or a renamed tool slug."""
        scoped = {"read": object()}

        with patch.object(base_subagent, "log") as mock_log:
            kept = resolve_declared_tools(
                GMAIL_AUTO_BIND, scoped, provider="gmail", kind="auto_bind"
            )

        assert kept == []
        assert mock_log.warning.called, "a fully-dropped declaration was silent"
        kwargs = mock_log.warning.call_args.kwargs
        assert kwargs.get("provider") == "gmail"
        assert kwargs.get("missing_tools") == sorted(GMAIL_AUTO_BIND)

    def test_a_partially_missing_declaration_reports_only_what_is_missing(self):
        scoped = {"GMAIL_FETCH_MESSAGES": object()}

        with patch.object(base_subagent, "log") as mock_log:
            kept = resolve_declared_tools(
                GMAIL_AUTO_BIND, scoped, provider="gmail", kind="auto_bind"
            )

        assert kept == ["GMAIL_FETCH_MESSAGES"]
        missing = mock_log.warning.call_args.kwargs["missing_tools"]
        assert missing == ["GMAIL_CUSTOM_GATHER_CONTEXT", "GMAIL_FETCH_THREAD"]
        assert mock_log.warning.call_args.kwargs["resolved_tools"] == ["GMAIL_FETCH_MESSAGES"]

    def test_declaring_nothing_is_not_a_warning(self):
        """Most subagents declare no auto-bind set at all; that is normal."""
        with patch.object(base_subagent, "log") as mock_log:
            assert (
                resolve_declared_tools(None, {"read": object()}, provider="x", kind="auto_bind")
                == []
            )
            assert (
                resolve_declared_tools([], {"read": object()}, provider="x", kind="auto_bind") == []
            )

        assert not mock_log.warning.called

    def test_everything_resolving_is_not_a_warning(self):
        """Control: without it, warning unconditionally would satisfy the tests
        above."""
        scoped = {name: object() for name in GMAIL_AUTO_BIND}

        with patch.object(base_subagent, "log") as mock_log:
            kept = resolve_declared_tools(
                GMAIL_AUTO_BIND, scoped, provider="gmail", kind="auto_bind"
            )

        assert kept == GMAIL_AUTO_BIND
        assert not mock_log.warning.called
