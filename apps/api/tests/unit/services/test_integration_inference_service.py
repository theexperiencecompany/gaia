"""Unit tests for integration_inference_service (LLM category + content inference).

Both inference helpers are best-effort: category falls back to "other" and
content to None on any failure, timeout, or contract violation — publishing
must never be blocked by the LLM.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.oauth_models import IntegrationContent
from app.services.integrations.integration_inference_service import (
    _is_complete,
    _server_domain,
    _tools_summary,
    infer_integration_category,
    infer_integration_content,
)

_MOD = "app.services.integrations.integration_inference_service"


def _complete_content() -> IntegrationContent:
    return IntegrationContent(
        use_cases=[f"use {i}" for i in range(5)],
        how_it_works=[{"title": f"t{i}", "body": "b"} for i in range(3)],
        faqs=[{"question": f"q{i}", "answer": "a"} for i in range(4)],
    )


@pytest.fixture
def mock_llm():
    with (
        patch(f"{_MOD}.get_helper_llm", return_value=SimpleNamespace()) as m_llm,
        patch(f"{_MOD}.ainvoke_llm", new_callable=AsyncMock) as m_invoke,
        patch(f"{_MOD}.ainvoke_structured", new_callable=AsyncMock) as m_structured,
    ):
        yield SimpleNamespace(llm=m_llm, invoke=m_invoke, structured=m_structured)


class TestToolsSummary:
    def test_joins_first_n_names(self):
        tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]

        assert _tools_summary(tools, 2) == "a, b"

    def test_skips_nameless_tools(self):
        assert _tools_summary([{"name": "a"}, {"description": "x"}], 5) == "a"

    def test_none_when_empty(self):
        assert _tools_summary([], 5) == "None"


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
            "My Tool", "desc", [{"name": "a"}], "https://x.example"
        )

        assert category == "productivity"
        assert mock_llm.llm.call_count == 1
        prompt = mock_llm.invoke.await_args.args[1][0].content
        assert "My Tool" in prompt
        assert "x.example" in prompt  # domain extracted from server_url
        # The label becomes ``agent_name`` on the llm_call wide event, which is
        # how this lane's auxiliary COGS is split from the other one-shots.
        assert mock_llm.invoke.await_args.kwargs["label"] == "integration_category"

    async def test_unrecognized_category_falls_back_to_other(self, mock_llm):
        mock_llm.invoke.return_value = SimpleNamespace(text="flying-spaghetti")

        assert (
            await infer_integration_category("My Tool", "desc", [], "https://x.example") == "other"
        )

    async def test_case_insensitive_match(self, mock_llm):
        mock_llm.invoke.return_value = SimpleNamespace(text="  Developer  ")

        assert (
            await infer_integration_category("My Tool", "desc", [], "https://x.example")
            == "developer"
        )

    async def test_llm_error_falls_back_to_other(self, mock_llm):
        mock_llm.invoke.side_effect = RuntimeError("llm down")

        assert (
            await infer_integration_category("My Tool", "desc", [], "https://x.example") == "other"
        )

    async def test_timeout_falls_back_to_other(self, mock_llm):
        mock_llm.invoke.side_effect = TimeoutError()

        assert (
            await infer_integration_category("My Tool", "desc", [], "https://x.example") == "other"
        )


class TestInferIntegrationContent:
    async def test_returns_complete_content(self, mock_llm):
        content = _complete_content()
        mock_llm.structured.return_value = content

        result = await infer_integration_content(
            "My Tool",
            "desc",
            [{"name": "a"}],
            "https://x.example",
            "productivity",
            user_id="u-1",
        )

        assert result is content

    async def test_incomplete_content_returns_none(self, mock_llm):
        mock_llm.structured.return_value = IntegrationContent(use_cases=["only one"])

        assert (
            await infer_integration_content(
                "My Tool", "desc", [], "https://x.example", "other", user_id="u-1"
            )
            is None
        )

    async def test_llm_error_returns_none(self, mock_llm):
        mock_llm.structured.side_effect = RuntimeError("llm down")

        assert (
            await infer_integration_content(
                "My Tool", "desc", [], "https://x.example", "other", user_id="u-1"
            )
            is None
        )

    async def test_timeout_returns_none(self, mock_llm):
        mock_llm.structured.side_effect = TimeoutError()

        assert (
            await infer_integration_content(
                "My Tool", "desc", [], "https://x.example", "other", user_id="u-1"
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
