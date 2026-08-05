"""A Composio custom-tool body executing through the real dispatch chain.

Nothing in the repo has ever run one. ``test_send_email_flow`` mocks the whole
service, and the unit tests stop at registration — so the code between "the
model picked a tool" and "the provider was called" was entirely unexercised:
argument validation, the auth-credentials fetch that fires on *every*
invocation, and the tool body itself.

Three seams have to be stubbed to run offline, and the plan (§2.8) is explicit
that missing any one of them still reaches the network:

* **A — proxy**: ``proxy_client._get_composio`` (gmail, calendar, docs, notion…)
* **B — hosted execute**: ``execute_tool``, patched **at each importing module**
  because consumers do ``from … import execute_tool`` and the name is bound at
  the call site — patching ``context_utils.execute_tool`` silently no-ops
* **C — dispatch**: ``CustomTool.__get_auth_credentials``, which calls
  ``connected_accounts.list`` before every single tool body runs

Seam C is the one people miss: stub A alone and the call still goes out.
"""

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

    Notion is the sample because its body goes through ``execute_tool`` (seam B)
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
        """End to end through ``invoke_trusted``: arguments validated, auth
        fetched, body run, result returned. Not a mock of the service — the
        real registered function."""
        tool, _, calls = gathered

        result = tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert calls, "the tool body never reached the provider call"
        assert result == {"relevant_pages": [{"id": "page-1", "title": "Roadmap"}]}

    def test_the_result_is_not_a_coroutine(self, gathered):
        """The failure mode the sync guard exists for, asserted on a real
        invocation rather than on the function's type."""
        import inspect

        tool, _, _ = gathered

        assert not inspect.isawaitable(tool.invoke_trusted(user_id=USER, request_kwargs={}))

    def test_the_provider_call_carries_the_invoking_user(self, gathered):
        """The tool body threads the user through to the provider. A wrong or
        missing user reads another account's data — or none."""
        tool, _, calls = gathered

        tool.invoke_trusted(user_id=USER, request_kwargs={})

        _, _, called_with_user = calls[0]
        assert called_with_user == USER


class TestSeamC:
    def test_auth_is_fetched_on_every_single_invocation(self, gathered):
        """The seam people miss. ``__get_auth_credentials`` calls
        ``connected_accounts.list`` before each body runs, so a test that stubs
        only the proxy still makes a live API call per tool call — and a suite
        that does it under load gets rate-limited rather than failing cleanly."""
        tool, seam_c, _ = gathered

        for _ in range(3):
            tool.invoke_trusted(user_id=USER, request_kwargs={})

        assert seam_c.call_count == 3

    def test_auth_is_fetched_for_the_user_being_invoked(self, gathered):
        tool, seam_c, _ = gathered

        tool.invoke_trusted(user_id="someone-else", request_kwargs={})

        assert seam_c.call_args.args[0] == "someone-else"

    def test_the_body_receives_the_credentials_it_was_given(self, tools):
        """The credentials are how a tool knows which account it is acting on;
        several tools read the user id straight out of them."""
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
        """``invoke_trusted`` validates through the request model, and it must
        reject BEFORE the body runs — otherwise malformed LLM-authored JSON
        reaches the provider and the failure surfaces as whatever the API
        happens to do with it.

        The body-never-ran assertion is the load-bearing half: asserting only
        "something raised" passes even with validation removed, because the body
        then blows up on the bad value a moment later.
        """
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
        """Models drop required fields. Reaching the provider without one is a
        confusing API error instead of a correction the model can act on."""
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
        """A security property the SDK documents and nothing tested. ``user_id``
        is a separate parameter precisely so an LLM cannot smuggle one into the
        arguments — if it could, a prompt injection would read another user's
        Notion workspace."""
        tool, seam_c, calls = gathered

        tool.invoke_trusted(user_id=USER, request_kwargs={"user_id": "victim"})

        assert seam_c.call_args.args[0] == USER
        assert calls[0][2] == USER
