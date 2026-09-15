"""Runs a Composio custom-tool body through the real dispatch chain (plan §2.8): seam B (execute_tool) must be patched at each importing module or it silently no-ops, and stubbing only seam A still reaches the network unless seam C's auth-credentials fetch is stubbed too."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

from composio import Composio
import pytest

from app.services.composio.custom_tools.registry import CustomToolsRegistry

# Imported for its side effect: app.patches installs the custom-tool schema
# patches at import time, and the contracts asserted below depend on them.
importlib.import_module("app.patches")

pytestmark = pytest.mark.e2e

USER = "user-1"


@pytest.fixture(scope="module")
def tools() -> dict[str, Any]:
    client = Composio(api_key="test-key-not-real")  # pragma: allowlist secret
    CustomToolsRegistry().initialize(client)
    return client.tools._custom_tools.custom_tools_registry


@pytest.fixture
def gathered(tools):
    """Notion's context tool, with seam C stubbed and seam B recorded.

    Notion is the sample because its body goes through execute_tool (seam B)
    — the hosted-execute path shared by github, slack, todoist and asana.
    """
    tool = tools["NOTION_CUSTOM_GATHER_CONTEXT"]
    seam_c = MagicMock(return_value={"user_id": USER, "token": "secret"})
    calls: list[tuple[str, dict[str, Any], str]] = []

    def fake_execute(tool_name: str, params: dict[str, Any], user_id: str, *a, **k):
        calls.append((tool_name, params, user_id))
        return {"results": [{"id": "page-1", "title": "Roadmap"}]}

    with (
        patch.object(tool, "_CustomTool__get_auth_credentials", seam_c),
        patch("app.agents.tools.integrations.notion_tool.execute_tool", fake_execute),
    ):
        yield tool, seam_c, calls


class TestABodyActuallyRuns:
    def test_the_tool_body_executes_and_returns_its_own_shape(self, gathered):
        """End to end through invoke_trusted on the real registered function, not a mock: validates, fetches auth, runs the body, returns the result."""
        tool, _, calls = gathered

        result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert calls, "the tool body never reached the provider call"
        assert result == {"relevant_pages": [{"id": "page-1", "title": "Roadmap"}]}

    def test_the_result_is_not_a_coroutine(self, gathered):
        """The failure mode the sync guard exists for, asserted on a real invocation rather than on the function's type."""
        import inspect

        tool, _, _ = gathered

        assert not inspect.isawaitable(tool.invoke_trusted(user_id=USER, request_kwargs={}))

    def test_the_provider_call_carries_the_invoking_user(self, gathered):
        """The tool body must thread the invoking user through to the provider, or a wrong/missing user reads another account's data."""
        tool, _, calls = gathered

        tool.invoke_trusted(user_id=USER, request_kwargs={})

        _, _, called_with_user = calls[0]
        assert called_with_user == USER


class TestSeamC:
    def test_auth_is_fetched_on_every_single_invocation(self, gathered):
        """__get_auth_credentials fires before every body run, so stubbing only the proxy still makes a live call per invocation — the seam people miss."""
        tool, seam_c, _ = gathered

        for _ in range(3):
            tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert seam_c.call_count == 3

    def test_auth_is_fetched_for_the_user_being_invoked(self, gathered):
        tool, seam_c, _ = gathered

        tool.invoke_trusted(user_id="someone-else", request_kwargs={})

        assert seam_c.call_args.args[0] == "someone-else"

    def test_the_body_receives_the_credentials_it_was_given(self, tools):
        """Several tools read the user id straight out of the credentials the body was given."""
        tool = tools["NOTION_CUSTOM_GATHER_CONTEXT"]
        seen: dict[str, Any] = {}

        with (
            patch.object(
                tool,
                "_CustomTool__get_auth_credentials",
                MagicMock(return_value={"user_id": USER, "token": "secret"}),
            ),
            patch(
                "app.agents.tools.integrations.notion_tool.execute_tool",
                lambda name, params, user_id, *a, **k: seen.update(user_id=user_id) or {},
            ),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert seen["user_id"] == USER


class TestArgumentHandling:
    def test_model_authored_arguments_are_validated_before_the_body_runs(self, tools):
        """Validation must reject malformed LLM-authored args before the body runs — asserting only that something raised would still pass with validation removed, since the body then blows up on the bad value itself."""
        from pydantic import ValidationError

        tool = tools["NOTION_FETCH_PAGE_AS_MARKDOWN"]
        ran: list[str] = []

        with (
            patch.object(
                tool,
                "_CustomTool__get_auth_credentials",
                MagicMock(return_value={"user_id": USER}),
            ),
            patch(
                "app.agents.tools.integrations.notion_tool.execute_tool",
                lambda *a, **k: ran.append("body") or {},
            ),
            pytest.raises(ValidationError),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={"page_id": 12345})

        assert ran == [], "the body ran on arguments that should have been rejected"

    def test_a_required_argument_the_model_omitted_is_rejected(self, tools):
        """Reaching the provider without a required field is a confusing API error instead of a correction the model can act on."""
        from pydantic import ValidationError

        tool = tools["NOTION_FETCH_PAGE_AS_MARKDOWN"]

        with (
            patch.object(
                tool,
                "_CustomTool__get_auth_credentials",
                MagicMock(return_value={"user_id": USER}),
            ),
            pytest.raises(ValidationError),
        ):
            tool.invoke_trusted(user_id=USER, request_kwargs={})

    def test_a_user_id_in_the_models_arguments_cannot_override_the_real_one(self, gathered):
        """user_id is a separate parameter precisely so a prompt injection can't smuggle one into the arguments to read another user's workspace."""
        tool, seam_c, calls = gathered

        tool.invoke_trusted(user_id=USER, request_kwargs={"user_id": "victim"})

        assert seam_c.call_args.args[0] == USER
        assert calls[0][2] == USER
