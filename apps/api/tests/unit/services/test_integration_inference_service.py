"""Unit tests for integration_inference_service (LLM category + content inference).

Both inference helpers are best-effort: category falls back to "other" and
content to None on any failure, timeout, or contract violation — publishing
must never be blocked by the LLM.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants import integrations as integration_constants
from app.models.integration_models import Integration, StoredIntegrationTool
from app.models.mcp_config import MCPConfig
from app.models.oauth_models import IntegrationContent, IntegrationFAQ, IntegrationHowItWorksStep
from app.services.integrations import integration_inference_service as inference
from app.services.integrations.integration_inference_service import (
    _is_complete,
    _server_domain,
    infer_integration_category,
    infer_integration_content,
)

_MOD = "app.services.integrations.integration_inference_service"


def _integration(
    tools: list[StoredIntegrationTool],
    *,
    description: str = "desc",
    mcp_config: MCPConfig | None = None,
) -> Integration:
    return Integration.model_validate(
        {
            "integration_id": "int-1",
            "name": "My Tool",
            "description": description,
            "category": "custom",
            "managed_by": "mcp",
            "tools": tools,
            "mcp_config": mcp_config,
        }
    )


def _complete_content() -> IntegrationContent:
    return IntegrationContent(
        use_cases=[f"use {i}" for i in range(5)],
        how_it_works=[IntegrationHowItWorksStep(title=f"t{i}", body="b") for i in range(3)],
        faqs=[IntegrationFAQ(question=f"q{i}", answer="a") for i in range(4)],
    )


@pytest.fixture
def mock_llm():
    with (
        patch(f"{_MOD}.resolve_model", return_value=SimpleNamespace()) as m_llm,
        patch(f"{_MOD}.ainvoke_llm", new_callable=AsyncMock) as m_invoke,
        patch(f"{_MOD}.ainvoke_structured", new_callable=AsyncMock) as m_structured,
    ):
        yield SimpleNamespace(llm=m_llm, invoke=m_invoke, structured=m_structured)


class TestToolsCatalog:
    def test_lists_each_tool_with_its_first_description_sentence(self):
        tools = [
            StoredIntegrationTool(name="a", description="Reads a. Also more."),
            StoredIntegrationTool(name="b"),
        ]

        assert inference._tools_catalog(tools) == "- a: Reads a.\n- b"

    def test_skips_nameless_tools(self):
        tools = [StoredIntegrationTool(name="a"), StoredIntegrationTool(name="", description="x")]

        assert inference._tools_catalog(tools) == "- a"

    def test_none_when_empty(self):
        assert inference._tools_catalog([]) == "None"

    def test_a_huge_server_keeps_every_tool_and_stays_inside_the_budget(self):
        tools = [
            StoredIntegrationTool(name=f"tool_number_{i}", description="Does a thing. " * 20)
            for i in range(400)
        ]

        catalog = inference._tools_catalog(tools)

        assert catalog.splitlines() == [f"- tool_number_{i}" for i in range(400)]
        assert len(catalog) <= integration_constants.TOOLS_PROMPT_CHAR_BUDGET

    def test_a_large_server_shortens_descriptions_to_fit_the_budget(self):
        long_sentence = "Reads " + "very " * 60 + "much."
        tools = [StoredIntegrationTool(name=f"t{i}", description=long_sentence) for i in range(120)]

        catalog = inference._tools_catalog(tools)

        assert len(catalog.splitlines()) == 120
        assert all(
            line.startswith(f"- t{i}: Reads very") for i, line in enumerate(catalog.splitlines())
        )
        assert len(catalog) <= integration_constants.TOOLS_PROMPT_CHAR_BUDGET

    def test_a_share_of_exactly_the_minimum_still_carries_descriptions(self):
        count = 200
        floor = integration_constants.TOOL_DESCRIPTION_MIN_CHARS
        # Names sized so the per-tool share the budget leaves is exactly the minimum.
        name_len = integration_constants.TOOLS_PROMPT_CHAR_BUDGET // count - len("- : ") - floor
        names = [f"t{i:0{name_len - 1}d}" for i in range(count)]
        tools = [
            StoredIntegrationTool(name=name, description="Reads " + "every " * 20 + "record.")
            for name in names
        ]

        lines = inference._tools_catalog(tools).splitlines()

        assert [line.partition(": ")[0] for line in lines] == [f"- {name}" for name in names]
        assert all(0 < len(line.partition(": ")[2]) <= floor for line in lines)

    def test_descriptions_share_the_space_left_by_tools_without_one(self):
        """Shared across all 400 tools, the one description got 32 characters and was dropped."""
        tools = [StoredIntegrationTool(name=f"t{i}") for i in range(399)]
        tools.append(StoredIntegrationTool(name="search", description="Finds issues by text."))

        catalog = inference._tools_catalog(tools)

        assert catalog.splitlines()[-1] == "- search: Finds issues by text."
        assert len(catalog) <= integration_constants.TOOLS_PROMPT_CHAR_BUDGET


class TestServerDomain:
    def test_hostname_extracted(self):
        assert _server_domain("https://mcp.example.com/mcp") == "mcp.example.com"

    def test_credentials_never_leak(self):
        assert _server_domain("https://user:secret@mcp.example.com") == "mcp.example.com"

    def test_port_stripped(self):
        assert _server_domain("https://mcp.example.com:8080") == "mcp.example.com"

    def test_unknown_for_unparseable(self):
        assert _server_domain("not a url") == "unknown"


class TestInferIntegrationCategory:
    async def test_returns_lowercased_valid_category(self, mock_llm):
        mock_llm.invoke.return_value = SimpleNamespace(text="Productivity")

        category = await infer_integration_category(
            "My Tool",
            "desc",
            [StoredIntegrationTool(name="a")],
            "https://x.example",
            user_id="u1",
        )

        assert category == "productivity"
        assert mock_llm.llm.call_count == 1
        prompt = mock_llm.invoke.await_args.args[1][0].content
        assert "My Tool" in prompt
        assert "x.example" in prompt  # domain extracted from server_url
        # The label becomes ``agent_name`` on the llm_call wide event, which is
        # how this lane's auxiliary COGS is split from the other one-shots.
        assert mock_llm.invoke.await_args.kwargs["label"] == "integration_category"
        assert mock_llm.invoke.await_args.kwargs["config"]["configurable"]["user_id"] == "u1"

    async def test_unrecognized_category_falls_back_to_other(self, mock_llm):
        mock_llm.invoke.return_value = SimpleNamespace(text="flying-spaghetti")

        assert (
            await infer_integration_category(
                "My Tool", "desc", [], "https://x.example", user_id="u1"
            )
            == "other"
        )

    async def test_case_insensitive_match(self, mock_llm):
        mock_llm.invoke.return_value = SimpleNamespace(text="  Developer  ")

        assert (
            await infer_integration_category(
                "My Tool", "desc", [], "https://x.example", user_id="u1"
            )
            == "developer"
        )

    async def test_llm_error_falls_back_to_other(self, mock_llm):
        mock_llm.invoke.side_effect = RuntimeError("llm down")

        assert (
            await infer_integration_category(
                "My Tool", "desc", [], "https://x.example", user_id="u1"
            )
            == "other"
        )

    async def test_timeout_falls_back_to_other(self, mock_llm):
        mock_llm.invoke.side_effect = TimeoutError()

        assert (
            await infer_integration_category(
                "My Tool", "desc", [], "https://x.example", user_id="u1"
            )
            == "other"
        )


class TestInferIntegrationContent:
    async def test_returns_complete_content(self, mock_llm):
        content = _complete_content()
        mock_llm.structured.return_value = content

        result = await infer_integration_content(
            _integration([StoredIntegrationTool(name="a")]),
            "productivity",
            auth_type="oauth",
            user_id="u-1",
        )

        assert result is content

    @pytest.mark.regression
    async def test_prompt_carries_every_tool_its_description_and_the_auth(self, mock_llm):
        mock_llm.structured.return_value = _complete_content()
        tools = [
            StoredIntegrationTool(name=f"tool_{i}", description=f"Does thing {i}.")
            for i in range(60)
        ]

        await infer_integration_content(
            _integration(tools), "other", auth_type="bearer", user_id="u"
        )

        prompt = mock_llm.structured.call_args.args[1]
        assert all(f"- tool_{i}: Does thing {i}." in prompt for i in range(60))
        assert "60 in total" in prompt
        assert "paste an API token" in prompt

    async def test_prompt_names_the_integration_and_its_server(self, mock_llm):
        mock_llm.structured.return_value = _complete_content()
        config = MCPConfig(server_url="https://user:pw@mcp.linear.app:443/sse")

        await infer_integration_content(
            _integration([], mcp_config=config), "other", auth_type="oauth", user_id="u"
        )

        prompt = mock_llm.structured.call_args.args[1]
        assert "\nIntegration name: My Tool\n" in prompt
        assert "\nDescription: desc\n" in prompt
        assert "\nServer domain: mcp.linear.app\n" in prompt

    async def test_prompt_says_what_it_does_not_know(self, mock_llm):
        mock_llm.structured.return_value = _complete_content()

        await infer_integration_content(
            _integration([], description=""), "other", auth_type=None, user_id="u"
        )

        prompt = mock_llm.structured.call_args.args[1]
        assert "\nDescription: No description provided\n" in prompt
        assert "\nServer domain: unknown\n" in prompt
        assert "\nHow users connect: not specified\n" in prompt

    async def test_incomplete_content_returns_none(self, mock_llm):
        mock_llm.structured.return_value = IntegrationContent(use_cases=["only one"])

        assert (
            await infer_integration_content(
                _integration([]), "other", auth_type=None, user_id="u-1"
            )
            is None
        )

    async def test_llm_error_returns_none(self, mock_llm):
        mock_llm.structured.side_effect = RuntimeError("llm down")

        assert (
            await infer_integration_content(
                _integration([]), "other", auth_type=None, user_id="u-1"
            )
            is None
        )

    async def test_timeout_returns_none(self, mock_llm):
        mock_llm.structured.side_effect = TimeoutError()

        assert (
            await infer_integration_content(
                _integration([]), "other", auth_type=None, user_id="u-1"
            )
            is None
        )


class TestIsComplete:
    def test_complete_content_passes(self):
        assert _is_complete(_complete_content()) is True

    def test_wrong_cardinality_fails(self):
        content = _complete_content()
        content.faqs = content.faqs[:3]

        assert _is_complete(content) is False
