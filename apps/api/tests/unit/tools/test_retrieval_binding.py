"""retrieve_tools binding mode: which requested names bind, which are refused, and what is logged."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.agents.tools.core import retrieval
from app.agents.tools.core.registry import DESKTOP_TOOL_CATEGORY
from app.constants.log_tags import LogTag

SCOPE = retrieval._RetrievalScope(user_id="u1", tool_space="gmail", include_subagents=False)


def _registry(categories: dict[str, str] | None = None) -> MagicMock:
    registry = MagicMock()
    registry.get_category_of_tool.side_effect = lambda name: (categories or {}).get(name)
    registry.get_category.return_value = SimpleNamespace(require_integration=False)
    return registry


def _triage(
    names: list[str],
    *,
    bindable: set[str],
    mcp: set[str] | None = None,
    categories: dict[str, str] | None = None,
) -> retrieval._BindingTriage:
    return retrieval._triage_exact_names(
        names, _registry(categories), bindable, set(), mcp or set(), include_desktop=False
    )


class TestTriage:
    def test_a_desktop_tool_is_unknown_outside_a_desktop_session(self) -> None:
        triage = _triage(
            ["click_save", "create_todo"],
            bindable={"click_save", "create_todo"},
            categories={"click_save": DESKTOP_TOOL_CATEGORY},
        )

        assert (triage.unknown, triage.validated) == (["click_save"], ["create_todo"])

    def test_an_exact_name_binds_as_itself_when_a_spelling_variant_also_exists(self) -> None:
        triage = _triage(
            ["notion_search", "notion-search"], bindable={"notion_search"}, mcp={"notion-search"}
        )

        assert (triage.validated, triage.renamed) == (["notion_search", "notion-search"], {})


def test_out_of_scope_guidance_names_the_tools_and_who_runs_them() -> None:
    assert retrieval._binding_guidance(["GMAIL_SEND_EMAIL", "create_todo"], {}, False) == [
        "These tools are not available inside this subagent and cannot be bound here: "
        "GMAIL_SEND_EMAIL, create_todo. They belong to the main executor, not this subagent. "
        "Do not retry binding them; finish your task here and let the executor handle them."
    ]


@contextmanager
def _binding_deps(
    *, mcp_names_for: dict[str, set[str]] | None = None, unconnected: dict | None = None
) -> Iterator[MagicMock]:
    async def _mcp_names(user_id: str | None) -> set[str]:
        return (mcp_names_for or {}).get(user_id or "", set())

    with (
        patch.object(retrieval, "_user_mcp_tool_names", new=AsyncMock(side_effect=_mcp_names)),
        patch.object(
            retrieval, "_unconnected_for_tools", new=AsyncMock(return_value=unconnected or {})
        ),
        patch.object(retrieval, "_render_proxied_docs", new=AsyncMock(return_value=[])),
        patch.object(retrieval, "log") as mock_log,
    ):
        yield mock_log


class TestBindExactTools:
    async def test_the_asking_users_mcp_tools_are_accepted(self) -> None:
        with _binding_deps(mcp_names_for={"u1": {"notion-search"}}):
            result = await retrieval._bind_exact_tools(
                SCOPE, _registry(), set(), ["notion-search"], None
            )

        assert result["response"] == ["notion-search"]

    async def test_an_unconnected_tool_does_not_hide_the_unknown_names_after_it(self) -> None:
        unconnected = {"GMAIL_SEND_EMAIL": retrieval._UnconnectedIntegration("gmail", "Gmail")}
        with _binding_deps(unconnected=unconnected):
            result = await retrieval._bind_exact_tools(
                SCOPE, _registry(), set(), ["GMAIL_SEND_EMAIL", "nope_tool"], None
            )

        assert "Not found, nothing bound: nope_tool." in result["response_text"]

    async def test_dropped_and_out_of_scope_names_are_logged_for_the_operator(self) -> None:
        with _binding_deps() as mock_log:
            await retrieval._bind_exact_tools(
                SCOPE,
                _registry(),
                {"create_todo", "other_tool"},
                ["create_todo", "nope_tool", "other_tool"],
                {"create_todo"},
            )

        assert mock_log.warning.call_args_list == [
            call(
                f"{LogTag.TOOL} retrieve_tools binding dropped unknown tools",
                tool_space="gmail",
                unknown=["nope_tool"],
                available_count=1,
            ),
            call(
                "retrieve_tools binding rejected out-of-scope tools",
                tool_space="gmail",
                out_of_scope=["other_tool"],
            ),
        ]


@pytest.fixture(autouse=True)
def _no_real_resolver() -> Iterator[None]:
    with patch.object(retrieval, "resolve_tool", new=AsyncMock(return_value=None)):
        yield
